# Plan — W3 Orchestrator reasoning/termination/observability + path unification (TDD + subagent-driven)

Spec: `docs/superpowers/specs/2026-07-02-intelligence-remediation-design.md` (§2 contracts
C-B/C-C/C-G — CONSUMED verbatim below; §3 W3 scope). Audit: `docs/INTELLIGENCE_AUDIT_2026-07.md`
§2 (ORCH-* rows) + prod-validation table (24% fail, `step_limit_reached`, 164k avg tokens/req,
`steps_used` avg 1.1 / max 7 with cap=100, `pipeline_complete`=1 vs sql_result 56 / text 80).

Branch: `feat/w3-orchestrator-2026-07-02`. Every task: **failing test → confirm fail → minimal
impl → confirm pass → conventional commit**. Status protocol: DONE / DONE_WITH_CONCERNS /
NEEDS_CONTEXT / BLOCKED. Two-stage review per task (spec compliance, then code quality).

Test conventions (from `tests/unit/test_orchestrator_audit_fixes.py` +
`tests/unit/test_stage_executor_audit_fixes.py`): pytest, `asyncio_mode=auto` (no
`@pytest.mark.asyncio` needed but existing tests use it — keep it), run with
`backend/.venv/bin/pytest`. `mock_llm` = `MagicMock()` with `router.complete = AsyncMock()` and
`router.get_context_window = MagicMock(return_value=128_000)`. `mock_tracker` =
`MagicMock(spec=WorkflowTracker)` with `begin/end/emit = AsyncMock()`, `has_ended =
MagicMock(return_value=False)`, and `step` = a `@asynccontextmanager` `fake_step` yielding None.
`_StubSink` (scripted `budget_exceeded() -> str | None`, async `observe`). `LLMResponse`,
`ToolCall` from `app.llm.base`. Directly invoke `orch._run_tool_loop(...)` / `orch.run(...)`.

---

## Precondition — W0 deliverables this wave CONSUMES

W3 is in **Group G3** (after W0). Hard edges: **W3.A01/A02 → W0.ResultValidation** and the whole
wave assumes **W0 helper-extraction of `orchestrator.py`** (partial `ORCH-A04`) has landed.

### C-B/C-C — `app/agents/result_validation.py` (W0 builds; verbatim, DO NOT redefine)
```python
@dataclass
class ResultDirective:
    action: Literal["accept", "warn", "requery", "block"]
    reason: str
    hints: list[str] = field(default_factory=list)   # e.g. repair guidance

class ResultValidation:
    def __init__(self, data_gate: DataGate, result_gate: AgentResultValidator, *,
                 reconcile: Callable[[Sequence[Any]], bool] = sql_results_reconcile) -> None: ...
    def evaluate(self, qr: QueryResult, *, question: str, sql: str,
                 truncated: bool | None = None) -> ResultDirective: ...   # SYNC — no AgentContext
```
- `evaluate` is **synchronous** — do NOT `await` it — and takes no `AgentContext`; pass `truncated=`
  to override `qr.truncated`. The collaborators are the real `AgentResultValidator` result-gate and
  the free function `sql_results_reconcile` — there is **no** `SqlResultGate`/`SqlResultReconciliation`.
- Composes `DataGate` hard-checks (Decimal-aware, `qr.truncated`-aware), the `AgentResultValidator`
  gate, zero-rows re-query + `sql_results_reconcile` reconciliation. Invoked by **both** the flat loop
  (`orchestrator._run_tool_loop` post-dispatch) and the pipeline (`stage_executor._run_sql_stage`).
  Closes `ORCH-A01`, `DATA-06`.
- `AnswerQualityGate` (thin wrapper over `AnswerValidator`, W0) — invoked by both the flat-loop and
  `response_builder.build_pipeline_response`. Closes `ORCH-A02`. W0 exposes:
  ```python
  class AnswerQualityGate:
      def __init__(self, validator: AnswerValidator) -> None: ...
      async def evaluate(self, *, question: str, answer: str,
                         sql_summaries: list[str] | None = None,
                         preferred_provider: str | None = None,
                         model: str | None = None) -> ResultDirective: ...   # ASYNC
  ```
  It takes the `AnswerValidator` directly (not `llm`/`usage_sink`) and returns a `ResultDirective`
  (`action in {"accept","warn","requery","block"}`), NOT an `AnswerValidationResult`. The underlying
  `AnswerValidationResult` verdict (`addresses_question`, `confidence`, `reason`, `is_partial`) is
  mapped inside the gate onto `ResultDirective.action` (a not-`addresses_question` verdict →
  `requery` when `is_partial` else `warn`).

### C-G — observability (W0 builds columns + migration; W3 populates)
- `RequestTrace` (`app/models/request_trace.py`) gains **`route`**, **`complexity`**,
  **`estimated_queries`** columns (W0 Alembic migration; back-compat server defaults:
  `route="unknown"`, `complexity="unknown"`, `estimated_queries=0`). W3 writes them from
  `route_result` into `context.extra` and `RequestMetrics`.
- `RequestMetrics` (`app/core/metrics.py`) already carries `route`/`complexity`; W0 adds
  `estimated_queries: int = 0` to the dataclass + its Prometheus labels. W3 populates it.
- New metrics (W0 registers; other waves emit): `retrieval_degraded_total`, `datagate_block_total`,
  `filter_guard_degrade_total`. W3 does **not** own these; it only records route/complexity/est.
- Termination knobs (C-G): `max_orchestrator_iterations` default → **20** (W0 flips the default in
  `app/config.py`; T1 below asserts + wires the live signal). Wrap-up gated on
  `iteration > 0 AND ≥1 successful data-retrieval`, excluding static prompt tokens (T2). No-tool-call
  turn with zero data on a data route re-prompts once (T3).

> **Assumption (surface early, do not block):** W0's decomposition of `_run_tool_loop` (~950 LOC)
> extracts named helpers but leaves the loop body in `orchestrator.py`. A01/A02 need two clean
> seams: (a) a **post-dispatch SQL hook** right where the flat loop currently builds
> `gate_directive`/`recon_note` (`orchestrator.py:1458-1475`) — W0 should expose this as a helper
> `_apply_result_validation(...)` or leave the inline block editable; (b) the **pipeline final-answer
> seam** in `response_builder.build_pipeline_response` (`response_builder.py:78-104`). If W0 did NOT
> extract (a) into a helper, A01 edits the inline block directly (still single-file-owned by W3).
> A02 must run the gate **outside** `build_pipeline_response` (it is sync + has no LLM) — the plan
> wires it in `_run_complex_pipeline` (`orchestrator.py:2037`) and passes the verdict in. See T9/T10.

---

## Dependency graph / groups

W3 owns (per spec §3/§5): `orchestrator.py`, `router.py`, `adaptive_planner.py`,
`stage_executor.py` (only `_run_sql_stage` SQL-gate seam + retry-budget), `query_planner.py`,
`prompts/orchestrator_prompt.py`, `prompts/planner_prompt.py`, `context_planner.py`,
`response_builder.py`, `stage_validator.py` (P01 text-stage scope). No file overlaps W1/W2/W4/W5/W6.

- **G3a (sequential glue — routing signal + termination; shared `orchestrator.py`/`router.py`):**
  T1 (ORCH-T01) → T2 (ORCH-T02) → T3 (ORCH-T03) → T4 (ORCH-A03). These all edit `_run_tool_loop`
  / `run()` in `orchestrator.py`; sequence them to avoid self-conflict.
- **G3b (parallel with G3a — disjoint files):**
  - T5 (ORCH-PR01) — `prompts/orchestrator_prompt.py` + synthesis-string de-dup
  - T6 (ORCH-CP01/CP02) — `context_planner.py` word-boundary + hot-path invocation
  - T7 (ORCH-P01) — `stage_validator.py` + `query_planner.py`/`planner_prompt.py` (text-stage scope)
  - T8 (ORCH-P02/P03 + RP01/RP02) — `adaptive_planner.py` + `planner_prompt.py` + `orchestrator.py`
    replan carry-over (RP01) & learnings tool-name (RP02). **RP01/RP02 touch `orchestrator.py`** →
    sequence T8 **after** G3a (or split RP01/RP02 into T8b run after T4). Marked `depends:[T4]`.
