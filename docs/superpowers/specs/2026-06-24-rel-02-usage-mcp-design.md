# Spec — Release R2: Usage accounting & MCP auth

**Date:** 2026-06-24 · **Source:** `docs/qa-audit/issues.md` §8 R2
**Bugs:** F-MCP-01 (🟠), F-MCP-02, F-MCP-03, F-MCP-04, F-CHAT-07, F-SQL-06, F-BILL-05
**Branch:** `fix/security-audit-2026-06-24`

## Problem

Every LLM call produces a token-usage triple, but **recording is per-caller**. The chat route
records on its 4 entry points; **MCP agents never record** (F-MCP-01) and **never acquire the
agent concurrency slot** (F-MCP-02). Inside the orchestrator, `AdaptivePlanner`, `AnswerValidator`,
and `QueryRepairer` call `LLMRouter.complete()` directly and **drop the returned `usage`** —
budget under-count (F-CHAT-07, F-SQL-06). MCP auth resolves an env-set candidate key **before**
an explicit JWT, so a misconfigured `cmd_mcp_…` env value can shadow a real JWT (F-MCP-03). DNS-
rebinding host validation is opt-in (F-MCP-04). The budget gate fires pre-flight only — once over,
a long agent run still completes (F-BILL-05).

## Design

Single mechanism: a per-request **`UsageSink`** protocol observed by every LLM call.
- `LLMRouter` accepts an optional `usage_sink` ctor arg AND a per-call override.
- After each successful provider call (`_call_with_retry`), the router calls `sink.observe(...)`
  with `(usage, provider, model, model_in_request)`.
- A concrete `DbUsageSink` writes a `TokenUsage` row via `UsageService.record_usage`.
- A concrete `AccumUsageSink` (composable) adds to an in-process dict (back-compat: existing
  `accum_usage` patterns become an in-process sink + the DB sink chained).
- Callers that already record explicitly (chat route final commit) stay unchanged; the sink
  catches every *other* call site, including the planner/validator/repair ones.

For MCP, both `query_database` and `search_codebase` build the router with `DbUsageSink`, acquire
`agent_limiter` before `orchestrator.run()`, and release on completion (mirror chat). MCP auth:
treat explicit `token` (JWT) ahead of env-derived `candidate_key`. DNS-rebinding protection
becomes on-by-default when the server is mounted and `mcp_allowed_hosts` is non-empty (already so);
add a startup warning when `mcp_mount_enabled` is on but `mcp_allowed_hosts` is empty.

For the post-call budget gate (F-BILL-05): after each LLM call, the `DbUsageSink` checks the
budget; on breach, set a sticky flag on the sink. `OrchestratorAgent.run()` polls the flag at the
top of each iteration and short-circuits with a "budget exceeded" error before the next LLM call
(no force-kill mid-call; we hard-stop at the next safe boundary).

## Locked contracts

### C1 — `app/llm/usage_sink.py` (new)
```python
class UsageSink(Protocol):
    async def observe(self, *, prompt_tokens: int, completion_tokens: int, total_tokens: int,
                      provider: str, model: str) -> None: ...
    def budget_exceeded(self) -> str | None: ...     # sticky reason or None

@dataclass
class NullUsageSink:                                 # default; no-op
    async def observe(self, **_): return None
    def budget_exceeded(self) -> str | None: return None

@dataclass
class AccumUsageSink:
    totals: dict[str, int] = field(default_factory=lambda: {"prompt_tokens":0,"completion_tokens":0,"total_tokens":0})
    async def observe(self, *, prompt_tokens, completion_tokens, total_tokens, provider, model):
        self.totals["prompt_tokens"] += prompt_tokens
        self.totals["completion_tokens"] += completion_tokens
        self.totals["total_tokens"] += total_tokens or (prompt_tokens + completion_tokens)
    def budget_exceeded(self) -> str | None: return None

class DbUsageSink:
    """Persists usage per call via UsageService, and (post-call) re-checks the
    user's budget. The reason is sticky so the orchestrator can hard-stop at the
    next safe boundary (F-BILL-05)."""
    def __init__(self, *, user_id: str, project_id: str, session_id: str|None = None,
                 message_id: str|None = None, accum: AccumUsageSink | None = None) -> None: ...
    async def observe(self, *, prompt_tokens, completion_tokens, total_tokens, provider, model) -> None
    def budget_exceeded(self) -> str | None
```

### C2 — `LLMRouter` accepts and invokes the sink
- `LLMRouter.__init__(self, *, usage_sink: UsageSink | None = None)` — default `NullUsageSink`.
- `complete(..., usage_sink: UsageSink | None = None)` — per-call override.
- Inside `complete()`, after a successful `_call_with_retry`, call
  `await (usage_sink or self._sink).observe(...)` with values from `resp.usage` (default zeros).
- Streaming path **unchanged** for R2 (token deltas not aggregated by providers reliably; tracked
  as a known gap for R11).

