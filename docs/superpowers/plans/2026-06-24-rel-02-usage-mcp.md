# Plan — Release R2: Usage accounting & MCP auth

Implements [`2026-06-24-rel-02-usage-mcp-design.md`](../specs/2026-06-24-rel-02-usage-mcp-design.md).
Contracts C1–C7. TDD per task. All commands from `backend/`.

## Dependency graph

```
T1 (usage_sink) ──┬──► T2 (router) ──┬──► T3 (planner/validator/repair) ──► T4 (orchestrator)
                  │                  │
                  │                  └──► T5 (mcp tools)
                  └──► T6 (mcp auth + server warning) — independent of T2..T5
```

## Tasks

- **T1 — Sink module + tests** · owns `app/llm/usage_sink.py` (new) + `tests/unit/test_usage_sink.py`.
  Implement `NullUsageSink`, `AccumUsageSink`, `DbUsageSink`. `DbUsageSink.observe` opens a new
  `async_session_factory()` to avoid leaking the request's session lifecycle.
- **T2 — LLMRouter wiring** · owns `app/llm/router.py` + `tests/unit/test_llm_router_usage.py`.
  Add `usage_sink` ctor + per-call override; invoke on success path of `complete()`.
- **T3 — Planner/Validator/Repair** · owns `app/agents/adaptive_planner.py`,
  `app/agents/answer_validator.py`, `app/core/query_repair.py` + their tests. Add `usage_sink`
  ctor; pass per-call into `_llm.complete(...)`.
- **T4 — Orchestrator post-call budget hard-stop (C4)** · owns `app/agents/orchestrator.py` and the
  three sub-agent constructor sites (lines ~1685 & ~2154 for `AdaptivePlanner`, plus existing
  `AnswerValidator`/`QueryRepairer` construction sites). Read the router's sink off `self._llm` if
  the orchestrator was given a router with one. At the top of each unified-loop iteration check
  `sink.budget_exceeded()` and short-circuit.
- **T5 — MCP tools usage + concurrency (C5)** · owns `app/mcp_server/tools.py` + the new
  `tests/integration/test_mcp_tools_usage.py`. Build `DbUsageSink`-bound router; acquire/release
  `agent_limiter`. Apply to both `query_database` and `search_codebase`.
- **T6 — MCP auth + server warning (C6+C7)** · owns `app/mcp_server/auth.py` + `app/mcp_server/server.py`
  + `tests/unit/test_mcp_asgi_auth.py`. Prefer explicit JWT; add startup warning.

## Integration (sequential, me)
1. Verify ownership disjoint; rebase test fixtures if needed.
2. Full gate: `make check` parity (ruff format+check, mypy, full unit+integration, coverage ≥72%).
3. DOC: CLAUDE.md note on the sink + budget hard-stop.
4. Atomic commit per task group; final R2 commit; push branch.
5. Mark R2 done in `issues.md`; pointer advances to R3.