- **G3c (sequential glue — path unification via W0 ResultValidation/AnswerQualityGate):**
  T9 (ORCH-R01 + ORCH-P04) → T10 (ORCH-A01) → T11 (ORCH-A02) → T12 (ORCH-P01 pipeline text scope
  glue if needed). All edit `orchestrator.py` / `stage_executor.py` / `response_builder.py` — must
  be sequential and after G3a (they share `run()` and the pipeline path). `depends:[T4]`.
- **G3d (Low batch, one task):** T13 (ORCH-A05, V01, V02, PR03, PR04, R03, R04).
- **G3e (integration):** T14 — full suite + `make check` + docs.

Topo order: T1→T2→T3→T4 ; {T5,T6,T7} ∥ ; T8(dep T4) ; T9→T10→T11→T12 (dep T4) ; T13 ; T14.

---

### T1 — ORCH-T01: make the step budget a live termination signal  [G3a]
`depends:[]` (consumes W0 default flip `max_orchestrator_iterations=20`).

**Problem (audit, prod-confirmed):** `max_orchestrator_iterations=100` (`config.py:254`) makes
`step_pct = (iteration+1)/max_iter` (`orchestrator.py:1105`) contribute nothing to `budget_pct`
before wall-clock/context-fill dominate — prod shows `steps_used` avg **1.1**, max 7, cap 100. The
step lever is dead. W0 sets the default to **20**; this task asserts the loop actually **converges**
(terminates) at the realistic cap and that the emergency-synthesis `step_pct` term now bites near
the cap.

**Files:** `backend/app/agents/orchestrator.py` (`_run_tool_loop` — confirm `max_iter` at line 1061
uses `settings.max_orchestrator_iterations`; the emergency-synthesis `step_pct` at 1105-1107 already
reads `max_iter`); `backend/tests/unit/test_orchestrator_termination.py` (NEW).

**Interfaces:** reads `settings.max_orchestrator_iterations` (W0 default = 20); no new signatures.

Steps:
- [ ] Write failing test `tests/unit/test_orchestrator_termination.py::test_loop_terminates_at_step_cap`.
      Build `orch` (fixtures copied from `test_orchestrator_audit_fixes.py`). Script `mock_llm.complete`
      to **always** return a tool-call (`LLMResponse(content="", tool_calls=[ToolCall(id="c1",
      name="search_codebase", arguments={"question":"q"})])`) so the loop never self-terminates on a
      no-tool-call turn. Stub the dispatcher: `orch._dispatcher.dispatch = AsyncMock(return_value=("ok",
      None))`. Monkeypatch `settings.max_orchestrator_iterations = 20`,
      `settings.agent_wall_clock_timeout_seconds = 10_000` (so wall-clock never trips) and
      `settings.agent_emergency_synthesis_pct = 0.90`. Call
      `resp = await orch._run_tool_loop(base_context, "wf-1", has_connection=False, db_type=None,
      has_kb=True, has_mcp=False, has_repo=False, table_map="", project_overview="",
      recent_learnings="", tools=get_orchestrator_tools(has_knowledge_base=True))`. Assert
      `resp.steps_total == 20` and `resp.steps_used <= 20` and `resp.response_type` in
      `{"step_limit_reached","knowledge","text"}` (it terminated, did not run 100 iters). Assert
      `mock_llm.complete.await_count <= 21` (≤ max_iter + 1 synthesis).
- [ ] Run: `cd backend && .venv/bin/pytest tests/unit/test_orchestrator_termination.py -k step_cap -v`
      → **confirm it currently reads whatever default is in config**; if W0's flip to 20 has NOT yet
      merged, the test fails on `steps_total == 100`. Expected fail msg: `assert 100 == 20`.
- [ ] Minimal impl: no code change if W0 already flipped the default. If W0 has NOT flipped yet
      (BLOCKED on W0), set `max_orchestrator_iterations: int = 20` in `app/config.py` **and** update
      `.env.example` + the docstring at `config.py:249-253` (replace "set generously (matches the
      documented default)" with "realistic step cap — the step budget is a live termination signal
      (ORCH-T01); wall-clock still bounds a request"). This is the fallback path — coordinate with W0.
- [ ] Add `test_step_pct_drives_emergency_synthesis_near_cap`: same setup but
      `settings.max_orchestrator_iterations = 4`, `agent_emergency_synthesis_pct = 0.90`; the loop
      must enter synthesis (append the EMERGENCY system message) by iteration 4 because
      `step_pct = 4/4 = 1.0 ≥ 0.90`. Assert the last `mock_llm.complete` call's `messages` contains a
      system message starting with `"EMERGENCY:"`. (Verifies the step term now bites at the low cap.)
- [ ] Run the file green: `.venv/bin/pytest tests/unit/test_orchestrator_termination.py -v`.
- [ ] Commit: `fix(orchestrator): make step budget a live termination signal (ORCH-T01)`.

**DoD:** loop provably terminates at the realistic cap; `steps_total` reflects it; step_pct
contributes to emergency synthesis; test file green; `make lint` clean.

---

### T2 — ORCH-T02: gate wrap-up on iter>0 AND ≥1 successful data-retrieval; exclude static tokens  [G3a]
`depends:[T1]`.

**Problem (audit `orchestrator.py:1109-1169`):** a large schema/rules/learnings payload can push
`should_wrap_up(messages, loop_budget)` (or `budget_pct`) over the threshold at **iteration 0-1**,
forcing synthesis with **zero data gathered**. The wrap-up estimate counts the static system prompt
(schema/rules) which is fixed cost, not analysis progress.

**Files:** `backend/app/agents/orchestrator.py` (`_run_tool_loop`, the `if not synthesis_phase and
(budget_pct >= emergency_pct or should_wrap_up(...))` block at 1109-1139);
`backend/tests/unit/test_orchestrator_termination.py` (extend).

**Interfaces:** no new public signatures. Track a local
`successful_data_retrievals: int = 0` incremented right where the loop records a successful data tool
(near `executed_questions.append(...)`, `orchestrator.py:1484-1492` — any `tc.name in
ToolDispatcher._DEDUP_TOOL_NAMES` call with `sub_result is not None and not gate_flagged`). Compute a
`data_ready = iteration > 0 and successful_data_retrievals >= 1` guard on the **context-fill**
wrap-up branch (NOT the hard emergency `budget_pct >= emergency_pct` branch — that stays as a real
safety valve). Exclude static prompt from the estimate by measuring wrap-up against
`estimate_messages_tokens(messages) - static_prompt_tokens` where `static_prompt_tokens =
LLMRouter.estimate_tokens(system_prompt)` captured once before the loop.

Steps:
- [ ] Failing test `test_no_premature_wrapup_with_zero_data`: build `orch`; craft an oversized
      `system_prompt` implicitly by passing a huge `table_map` (e.g. `"t(" + "col," * 20000 + ")"`) so
      `should_wrap_up` would trip at iter 0. Script `mock_llm.complete` to return a `query_database`
      tool-call on iter 0 (data NOT yet gathered), then a no-tool-call answer on iter 1. Stub
      `orch._dispatcher.dispatch` to return `("42 rows", <a SQLAgentResult with results.rows=[[1]]>)`.
      Assert the **first** LLM call (iter 0) was made **with tools** (`tools is not None` /
      non-empty) — i.e. the loop did NOT jump straight to synthesis (`effective_tools = None`) on
      iter 0. Concretely: inspect `mock_llm.complete.call_args_list[0].kwargs["tools"]` is truthy.
- [ ] Run: `.venv/bin/pytest tests/unit/test_orchestrator_termination.py -k premature_wrapup -v` →
      confirm fail (currently the huge static prompt trips `should_wrap_up` at iter 0 → tools=None).
- [ ] Minimal impl in `_run_tool_loop`:
      - Before the loop: `static_prompt_tokens = LLMRouter.estimate_tokens(system_prompt)` and
        `successful_data_retrievals = 0`.
      - Change the context-fill branch condition from
        `budget_pct >= emergency_pct or should_wrap_up(messages, loop_budget)`
        to keep the hard `budget_pct >= emergency_pct` unchanged but gate the soft trigger:
        ```python
        data_ready = iteration > 0 and successful_data_retrievals >= 1
        dynamic_tokens = max(0, estimate_messages_tokens(messages) - static_prompt_tokens)
        soft_wrap = should_wrap_up(messages, loop_budget) and dynamic_tokens > int(
            loop_budget * 0.30
        )
        if not synthesis_phase and (
            budget_pct >= emergency_pct or (data_ready and soft_wrap)
        ):
            ...
        ```
        (i.e. a context-fill wrap-up requires that at least one successful data-retrieval happened
        AND that the *dynamic* content — not the static prompt — is actually large.)
      - Increment `successful_data_retrievals += 1` inside the existing successful-data-tool record
        block (guard `tc.name in ToolDispatcher._DEDUP_TOOL_NAMES and tc.id not in skipped_map and
        sub_result is not None and not gate_flagged`).