### C3 — Planner / Validator / Repair tagged with the sink
`AdaptivePlanner.__init__(self, llm_router, usage_sink=None)`,
`AnswerValidator.__init__(self, llm, usage_sink=None)`,
`QueryRepairer.__init__(self, llm_router, usage_sink=None)` — store `self._sink`. Every
`self._llm.complete(...)` call passes `usage_sink=self._sink`. `OrchestratorAgent` constructs them
with the same sink it uses on the router (`self._llm._sink`). No public API change for tests
(default `None` → router's sink).

### C4 — Orchestrator: post-call budget hard-stop
Inside `OrchestratorAgent.run()` main loop, **before** each LLM iteration, call
`reason = self._sink.budget_exceeded() if self._sink else None`; if set, short-circuit the run with
`AgentResponse(error=reason, response_type="error", ...)` (no further LLM calls). Applied at the
top of the orchestrator iteration loop in `_run_unified_loop` (the one place every iteration goes
through).

### C5 — MCP: usage + concurrency + post-call budget
In `app/mcp_server/tools.py::query_database` and `::search_codebase`:
1. Replace `LLMRouter()` with `LLMRouter(usage_sink=DbUsageSink(user_id=user_id, project_id=project_id))`.
2. Acquire `agent_limiter` slot **before** `orchestrator.run()`, release in `finally`. Mirror chat:
   ```python
   limit_err = await agent_limiter.acquire(user_id)
   if limit_err: raise ToolError(limit_err)
   try:
       resp = await orchestrator.run(ctx)
   finally:
       await agent_limiter.release(user_id)
   ```
3. No need to change the orchestrator — it picks the sink off the router and threads it down via C3.

### C6 — MCP auth: prefer explicit JWT over env candidate (F-MCP-03)
`app/mcp_server/auth.py::authenticate`: when both an explicit `token` (JWT) and an env-derived
`candidate_key` exist, **try the JWT first**. If `token` is provided, attempt JWT resolution; on
failure, raise (do not silently fall through to the env key). The explicit per-call credential is
always more authoritative than the operator's env default.

### C7 — MCP DNS-rebinding warning (F-MCP-04)
`app/mcp_server/server.py` (or startup hook): when `settings.mcp_mount_enabled and
not settings.mcp_allowed_hosts`, log a startup `WARNING`: "MCP mounted with empty
MCP_ALLOWED_HOSTS — DNS-rebinding Host validation is disabled." (Operators self-host and may want
this off; we don't fail-closed — but the silent state is the bug.)

## Test plan (TDD per task)

- `tests/unit/test_usage_sink.py` (new) — `NullUsageSink` is no-op; `AccumUsageSink` totals
  correctly; `DbUsageSink.observe` calls `UsageService.record_usage` with the right kwargs;
  `DbUsageSink.budget_exceeded` returns a string after a `BudgetExceededError`, None otherwise.
- `tests/unit/test_llm_router_usage.py` (new) — patching the provider, the router invokes
  `sink.observe` with the response usage; per-call sink overrides the ctor sink; no observe on
  total failure.
- `tests/unit/test_adaptive_planner.py` / `test_answer_validator.py` / `test_query_repair.py`
  (extend existing) — passing a sink, the LLM-mock's usage flows into `sink.totals`.
- `tests/integration/test_mcp_tools_usage.py` (new) — patch the orchestrator and assert
  `agent_limiter.acquire` was awaited and a `TokenUsage` row landed.
- `tests/unit/test_mcp_asgi_auth.py` (extend) — JWT preferred when both env+JWT present.

## DOC updates (DoD)
- `CLAUDE.md` "Multi-tenancy & access control" / "LLM routing & observability": add a one-liner
  on the per-request usage sink + post-call budget gate.
- `CLAUDE.md` MCP paragraph: confirm usage + `agent_limiter` parity with chat.

## Verification & deploy
`make check` green. Branch → PR (#172). Prod merge = gated human step. Post-deploy: `/api/health` +
Heroku logs; close the 7 bugs in `issues.md`.

## Parallelization (non-overlapping file ownership)
- **T1** `app/llm/usage_sink.py` (new) + `tests/unit/test_usage_sink.py` (C1).
- **T2** `app/llm/router.py` + `tests/unit/test_llm_router_usage.py` (C2). Depends on T1.
- **T3** `app/agents/adaptive_planner.py` + `app/agents/answer_validator.py` +
  `app/core/query_repair.py` (+ their tests) (C3). Depends on T1+T2.
- **T4** `app/agents/orchestrator.py` (C4) — post-call budget short-circuit + thread the sink to
  T3 helpers. Depends on T3.
- **T5** `app/mcp_server/tools.py` + `tests/integration/test_mcp_tools_usage.py` (C5).
  Depends on T1+T2.
- **T6** `app/mcp_server/auth.py` + `tests/unit/test_mcp_asgi_auth.py` (C6) +
  `app/mcp_server/server.py` startup warning (C7). Independent.

Order: T1 → (T2, T6 in parallel) → (T3, T5 in parallel) → T4 → integration glue + DOC + gate.