- [ ] Add `test_hard_emergency_still_wraps_at_iter0`: with `agent_emergency_synthesis_pct=0.01` and a
      huge prompt, assert the loop STILL enters synthesis at iter 0 (the hard budget branch is
      untouched — honest degradation preserved).
- [ ] Run file green; commit: `fix(orchestrator): gate wrap-up on data gathered + exclude static prompt (ORCH-T02)`.

**DoD:** premature zero-data synthesis regression covered; hard emergency valve intact; green.

---

### T3 — ORCH-T03: re-prompt once on a no-tool-call, zero-data turn on a data route  [G3a]
`depends:[T2]`.

**Problem (audit `orchestrator.py:1240-1254`):** the loop terminates on the **first** no-tool-call
turn. A "let me think…" text turn with **no data gathered** on a data route (`route` in
{query,knowledge,git,mcp,explore}) ships a non-answer. Re-prompt **once** before terminating.

**Files:** `backend/app/agents/orchestrator.py` (the `if not llm_resp.tool_calls:` block at 1240);
`backend/tests/unit/test_orchestrator_termination.py` (extend).

**Interfaces:** uses `route_result: RouteResult | None` (already a param). A route is a "data route"
when `route_result is not None and not route_result.is_direct` (or `route_result is None`, be
conservative → treat as data route). Track `reprompted_no_data: bool = False` local.

Steps:
- [ ] Failing test `test_reprompts_once_on_no_tool_zero_data`: `mock_llm.complete` returns a
      **no-tool-call** `LLMResponse(content="Let me think about this.")` on iter 0, then a
      `query_database` tool-call on iter 1, then a final no-tool answer on iter 2. `route_result =
      RouteResult(route="query", complexity="moderate", approach="", estimated_queries=1,
      needs_multiple_data_sources=False)`. Stub dispatch to return rows. Assert the loop did **not**
      terminate at iter 0: `mock_llm.complete.await_count >= 2` and the answer is the final one (not
      "Let me think about this."). Assert a re-prompt system message was appended (content contains a
      cue like `"You have not gathered any data yet"`).
- [ ] Add `test_no_reprompt_when_data_already_gathered` (a no-tool turn AFTER a successful query
      terminates normally — the fix must not loop forever) and
      `test_no_reprompt_on_direct_route` (`route_result.is_direct` → terminate immediately even with
      zero data — direct is conversational).
- [ ] Run: confirm fail (`await_count == 1` today).
- [ ] Minimal impl in the `if not llm_resp.tool_calls:` block:
      ```python
      is_data_route = route_result is None or not route_result.is_direct
      no_data_yet = successful_data_retrievals == 0 and not all_sql_results and not knowledge_sources \
          and not has_mcp_result
      if is_data_route and no_data_yet and not reprompted_no_data and not synthesis_phase:
          reprompted_no_data = True
          await self._tracker.emit(wf_id, "thinking", "in_progress",
              "No data gathered yet — asking the agent to use a tool…")
          messages.append(Message(role="system", content=(
              "You have not gathered any data yet, but this question needs data from your "
              "sources. Call the appropriate tool now (do not answer from prior knowledge). "
              "If the question truly needs no data, say so explicitly.")))
          continue
      # else: existing terminate-on-no-tool-call path unchanged
      ```
      Guard against an infinite re-prompt with the one-shot `reprompted_no_data` flag; the
      `not synthesis_phase` guard prevents fighting the emergency valve.
- [ ] Run file green; commit: `fix(orchestrator): re-prompt once on no-tool zero-data data-route turn (ORCH-T03)`.

**DoD:** the three termination tests green; no infinite loop; direct route unaffected.

---

### T4 — ORCH-A03: write route/complexity/estimated_queries into context.extra + RequestMetrics (C-G)  [G3a]
`depends:[T3]` (consumes W0 RequestTrace columns + `RequestMetrics.estimated_queries`).

**Problem (audit `orchestrator.py:1749,2027`):** `complexity` is read from `context.extra` in the
metrics call but **never written**, so metrics log `"unknown"` and mis-routes are unmeasurable. The
`route`/`estimated_queries` from `route_result` are dropped.

**Files:** `backend/app/agents/orchestrator.py` (`run()` — after `route_result` is computed at
~544-555, before the branch dispatch; and the two `record_request` sites at 1746 and 2024);
`backend/tests/unit/test_orchestrator_routing_metrics.py` (NEW).

**Interfaces (C-G, verbatim consumption):**
- Write into `context.extra` immediately after `route_result` is set (both the continuation branch at
  536-543 and the real route branch at 544-555 — do it once after the `if/else`):
  ```python
  context = replace(context, extra={
      **context.extra,
      "route": route_result.route,
      "complexity": route_result.complexity,
      "estimated_queries": route_result.estimated_queries,
  })
  ```
- Pass through to `RequestMetrics` at both sites:
  `route=str(context.extra.get("route") or "unified")` — keep the existing `"unified"` /
  `"complex_pipeline"` literals as the metrics `route` label (that is the *execution path*), and
  additionally add `estimated_queries=int(context.extra.get("estimated_queries") or 0)` and
  `complexity=str(context.extra.get("complexity") or "unknown")`. Do **not** collapse the two
  meanings: `route` label = execution path; `complexity`/`estimated_queries` = router signal now
  populated. (This preserves the existing `route="unified"` metric semantics the dashboards use.)
- `RequestMetrics(estimated_queries=...)` — field added by W0. If W0 has not added it (BLOCKED), add
  `estimated_queries: int = 0` to the dataclass in `app/core/metrics.py` and its Prometheus label in
  `record_request` (`("estimated_queries", str(metrics.estimated_queries))`), then note the overlap
  with W0 for review.

Steps:
- [ ] Failing test `tests/unit/test_orchestrator_routing_metrics.py::test_complexity_written_to_context_extra`.
      Patch `route_request` (import site `app.agents.orchestrator.route_request`) with an `AsyncMock`
      returning `RouteResult(route="query", complexity="complex", approach="a", estimated_queries=4,
      needs_multiple_data_sources=False)`. Capture `RequestMetrics` by monkeypatching
      `app.core.metrics.get_metrics_collector().record_request` (or patch
      `app.agents.orchestrator.get_metrics_collector`) to record into a list. Drive the **unified**
      path (no connection → not `use_complex_pipeline and has_connection`; but `complexity="complex"`
      + no connection means the `use_complex_pipeline and has_connection` guard is False → unified).
      Stub `mock_llm.complete` to return a no-tool answer immediately. Assert the recorded
      `RequestMetrics.complexity == "complex"` and `.estimated_queries == 4` (NOT `"unknown"`/`0`).
- [ ] Add `test_route_signal_survives_into_metrics_on_complex_path`: with `connection_config` set and
      `complexity="complex"`, drive `_run_complex_pipeline` (mock `AdaptivePlanner.plan` →
      one-stage plan, mock `StageExecutor.execute` → completed result) and assert the pipeline-path
      `RequestMetrics.complexity == "complex"` and `.estimated_queries` propagated.
- [ ] Run: confirm fail (`complexity == "unknown"`).
- [ ] Minimal impl per Interfaces above.
- [ ] (If W0 added the RequestTrace columns + trace-persistence reads `context.extra`) add
      `test_trace_persistence_reads_route_signal` only if W0 wired the read; otherwise leave a note
      that trace-column population is a W0 responsibility and W3 only guarantees `context.extra` is
      populated. **Do not** edit `trace_persistence*.py` in W3 (not W3-owned).
- [ ] Run green; commit: `feat(orchestrator): record route/complexity/estimated_queries (ORCH-A03, C-G)`.

**DoD:** metrics no longer log `"unknown"` complexity; `context.extra` carries the 3 signals on both
paths; green. Update `CLAUDE.md` LLM-routing/observability bullet if it claims complexity is logged.

---

### T5 — ORCH-PR01: de-duplicate the triple-stated prompt guidance + stale self-description  [G3b]
`depends:[]` (disjoint file from G3a).

**Problem (audit `orchestrator_prompt.py`, ORCH-PR01-04):** (1) the reconciliation instruction
("When multiple SQL queries produce the same grand total, do NOT claim an earlier query was
wrong…") is stated **3×** — orchestrator PRINCIPLES (`orchestrator_prompt.py:181-183`), the emergency
synthesis message (`orchestrator.py:1123-1127`), and the synthesis-message builder
(`response_builder.py:314-316`). Token waste on every request (prod avg 164k tokens). (2) The module
docstring + prompt describe the orchestrator as a *router* (stale post unified-loop).

**Files:** `backend/app/agents/prompts/orchestrator_prompt.py`;
`backend/tests/unit/test_orchestrator_prompt.py` (NEW or extend if exists).
**Do NOT** edit the emergency-synthesis string in `orchestrator.py` or the builder in
`response_builder.py` in this task (those are the load-bearing single-shot restatements at the actual
synthesis moment — keeping ONE canonical statement in the *system prompt* and ONE at the *synthesis
moment* is the intended de-dup; remove only the redundant third copy). Concretely: **remove** the
reconciliation sentence from the always-on PRINCIPLES block (it is re-injected at synthesis where it
matters) — that is the copy paid on every iteration.

**Interfaces:** `build_orchestrator_system_prompt(...)` signature unchanged.

Steps:
- [ ] Failing test `test_reconciliation_guidance_not_in_principles`: call
      `build_orchestrator_system_prompt(has_connection=True, db_type="postgres")` and assert the
      returned prompt does **not** contain `"do NOT claim an earlier query was wrong"` (moved to the
      synthesis-moment messages only). Also assert `test_self_description_not_router`: the prompt/
      docstring no longer calls the orchestrator a "router" in the module docstring — assert
      `"router" not in build_orchestrator_system_prompt.__module__`'s docstring is too weak; instead
      assert the built prompt contains `"coordinate specialized sub-agents"` (kept) and that the top
      docstring is updated (checked via reading the module source in the test:
      `import app.agents.prompts.orchestrator_prompt as m; assert "focuses on *routing*" not in
      (m.__doc__ or "")`).
- [ ] Run: confirm fail.
- [ ] Minimal impl: delete the reconciliation sentence from the PRINCIPLES block
      (`orchestrator_prompt.py:181-183`). Update the module docstring (lines 1-5) from "focuses on
      *routing* — deciding which sub-agent to invoke rather than executing tools directly" to
      "drives a unified tool-calling loop: it gathers data via sub-agent tools and synthesizes the
      final answer (it is not a pure router)."
- [ ] Add `test_language_caveat_present` (PR04): assert the PRINCIPLES still contain the LANGUAGE
      mirroring instruction (regression guard — don't over-delete).
- [ ] Run green; commit: `refactor(prompts): de-dup reconciliation guidance + fix stale self-description (ORCH-PR01)`.

**DoD:** the triple-statement is now a single canonical system-prompt line + synthesis-moment lines;
docstring current; green. (PR03 intermediate-analysis language-mirroring is folded into T13.)

---

### T6 — ORCH-CP01 + ORCH-CP02: word-boundary cue matching + invoke ContextPlanner on the hot path  [G3b]
`depends:[]` (CP01 disjoint file; CP02 documents-or-wires — see note).

**Problem (audit `context_planner.py:96-154`, CP01):** naive substring cue match
(`any(cue in q for cue in cues)`) fires `"code"` on "country **code**" and `"drop"` on "**drop**-off"
→ spurious RAG/INSIGHTS category loading, defeating the token-saving purpose. **CP02**
(`orchestrator.py:803-888`): `ContextPlanner` is not invoked on the hot unified path; all categories
eager-loaded via `_run_unified_agent`.

**Files:** `backend/app/agents/context_planner.py` (`_plan_heuristic` cue loop + `_CUES`);
`backend/tests/unit/test_context_planner.py` (extend).

**Interfaces:** `ContextPlanner.plan(...)` / `ContextPlan` unchanged. Add a module-level
`_word_match(q: str, cue: str) -> bool` using `re` word boundaries for single-word cues and plain
`in` for multi-word phrase cues:
```python
import re
_WORD_CACHE: dict[str, re.Pattern[str]] = {}
def _word_match(q: str, cue: str) -> bool:
    if " " in cue:            # phrase cue ("where is", "how does") — substring is fine
        return cue in q
    pat = _WORD_CACHE.get(cue)
    if pat is None:
        pat = _WORD_CACHE[cue] = re.compile(rf"\b{re.escape(cue)}\b")
    return bool(pat.search(q))
```

Steps:
- [ ] Failing test `test_country_code_does_not_trigger_rag`: `p = await ContextPlanner().plan(
      "show me the country code distribution", has_connection=True, has_repo=False)`; assert
      `not p.wants(ContextNeed.RAG)` (today `"code" in q` fires RAG). Add
      `test_dropoff_does_not_trigger_insights`: question "analyze the drop-off funnel" must not fire
      INSIGHTS via the bare `"drop"` cue — assert `ContextNeed.INSIGHTS not in p.needs` unless another
      cue legitimately fires (question has no other insights cue). Add positive guard
      `test_real_code_word_triggers_rag`: "explain the login **function**" with `has_repo=True` →
      `p.wants(ContextNeed.RAG)` still True.
- [ ] Run: confirm fail (RAG fires on "country code").
- [ ] Minimal impl: replace `if any(cue in q for cue in cues):` with
      `if any(_word_match(q, cue) for cue in cues):` in `_plan_heuristic`. Drop the over-broad
      single-char/ambiguous cues per audit: remove `"drop"` from INSIGHTS `_CUES` (keep `"drop-off"`
      only if desired — add `"drop-off"` as an explicit phrase cue). Keep `"code"` in RAG but it is
      now word-boundary safe (won't hit "country code" because that is two words — `\bcode\b` matches
      "code" as a token; "country code" DOES contain the token "code" → still matches!). **So also**
      remove the bare `"code"` cue from RAG `_CUES` and rely on `"function"`, `"class"`, `"module"`,
      `"implementation"`, `"file"`, `"how does"`, `"architecture"` (word-boundary). Adjust the test
      accordingly and assert the final cue set.
- [ ] **CP02 (choose one, document the choice in the commit body):**
      - *Option A (wire — preferred if `context_planner_enabled` is the gate):* NOT in scope for W3 —
        the full ContextPack runtime wiring is **W2** (`RET-R1`, `context_planner_enabled`). So for
        W3, **document** where pruning happens: add a code comment at `_run_unified_agent`
        (`orchestrator.py:845-864`) noting "context categories are eager-loaded here; query-aware
        pruning via ContextPlanner is wired in W2 behind `context_planner_enabled` (RET-R1)" and add a
        test `test_context_planner_cue_precision_is_wired_for_w2` that simply asserts `_word_match`
        is exported and behaves (the precision fix is the W3 deliverable; the invocation is W2's).
      This keeps W3 non-overlapping with W2's `context_planner.py`? — **Conflict check:** W2 spec
      §3 lists `context_planner.py` under W2 ownership too. **Resolution:** W3 owns the CP01
      *precision* fix (cue matching) only; W2 owns the *runtime invocation*. Sequence: land T6
      (precision) before W2 touches invocation, or coordinate. Note this in the task's review.
- [ ] Run green; commit: `fix(context-planner): word-boundary cue matching, drop over-broad cues (ORCH-CP01); document hot-path pruning (ORCH-CP02)`.

**DoD:** false-positive cue matches gone; positive matches retained; CP02 pruning location documented
(invocation deferred to W2); green. Flag the `context_planner.py` co-ownership with W2 in review.

---

### T7 — ORCH-P01: scope validation criteria to data stages; text stages validated on non-empty summary  [G3b]
`depends:[]` (files disjoint from G3a; shares `query_planner.py`/`planner_prompt.py` with T8 — see
note).

**Problem (audit `adaptive_planner.py:329-347`, `stage_validator.py:113-136`):**
`expected_columns`/`min_rows` are dead no-ops on text-producing stages (`analyze_results`,
`search_codebase`, `analyze_git`, `synthesize` — which set `summary`, not `query_result`), yet the
planner prompt invites them. A text stage that returns an **empty** summary passes validation.

**Files:** `backend/app/agents/stage_validator.py` (`validate`); `backend/app/agents/prompts/planner_prompt.py`
(scope guidance); `backend/tests/unit/test_stage_validator_text_scope.py` (NEW).

**Interfaces:** `StageValidator.validate(...)` unchanged externally. Define the text-tool set at
module scope in `stage_validator.py`:
`_TEXT_STAGE_TOOLS = {"analyze_results", "search_codebase", "analyze_git", "synthesize"}`.

Steps:
- [ ] Failing test `test_text_stage_empty_summary_fails`: build a `search_codebase` `PlanStage` with
      `StageValidation(min_rows=5)` (planner-invited data criterion) and a `StageResult(status=
      "success", summary="", query_result=None)`; call
      `StageValidator().validate(stage, result, ctx)` and assert `outcome.passed is False` with an
      error mentioning "empty" (the summary is empty). Add `test_text_stage_nonempty_summary_passes`
      (summary = "Found the caching module.") → `passed is True` and the data criteria (`min_rows`)
      are **ignored** for a text stage (no spurious "expected at least 5 rows" warning/fail).
- [ ] Add `test_data_stage_still_uses_row_criteria`: a `query_database` stage with `min_rows=5` and a
      2-row result still warns/fails as today (regression guard — data-stage path unchanged).
- [ ] Run: confirm fail (today an empty-summary text stage passes; `min_rows` on a text stage with
      `query_result=None` is silently skipped so it neither warns nor validates content).
- [ ] Minimal impl in `StageValidator.validate` (after the `result.status == "error"` early-return):
      ```python
      if stage.tool in _TEXT_STAGE_TOOLS:
          summary = (result.summary or "").strip()
          if not summary:
              outcome.fail("Text stage produced an empty summary")
          # data criteria (expected_columns/min_rows/max_rows) do not apply to
          # text stages — skip them entirely.
          if v.cross_stage_checks:
              for check in v.cross_stage_checks:
                  self._evaluate_cross_check(check, result, stage_ctx, outcome)
          return outcome
      ```
      (Keep `validate_async` delegating as-is — business rules require `query_result`, so a text
      stage skips them naturally.)
- [ ] Update `planner_prompt.py` rule 6: add a sentence that `expected_columns`/`min_rows`/`max_rows`
      apply **only** to data-retrieval stages (`query_database`/`process_data`); text stages
      (`analyze_results`/`search_codebase`/`analyze_git`/`synthesize`) are validated on a non-empty
      result. **File note:** T8 also edits `planner_prompt.py` (P02 cohort_window) — sequence T7's
      prompt edit before T8, or have T8 (which is `depends:[T4]`, later) apply both. To avoid the
      overlap, **T7 edits only `stage_validator.py`**; move the `planner_prompt.py` rule-6 sentence
      into T8's prompt-consolidation edit. (Marked resolved: T7 = validator only; T8 = prompt.)
- [ ] Run green; commit: `fix(stage-validator): scope data criteria to data stages, require non-empty text-stage summary (ORCH-P01)`.

**DoD:** empty text-stage summary now fails; data criteria no longer dead on text stages; data-stage
path unchanged; green.

---

### T8 — ORCH-P02/P03 + RP01/RP02: unify cohort_window param convention; bounce ≤2-data-stage plans; carry degraded on replan; store failed_stage.tool  [G3b→after G3a]
`depends:[T4]` (RP01/RP02 edit `orchestrator.py`; sequence after G3a).

**Problems (audit):**
- **ORCH-P02** (planner vs orchestrator prompt): `cohort_window` documented with **different param
  envelopes** — orchestrator prompt says pass params via `'params_json'` (`orchestrator_prompt.py:59-62`),
  planner prompt says top-level keys `release_dates`/`event_date_column`/… (`planner_prompt.py:38-42`).
  Unify one convention; accept both during transition.
- **ORCH-P03** (`planner_prompt.py:11`): no lower guard — the pipeline can emit a trivial 1-2 stage
  plan that loses flat-loop features (viz, follow-ups, result-gate). Bounce ≤2-**data**-stage plans
  back to the unified loop.
- **ORCH-RP01** (`adaptive_planner.py`, `orchestrator.py:2288`): `degraded` stages are neither
  carried nor re-run on replan (`_run_pipeline_replans` seeds only `status == "success"`) → redoes
  work / loses usable results.
- **ORCH-RP02** (`orchestrator.py:2547`): pipeline learnings store `stage_id` where the **tool name**
  is expected (`_extract_pipeline_learnings` passes `failed_stage_tool=rh.get("failed_stage", "")` —
  that value is a `stage_id`, not a tool). Store the real tool.

**Files:** `backend/app/agents/prompts/orchestrator_prompt.py` + `prompts/planner_prompt.py` (P02
convention + P01 rule-6 sentence from T7); `backend/app/agents/adaptive_planner.py` (P03 bounce
signal + RP01 carry); `backend/app/agents/orchestrator.py` (P03 bounce enforcement in
`_run_complex_pipeline`; RP01 seed `degraded` in `_run_pipeline_replans`; RP02 tool in
`_run_pipeline_replans`/`_extract_pipeline_learnings`); `backend/tests/unit/test_orchestrator_replan.py`
(NEW) + `tests/unit/test_planner_prompt_convention.py` (NEW).

**Interfaces:**
- P02: pick **top-level keys** as canonical (matches `data_processor.cohort_window` param parsing and
  the planner path that actually runs cohort in the pipeline). Add a transition note to BOTH prompts:
  "`cohort_window` params: use top-level keys `release_dates`, `event_date_column`, `value_column`
  (revenue) or `id_column` (retention), `windows`, `metric`. (A `params_json` wrapper object is also
  accepted for back-compat.)" Ensure `ToolDispatcher.build_process_data_params` /
  `_parse_process_data_params` (`stage_executor.py:903`) accept a `params_json` wrapper by unwrapping
  it if present (belt-and-braces so both conventions run). Verify current unwrap behavior first.
- P03: in `_run_complex_pipeline` after `plan` is produced (`orchestrator.py:1906`), compute
  `data_stage_count = sum(1 for s in plan.stages if s.tool in {"query_database","search_codebase",
  "query_mcp_source","analyze_git"})`; if `data_stage_count <= 2` and the plan has no checkpoint and
  no `process_data` fan-out (i.e. it's a trivial plan), **bounce to the unified loop** via the same
  fallback path already used when `plan is None` (`orchestrator.py:1917-1934`, the `self.run(...)`
  with `"_skip_complexity": True`). Extract that fallback into a small helper
  `_fallback_to_unified(context, wf_id)` to reuse (single-file W3 edit).
- RP01: in `_run_pipeline_replans` seed carry-over with `status in ("success", "degraded")`
  (`orchestrator.py:2242-2244` `seedable_ids` and `2288-2290` seeding loop). A degraded stage has a
  usable `query_result`/`summary`; carrying it avoids re-running.
- RP02: in `_run_pipeline_replans` capture `failed.tool` alongside `failed.stage_id` in
  `replan_history` entries (`{"attempt":…, "failed_stage": failed.stage_id, "failed_stage_tool":
  failed.tool, "error": …}`); in `_extract_pipeline_learnings` pass
  `failed_stage_tool=rh.get("failed_stage_tool", "")` (not the stage_id).

Steps:
- [ ] Failing test `tests/unit/test_planner_prompt_convention.py::test_cohort_window_convention_consistent`:
      assert both `orchestrator_prompt.build_orchestrator_system_prompt(has_connection=True,
      has_repo=True, db_type="postgres")` and `planner_prompt.PLANNER_SYSTEM_PROMPT` contain the
      canonical phrase `"top-level keys"` for cohort_window and both mention `release_dates` +
      `event_date_column`. (Today they disagree on `params_json` vs top-level.)
- [ ] Failing test `tests/unit/test_orchestrator_replan.py::test_trivial_plan_bounces_to_unified`:
      patch `route_request` → `complexity="complex"` + `connection_config` set;
      `AdaptivePlanner.plan` → a 1-stage `query_database` plan; assert `_run_complex_pipeline` calls
      `self.run(...)` again with `extra["_skip_complexity"] is True` (spy on `orch.run`), i.e. the
      trivial plan is bounced.
- [ ] Failing test `test_degraded_stage_carried_on_replan`: build a `_StageExecutorResult(status=
      "stage_failed", replan_eligible=True)` whose `stage_ctx.results` has one `degraded` stage with a
      `query_result`; run `_run_pipeline_replans` with a stubbed `adaptive.replan` returning a plan
      that `depends_on` the degraded stage id; assert the new `StageContext` was seeded with that
      degraded result (spy on `new_stage_ctx.set_result` / assert `executor.execute` received a
      stage_ctx containing it) and that the dangling-dep guard did NOT reject it (degraded is now
      seedable).
- [ ] Failing test `test_replan_learning_gets_tool_not_stage_id`: build `replan_history=[{"attempt":1,
      "failed_stage":"fetch_rev","failed_stage_tool":"query_database","error":"x"}]` and a stub
      `PipelineLearningExtractor.extract_from_replan` (mock); call `_extract_pipeline_learnings` and
      assert `extract_from_replan` was called with `failed_stage_tool="query_database"` (NOT
      `"fetch_rev"`).
- [ ] Run: confirm all four fail.
- [ ] Minimal impls per Interfaces. For P02, first `grep` `build_process_data_params` /
      `_parse_process_data_params` to confirm whether a `params_json` wrapper is already unwrapped; if
      not, add `if "params_json" in params and isinstance(params["params_json"], dict): params =
      {**params["params_json"], **{k:v for k,v in params.items() if k!='params_json'}}` before the
      `operation` handling in `stage_executor._parse_process_data_params`.
- [ ] Include the T7 rule-6 sentence edit in `planner_prompt.py` here (single owner of the prompt in
      G3b).
- [ ] Run green; commit: `fix(orchestrator): unify cohort_window params, bounce trivial plans, carry degraded on replan, store failed tool in learnings (ORCH-P02/P03/RP01/RP02)`.

**DoD:** four regressions covered; both prompts agree on cohort params; trivial plans no longer strip
flat-loop features; degraded results reused on replan; learnings carry the tool name; green.

---

### T9 — ORCH-R01 (+ ORCH-P04): allow the multi-stage pipeline for complex non-DB questions; fix _quick_data_plan fallback tool  [G3c]
`depends:[T4]`.

**Problem (audit `orchestrator.py:589`, ORCH-R01):** the pipeline is gated on
`route_result.use_complex_pipeline **and has_connection**`; complex **knowledge/Git/MCP** questions
silently drop to the flat loop. Gate on **any** data source. **ORCH-P04** (referenced in scope): the
`_quick_data_plan` fallback (`adaptive_planner.py:196-211`) hardcodes a single `query_database`
stage — wrong for a knowledge/Git-only project (there is no connection to query). Make the fallback
tool source-aware.

**Files:** `backend/app/agents/orchestrator.py` (`run()` branch at 588-613 — the
`if route_result.use_complex_pipeline and has_connection:` guard; `_run_complex_pipeline` /
`_load_table_map` tolerate no-connection); `backend/app/agents/adaptive_planner.py` (`_quick_data_plan`
+ `plan(...)` signature to accept a preferred fallback tool); `backend/tests/unit/test_orchestrator_nondb_pipeline.py`
(NEW).

**Interfaces:**
- Broaden the guard to:
  ```python
  has_any_data_source = has_connection or has_kb or has_mcp or has_repo
  if route_result.use_complex_pipeline and has_any_data_source:
      table_map = await self._load_table_map(context, wf_id) if has_connection else ""
      ...
      return await self._run_complex_pipeline(context, wf_id, table_map, db_type,
          staleness_warning=staleness_complex, has_repo=has_repo)
  ```
  `_run_complex_pipeline`/`AdaptivePlanner.plan` already accept an empty `table_map`; the planner LLM
  chooses `search_codebase`/`analyze_git`/`query_mcp_source` stages. `_load_table_map` is only called
  when `has_connection` (avoid a no-op DB round trip).
- `_quick_data_plan` (P04): add a param `fallback_tool: str = "query_database"` and thread a
  source-derived default from `plan(...)`. `AdaptivePlanner.plan` gains
  `fallback_tool: str = "query_database"`; the orchestrator passes
  `fallback_tool = "query_database" if has_connection else ("search_codebase" if has_kb else
  ("analyze_git" if has_repo else "query_mcp_source"))`. The quick plan's single stage uses that
  tool. Keep the default `query_database` for callers that don't pass it (back-compat).

Steps:
- [ ] Failing test `test_complex_knowledge_question_uses_pipeline`: `has_connection=False`,
      `has_kb=True`; patch `route_request` → `RouteResult(route="knowledge", complexity="complex",
      approach="", estimated_queries=3, needs_multiple_data_sources=False)`. Spy on
      `orch._run_complex_pipeline` (AsyncMock). Call `await orch.run(context)` and assert
      `_run_complex_pipeline` **was awaited** (today it is NOT — the `and has_connection` guard is
      False so it falls to `_run_unified_agent`). Add `test_complex_db_question_still_uses_pipeline`
      regression (has_connection=True path unchanged).
- [ ] Failing test `test_quick_data_plan_uses_source_tool`: `AdaptivePlanner._quick_data_plan("q",
      fallback_tool="search_codebase").stages[0].tool == "search_codebase"`; default call →
      `"query_database"`.
- [ ] Run: confirm fail.
- [ ] Minimal impl per Interfaces. Ensure `_run_complex_pipeline` does not assume a connection when
      building `conn_id` for learnings (`orchestrator.py:2006` already guards `if conn_id:`).
- [ ] Run green; commit: `feat(orchestrator): route complex non-DB questions through the pipeline; source-aware quick-plan fallback (ORCH-R01, ORCH-P04)`.

**DoD:** complex knowledge/Git/MCP questions reach the pipeline; quick-plan fallback picks a valid
tool for the available source; DB path unchanged; green. Prod signal to watch post-deploy:
`pipeline_complete` count should rise from 1.

---

### T10 — ORCH-A01: unify the SQL result-quality gate + reconciliation across flat loop AND stage_executor via C-B/C-C ResultValidation  [G3c]
`depends:[T9]` — **consumes W0 `ResultValidation.evaluate(...)`**.

**Problem (audit `stage_executor.py:576-624` vs `orchestrator.py:1444-1475`, ORCH-A01):** the
result-quality gate + reconciliation run **only** on the flat loop. `_run_sql_stage` in the pipeline
never applies them → the same question gets different correctness assurance by routing coin-flip.

**Files:** `backend/app/agents/stage_executor.py` (`_run_sql_stage` — add the shared gate);
`backend/app/agents/orchestrator.py` (flat-loop post-dispatch block at 1458-1475 — route through the
same `ResultValidation` so both call one gate; if W0 exposed
`_apply_result_validation`, wire it; else keep the inline gate but make it delegate to
`ResultValidation.evaluate`); `backend/app/agents/result_validation.py` is **W0-owned — DO NOT edit**,
only consume; `backend/tests/unit/test_result_validation_both_paths.py` (NEW).

**Interfaces (C-B/C-C, verbatim):**
```python
directive: ResultDirective = result_validation.evaluate(   # SYNC — do not await
    qr, question=<stage/turn question>, sql=<sql>, truncated=qr.truncated)
# directive.action in {"accept","warn","requery","block"}; directive.reason; directive.hints
```
- Construct `ResultValidation(DataGate(), AgentResultValidator())` once (the keyword-only `reconcile`
  keeps its default `sql_results_reconcile`). The positional collaborators are the real `DataGate` +
  `AgentResultValidator` — there is no `SqlResultGate`/`SqlResultReconciliation` to construct. Because
  `evaluate` is synchronous, `_run_sql_stage` calls it directly (no `await`).
- `StageExecutor.__init__` gains `result_validation: ResultValidation | None = None`; the orchestrator
  passes one when building the executor in `_run_complex_pipeline` (`orchestrator.py:1951-1960`). When
  `None`, `_run_sql_stage` skips the gate (back-compat for tests that don't wire it) — but production
  always wires it.
- In `_run_sql_stage`, after building `qr`, call `evaluate`; map `directive.action`:
  `"block"` → `StageResult(status="error", error=directive.reason, error_category="data_missing")`
  (so the existing replan machinery kicks in); `"requery"`/`"warn"` → keep the result but append
  `directive.reason`+`hints` to `summary` (so the synthesis stage sees the caveat); `"accept"` → no-op.

Steps:
- [ ] Failing test `test_stage_executor_applies_result_validation`: build a `ResultValidation` double
      whose `evaluate` is a `MagicMock(return_value=ResultDirective(action="block", reason="150%
      conversion impossible", hints=["state the %-base"]))` (SYNC — plain `MagicMock`, not
      `AsyncMock`). Wire it into `StageExecutor(..., result_validation=<double>)`. Stub `sql_agent.run`
      → a `SQLAgentResult(status="success", query=..., results=QueryResult(columns=["pct"],
      rows=[[150]], row_count=1))`. Call `await executor._run_sql_stage("q", stage, ctx)` and assert
      the returned `StageResult.status == "error"` and `"impossible" in error` (the pipeline path now
      blocks the same impossible number the flat loop would). Assert `evaluate` was **called** once
      (not awaited) with `qr` = the QueryResult.
- [ ] Failing test `test_both_paths_use_same_gate`: assert the flat-loop path also delegates — spy on
      `ResultValidation.evaluate` via a patched instance shared by both, drive one `query_database`
      turn through `_run_tool_loop` and one stage through `_run_sql_stage`, assert `evaluate` was
      **called** on both. (If W0 kept the flat-loop gate inline without delegation, this test instead asserts
      the inline gate and the stage gate produce the **same directive** for the same `qr` — pick the
      assertion matching W0's actual shape; document which in the commit.)
- [ ] Run: confirm fail (`_run_sql_stage` today never validates).
- [ ] Minimal impl per Interfaces. Do not double-run DataGate: the pipeline already calls
      `self._data_gate.check(...)` in `_process_one_stage` (`stage_executor.py:355`). **Reconcile:**
      `ResultValidation` composes DataGate hard-checks per spec; to avoid a double gate, have
      `_run_sql_stage` own the `ResultValidation` (per-result, zero-row + reconciliation +
      Decimal/truncation-aware DataGate) and keep `_process_one_stage`'s existing `DataGate.check` as
      the **stage-shape** gate (min_rows etc. via StageValidator). If W0's `ResultValidation`
      subsumes DataGate hard-checks, gate the `_process_one_stage` DataGate call behind "not already
      run by ResultValidation" — confirm W0's intent; default to keeping both (idempotent hard-checks)
      and add a note. Prefer: `_run_sql_stage` returns the (possibly summary-annotated) result; the
      later `DataGate.check` is a no-op on an already-clean result.
- [ ] Run green; commit: `feat(orchestrator): unify SQL result-quality gate across flat loop and pipeline via ResultValidation (ORCH-A01, DATA-06)`.

**DoD:** the pipeline SQL path applies the same gate + reconciliation as the flat loop; an impossible
number blocks on **both** paths; no double-DataGate regression; green. **Confirm W0 constructor shape
before coding** (see assumption).

---

### T11 — ORCH-A02: run AnswerQualityGate on the pipeline final answer too  [G3c]
`depends:[T10]` — **consumes W0 `AnswerQualityGate`**.

**Problem (audit `orchestrator.py:1592` vs `response_builder.py:78-104`, ORCH-A02):** `AnswerValidator`
runs on flat-loop answers but **not** on pipeline final answers — a `pipeline_complete` can ship a
vague non-answer with a green check.

**Files:** `backend/app/agents/orchestrator.py` (`_run_complex_pipeline` at ~2037, before
`ResponseBuilder.build_pipeline_response` — run the gate and pass the downgrade decision in);
`backend/app/agents/response_builder.py` (`build_pipeline_response` — accept an optional
`answer_directive: ResultDirective | None = None` and, when its `action` is `"requery"`/`"warn"`, set
`response_type = "step_limit_reached"` and keep the answer text — mirroring the flat-loop downgrade at
`orchestrator.py:1609-1610`); `backend/tests/unit/test_pipeline_answer_gate.py` (NEW).

**Interfaces (C-B/C-C `AnswerQualityGate`, verbatim — returns a `ResultDirective`):**
```python
directive: ResultDirective = await answer_quality_gate.evaluate(
    question=context.user_question,
    answer=exec_result.final_answer,
    sql_summaries=[<per-stage sql summaries>],
    preferred_provider=context.preferred_provider, model=context.model)
# directive.action in {"accept","warn","requery","block"}; a non-"accept" action is an inadequate answer
```
- Only run when `exec_result.status == "completed"` and `settings.answer_validator_enabled` (mirror
  the flat-loop cost discipline — but the pipeline final answer is the hardest/most-expensive request,
  so run it unconditionally on `completed` per audit "run it on pipeline final answers too"). Build
  `AnswerQualityGate(self._answer_validator)` — it takes the `AnswerValidator` instance directly (the
  validator itself already carries the router + usage sink; the gate does NOT take `llm`/`usage_sink`).
- `build_pipeline_response(exec_result, wf_id, staleness_warning, pipeline_run_id, *,
  answer_directive=None)` — new keyword-only param, default `None` (back-compat: existing callers and
  the resume path `orchestrator.py:2452` pass nothing → behaviour unchanged). When
  `answer_directive is not None and answer_directive.action != "accept" and status=="completed"`,
  override `response_type = "step_limit_reached"` (so the UI offers "Continue analysis"), keep the
  answer + viz, and set `error = None` (it is not an error, just incomplete).

Steps:
- [ ] Failing test `test_pipeline_vague_answer_downgraded`: build a completed `_StageExecutorResult`
      with `final_answer="I looked at some data."`. Patch `AnswerQualityGate` (import site in
      orchestrator) with an instance whose async `evaluate` → `ResultDirective(action="requery",
      reason="no conclusion")`. Drive `_run_complex_pipeline` (stub planner + executor to return the
      completed result). Assert the returned `AgentResponse.response_type == "step_limit_reached"`
      (NOT `"pipeline_complete"`). Add `test_pipeline_good_answer_kept` (directive `action="accept"` →
      `response_type == "pipeline_complete"`).
- [ ] Failing test on the builder directly `test_build_pipeline_response_honors_directive`: call
      `ResponseBuilder.build_pipeline_response(exec_result, "wf", None, "run",
      answer_directive=ResultDirective(action="requery", reason="x"))` and assert
      `resp.response_type == "step_limit_reached"` and `resp.answer == exec_result.final_answer`.
- [ ] Run: confirm fail (builder has no `answer_directive` param; pipeline never gates).
- [ ] Minimal impl per Interfaces. In `_run_complex_pipeline`, run the gate only for
      `exec_result.status == "completed"` (checkpoint/stage_failed do not need it — they are already
      honest partials), guard with `try/except` → on gate failure fall through with `answer_directive=
      None` (honest degradation: never break the answer because the gate failed). Map the returned
      `directive.action` to the downgrade decision (any non-`"accept"` → downgrade); do NOT read
      `AnswerValidationResult` fields directly (the gate already mapped the verdict). Emit a tracker
      `orchestrator:answer_validator` event mirroring the flat-loop one.
- [ ] Run green; commit: `feat(orchestrator): run AnswerQualityGate on pipeline final answers (ORCH-A02)`.

**DoD:** a vague pipeline answer is downgraded to `step_limit_reached`; a good one stays
`pipeline_complete`; the gate never breaks the answer; resume path back-compat intact; green.

---

### T12 — ORCH-P01 (pipeline glue) + reconciliation note on pipeline synthesis  [G3c]
`depends:[T11]`.

**Purpose:** close the P01 loop on the pipeline side and ensure the pipeline synthesis benefits from
the same reconciliation-note that the flat loop injects (`orchestrator.py:1473-1475`,
`response_builder.build_synthesis_messages:296-298`). The pipeline `_synthesize`
(`stage_executor.py:961-984`) dumps per-stage rows but never injects a reconciliation note across the
SQL stages, so a multi-query pipeline can still hallucinate "an earlier query under-counted".

**Files:** `backend/app/agents/stage_executor.py` (`_synthesize` — inject
`build_reconciliation_note(...)` built from the SQL stage results);
`backend/tests/unit/test_stage_executor_synthesis_reconcile.py` (NEW).

**Interfaces:** import `from app.agents.sql_result_reconciliation import build_reconciliation_note`;
build a list of `SQLAgentResult`-shaped objects OR (simpler) reuse the reconciliation over the
`stage_ctx` SQL results. Confirm `build_reconciliation_note` signature accepts what the pipeline has
(it takes `list[SQLAgentResult]`); if the pipeline stores `StageResult` (with `query`/`query_result`),
adapt by constructing lightweight `SQLAgentResult(query=sr.query, results=sr.query_result)` per SQL
stage before calling. Keep it best-effort (try/except → skip on mismatch).

Steps:
- [ ] Failing test `test_pipeline_synthesis_includes_reconciliation_note`: build a `stage_ctx` with
      two `query_database` stages whose `query_result` totals reconcile; stub the synthesis LLM to
      echo its user message; call `executor._synthesize(stage_ctx, ctx)` and assert the user message
      passed to the LLM contains a reconciliation note (e.g. `"RECONCIL"`/the note's marker). Assert
      no note when there is 0 or 1 SQL stage.
- [ ] Run: confirm fail (no note today).
- [ ] Minimal impl in `_synthesize`: after building `parts`, collect SQL stages, build adapter
      `SQLAgentResult`s, `note = build_reconciliation_note(adapters)`; if `note`, append to `parts`.
      Wrap in try/except (honest degradation).
- [ ] Run green; commit: `fix(stage-executor): inject SQL reconciliation note into pipeline synthesis (ORCH-P01/T5 parity)`.

**DoD:** the pipeline synthesis now carries the same anti-false-self-correction reconciliation note as
the flat loop; green.

---

### T13 — Low batch: ORCH-A05, V01, V02, PR03, PR04, R03, R04  [G3d]
`depends:[T4,T12]` (edits `orchestrator.py`/`router.py`/`stage_executor.py` — after the sequential
edits settle).

**Findings (audit §2 low/med grouped):**
- **ORCH-A05** (`orchestrator.py:1916-1934`): planner-fallback rebuilds `AgentContext` field-by-field
  (13 fields) → new fields silently dropped. Replace with `dataclasses.replace(context, extra={
  **context.extra, "_skip_complexity": True}, workflow_id=wf_id)` (import `replace` already present).
- **ORCH-V01/V02** (`stage_executor.py:434-538`): per-stage retries compound (execute ×2 →
  validation-retry ×2 → data-gate-retry ×2 ≈ 7×) before replan; deadline checked only between
  batches. **V02 fix:** share **one** retry budget per stage across the three retry loops
  (`_execute_with_retries`, `_retry_failed_validation`, `_retry_failed_data_gate`) — thread a
  remaining-attempts counter; and check the pipeline `deadline` **inside** the retry loops (pass the
  executor deadline down or re-read `time.monotonic()` and abort a retry loop once past deadline).
- **ORCH-R03** (`router.py:42-54,187`): `estimated_queries` is a single uncalibrated LLM int; OR-in a
  cheap heuristic. Add: `estimated_queries = max(est_queries, _heuristic_queries(question))` where
  `_heuristic_queries` counts data-intent conjunctions ("and", "then", "compare", "by", "vs",
  "over time", "each") capped at 5. Log estimated-vs-nothing (calibration hook).
- **ORCH-R04** (`orchestrator.py:536-543,1932`): planner-fallback hardcodes `route=explore,
  complexity=moderate` → one bad JSON permanently downgrades a complex turn. Preserve the **original**
  `complexity` across fallback re-entry: when building the `_skip_complexity` fallback context, carry
  `extra["complexity"]` (set by T4) so the re-entered `run()` continuation branch keeps it.
- **PR03** (`orchestrator_prompt.py` / `stage_executor._run_analysis_stage`): intermediate analysis
  stage lacks language-mirroring — add "write any user-facing text in the user's language" caveat to
  the analysis-stage system prompt (`stage_executor.py:720-725`). **PR04** already covered by T5
  regression; assert it stays.

**Files:** `backend/app/agents/orchestrator.py`, `router.py`, `stage_executor.py`,
`prompts/orchestrator_prompt.py`; `backend/tests/unit/test_orchestrator_low_batch.py` (NEW).

Steps (one failing test per finding, then batched impl):
- [ ] `test_planner_fallback_preserves_extra` (A05+R04): set `context.extra = {"complexity":"complex",
      "session_id":"s1","custom_key":"keep"}`; force planner failure (`AdaptivePlanner.plan` →
      `None`); spy on `orch.run`; assert the re-entered context's `extra` contains
      `complexity=="complex"`, `custom_key=="keep"`, AND `_skip_complexity is True` (nothing dropped).
- [ ] `test_stage_retry_budget_is_shared` (V02): configure a stage with `max_retries=2`; make the
      stage fail validation then data-gate; assert the **total** sub-agent invocation count is bounded
      by the shared budget (≤ `max_retries+1` executions, not `~7`). Spy on `_execute_stage`.
- [ ] `test_deadline_checked_inside_retry_loop` (V02): set a deadline already in the past; assert a
      retry loop aborts without another `_execute_stage` call.
- [ ] `test_router_heuristic_ors_in` (R03): `_parse_route_response('{"route":"query","complexity":
      "simple","approach":"","estimated_queries":1,"needs_multiple_data_sources":false}', ...)` for a
      question "revenue by country and by month then compare vs last year" → after heuristic OR-in,
      `estimated_queries >= 3`. (Thread the question into `_parse_route_response` or apply the
      heuristic in `route_request` after parse — apply in `route_request` to keep the parser pure.)
- [ ] `test_analysis_stage_language_caveat` (PR03): assert the analysis-stage system prompt contains a
      language-mirroring instruction.
- [ ] Run all → confirm fail; batched minimal impls per Findings; run green.
- [ ] Commit: `fix(orchestrator): low-batch A05/V01/V02/PR03/PR04/R03/R04`.

**DoD:** each low finding has a regression test; retry surface bounded; deadline honored inside
retries; router estimate calibrated; fallback preserves state; analysis stage mirrors language; green.

---

### T14 — Integration + gates + docs  [G3e]
`depends:[T1..T13]`.

Steps:
- [ ] `cd backend && .venv/bin/ruff format --check app/ tests/ && .venv/bin/ruff check app/ tests/ &&
      .venv/bin/mypy app/ --ignore-missing-imports`.
- [ ] `cd backend && .venv/bin/pytest tests/unit tests/integration -q` (full suite) — must be green;
      then the coverage gate: `.venv/bin/coverage report --fail-under=72` (per CLAUDE.md — the single
      authoritative gate). Do not let W3 drop coverage below 72%.
- [ ] Retrieval-eval gate (per spec §6 per-wave DoD):
      `.venv/bin/pytest tests/unit/test_retrieval_eval.py tests/unit/test_reranker.py -q` — must stay
      green (W3 must not regress retrieval; it doesn't touch retrieval code, this is a safety net).
- [ ] Docs (same-change DoD): update `CLAUDE.md` — the "LLM routing & observability" bullet
      (complexity now recorded, not `"unknown"`), the request-lifecycle note (pipeline now taken for
      complex non-DB questions; shared result gate + answer gate across both paths), and the feature-
      flag line if `max_orchestrator_iterations` default changed. Update `CHANGELOG.md [Unreleased]`
      with the W3 line items (ORCH-T01/T02/T03, A01/A02/A03, R01/P04, PR01, CP01, P01, P02/P03,
      RP01/RP02, low batch). Update `API.md` only if a response_type/behaviour contract visible to
      clients changed (pipeline answers can now come back as `step_limit_reached` — note it).
- [ ] Commit: `docs(w3): changelog + CLAUDE.md/API.md for orchestrator remediation`.

**DoD:** `make check` equivalent green (ruff format+check, mypy, unit+integration, coverage ≥72%);
retrieval-eval green; docs updated in-change.

---

## Post-deploy verification (operator-run; per spec §8 — re-pull prod before/after)
- Re-pull `request_traces` (n≥195) and compare vs the 2026-07-01 baseline:
  - Failure rate should fall from **24%**; `step_limit_reached` count should fall (T1/T2/T3).
  - `complexity` label should no longer be `"unknown"` in `/api/metrics` (T4/A03).
  - `pipeline_complete` count should rise above 1 for complex non-DB questions (T9/R01).
  - avg tokens/request should fall from **164,230** (T5 de-dup; T2 no premature synthesis on huge
    prompts is neutral-to-positive).
- Not blocking for ship; the autonomous path (T1-T14) is complete without it.

## Human steps (end)
- None required to ship. Post-deploy prod re-pull above is operator-run and optional.
