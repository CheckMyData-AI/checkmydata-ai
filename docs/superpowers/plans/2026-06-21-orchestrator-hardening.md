# Orchestrator Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 4 orchestrator correctness bugs (B1–B4) and land 6 improvements (I2/I3, I4, I5, I6, I7) in one hardening sweep on the `fix/orchestrator-hardening` branch.

**Architecture:** Sequential-dominant. `orchestrator.py` is a shared hotspot so all its edits run in order; `anthropic_adapter.py`, `router.py`, `data_gate.py` are independent. A new shared module `app/llm/_system_messages.py` is created first (CONTRACT-0) and consumed by both LLM adapters.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, pytest (`asyncio_mode=auto`), ruff 0.15.15, mypy.

## Global Constraints

- Line length 100; ruff rules `E F I N W UP`; ruff/mypy pinned — do not widen.
- `asyncio_mode = "auto"` — no `@pytest.mark.asyncio` needed.
- Combined unit+integration coverage must stay ≥ 72%.
- No new feature flags except `router_last_turn_char_limit` (behavior-preserving).
- New env vars → `app/config.py` (with docstring) + `backend/.env.example`.
- Conventional commits per task (`fix(...)`, `refactor(...)`, `docs(...)`).
- Run tests from `backend/` via `.venv/bin/pytest`.

---

### Task 1: Extract shared `merge_nonleading_system` (CONTRACT-0)

**Files:**
- Create: `backend/app/llm/_system_messages.py`
- Modify: `backend/app/llm/openrouter_adapter.py` (replace local `_merge_nonleading_system` with import + alias)
- Test: `backend/tests/unit/test_llm_adapters.py` (existing merge tests keep passing)

**Interfaces:**
- Produces: `merge_nonleading_system(messages: list[Message]) -> list[Message]` in `app.llm._system_messages`.

- [ ] **Step 1:** Create `_system_messages.py` with `merge_nonleading_system` (verbatim body of the current `openrouter_adapter._merge_nonleading_system`).
- [ ] **Step 2:** In `openrouter_adapter.py`, delete the local def, add `from app.llm._system_messages import merge_nonleading_system`, keep `_merge_nonleading_system = merge_nonleading_system` alias for any existing test imports; update the call site to `merge_nonleading_system(messages)`.
- [ ] **Step 3:** Run `.venv/bin/pytest tests/unit/test_llm_adapters.py -v` → PASS (behavior unchanged).
- [ ] **Step 4:** Commit `refactor(llm): extract merge_nonleading_system into shared module`.

### Task 2: B3 — Anthropic adapter folds non-leading system

**Files:**
- Modify: `backend/app/llm/anthropic_adapter.py:106-127` (`_format_messages`)
- Test: `backend/tests/unit/test_llm_adapters.py`

**Interfaces:**
- Consumes: `merge_nonleading_system` (Task 1).

- [ ] **Step 1 (failing test):**
```python
def test_anthropic_format_folds_midloop_system():
    from app.llm.anthropic_adapter import AnthropicAdapter
    from app.llm.base import Message
    a = AnthropicAdapter.__new__(AnthropicAdapter)  # no network
    msgs = [
        Message(role="system", content="LEAD"),
        Message(role="user", content="hi"),
        Message(role="assistant", content="ok"),
        Message(role="system", content="BUDGET step 2/10"),
    ]
    system, formatted = a._format_messages(msgs)
    assert system == "LEAD"                      # only leading system hoisted
    assert "BUDGET step 2/10" in formatted[-1]["content"]  # folded into trailing user
    assert formatted[-1]["role"] == "user"
```
- [ ] **Step 2:** Run it → FAIL (current code hoists "BUDGET..." into `system`).
- [ ] **Step 3:** In `_format_messages`, first line: `messages = merge_nonleading_system(messages)`; add the import at top.
- [ ] **Step 4:** Run the test + full `test_llm_adapters.py` → PASS.
- [ ] **Step 5:** Commit `fix(llm): fold non-leading system into user turn on Anthropic (B3)`.

### Task 3: B1 — complex pipeline uses public planner

**Files:**
- Modify: `backend/app/agents/orchestrator.py` `_run_complex_pipeline` (the `adaptive._llm_plan(...)` call)
- Test: `backend/tests/unit/test_orchestrator.py`

- [ ] **Step 1 (failing test):** assert that after `_run_complex_pipeline` planning, `query_database` stages carry `validation.min_rows is not None` (auto-injected). Use a monkeypatched `AdaptivePlanner.plan`/`_llm_plan` returning a plan whose stage omits validation, and assert the executed plan got criteria injected. (If existing orchestrator tests already stub the planner, adapt to assert `plan()` is the method invoked.)
- [ ] **Step 2:** Run → FAIL (currently `_llm_plan` used, no injection).
- [ ] **Step 3:** Change `plan = await adaptive._llm_plan(` → `plan = await adaptive.plan(` (same kwargs). Keep the `if not plan:` flat-loop fallback.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `fix(orchestrator): complex pipeline uses public planner with validation injection (B1)`.

### Task 4: B4 — remove dead cross-turn cache reuse

**Files:**
- Modify: `backend/app/agents/orchestrator.py:410-417` (top of `run()`)
- Test: `backend/tests/unit/test_orchestrator.py`

- [ ] **Step 1 (failing/guard test):** assert `run()` does not resurrect `_wf_sql_results` from `_wf_enriched` for a fresh `wf_id` (i.e. a stale enriched entry under a *different* wf id is not surfaced). Assert `_cleanup_stale_results` still prunes old entries.
- [ ] **Step 2:** Run → may already pass; if so, keep as a regression guard and proceed.
- [ ] **Step 3:** Remove the `enriched = self._wf_enriched.get(wf_id) ...` reuse block (lines ~410-415); keep `self._cleanup_stale_results(stale_seconds)`; fix the comment.
- [ ] **Step 4:** Run orchestrator tests → PASS.
- [ ] **Step 5:** Commit `refactor(orchestrator): drop dead cross-turn SQL cache reuse (B4)`.

### Task 5: B2 — single-call dispatch safety net + `_tool_exc_to_directive`

**Files:**
- Modify: `backend/app/agents/orchestrator.py` (`_run_tool_loop` parallel branch ~1170-1236; add staticmethod)
- Test: `backend/tests/unit/test_orchestrator.py`

**Interfaces:**
- Produces: `OrchestratorAgent._tool_exc_to_directive(exc, tool_name) -> tuple[str, str]` (err_text, directive).

- [ ] **Step 1 (failing test):** monkeypatch `ToolDispatcher.dispatch` to raise `RuntimeError("boom")` for a single-tool-call turn; assert `run()` returns a normal `AgentResponse` (not `response_type="error"`) and the transcript contains a "failed" directive — i.e. the turn survives.
- [ ] **Step 2:** Run → FAIL (unhandled raise becomes generic error response).
- [ ] **Step 3:** Add `_tool_exc_to_directive` (extract the retryable/fatal directive logic from the parallel branch). Refactor the parallel branch to call it. Wrap the single-call `else` branch's `dispatch` in `try/except`: re-raise `_ClarificationRequestError`; on `Exception`, build `(err, directive)`, emit `tool_call:error`, store `(f"Tool '{tc.name}' failed: {err}.{directive}", None)`.
- [ ] **Step 4:** Run the new test + full orchestrator suite → PASS.
- [ ] **Step 5:** Commit `fix(orchestrator): graceful error handling on single-call tool dispatch (B2)`.

### Task 6: I4/B3-orch — budget marker de-duplication

**Files:**
- Modify: `backend/app/agents/orchestrator.py` (`_run_tool_loop` budget_status append ~994)
- Test: `backend/tests/unit/test_orchestrator.py`

- [ ] **Step 1 (failing test):** drive `_run_tool_loop` for ≥3 iterations (stub LLM to return a tool call then stop) and assert the final `messages` list contains at most ONE message whose content starts with `"[Budget:"`.
- [ ] **Step 2:** Run → FAIL (one per iteration accumulates).
- [ ] **Step 3:** Before appending the new budget marker, remove any existing message whose `content` starts with `"[Budget:"` (search by prefix, not index). The EMERGENCY marker is already single-shot (`if not synthesis_phase`).
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `fix(orchestrator): de-duplicate per-iteration budget marker (I4/B3)`.

### Task 7: I2/I3 — consolidate empty-result retry into the result-gate

**Files:**
- Modify: `backend/app/agents/tool_dispatcher.py:411-436` (`_handle_query_database`)
- Test: `backend/tests/unit/test_tool_dispatcher_git.py` or a new `test_tool_dispatcher.py`

- [ ] **Step 1 (failing test):** a SQL sub-result that is a *clean* zero-row result (no error, `vr.passed=True`) must NOT trigger a dispatcher re-query — `self._sql.run` is called exactly once. (Currently `empty_suspicious` forces a second call.)
- [ ] **Step 2:** Run → FAIL (called twice).
- [ ] **Step 3:** Remove the `empty_suspicious` retry trigger from `_handle_query_database` (`needs_retry = not vr.passed`). The result-gate (`_result_gate_directive`) remains the single owner of the zero-row re-query decision.
- [ ] **Step 4:** Run + existing dispatcher/orchestrator empty-result tests → PASS (adjust any test that asserted the double retry).
- [ ] **Step 5:** Commit `fix(orchestrator): single-owner empty-result retry via result gate (I2/I3)`.

### Task 8: I6 — budget-conscious answer gate on normal completion

**Files:**
- Modify: `backend/app/agents/orchestrator.py` (normal completion block ~1078-1092 / response_type ~1390)
- Test: `backend/tests/unit/test_orchestrator.py`

- [ ] **Step 1 (failing test A):** a normal completion with a *suspicious* result (zero rows OR `validate_sql_result` warning) whose answer is judged inadequate is downgraded away from `sql_result`. Stub `AnswerValidator.validate` → `addresses_question=False`.
- [ ] **Step 1b (failing test B / cost guard):** a normal completion with a clean, non-suspicious result makes NO `AnswerValidator` call (spy asserts 0 calls).
- [ ] **Step 2:** Run → A fails (gate not run on normal path).
- [ ] **Step 3:** In the normal completion path, compute `suspicious = bool(vr.warnings) or row_count==0 or wf in _wf_suspicious`; only when `suspicious`, run `_validate_partial_answer`; if it returns False, set `response_type="step_limit_reached"` (continuable). Otherwise leave `determine_response_type` untouched and make no LLM call.
- [ ] **Step 4:** Run A + B → PASS.
- [ ] **Step 5:** Commit `feat(orchestrator): budget-conscious answer gate on normal completion (I6)`.

### Task 9: I5 — router sees more of the latest user turn

**Files:**
- Modify: `backend/app/agents/router.py:233-239`; `backend/app/config.py`; `backend/.env.example`
- Test: `backend/tests/unit/test_router.py`

**Interfaces:**
- Produces: `settings.router_last_turn_char_limit: int = 800`.

- [ ] **Step 1 (failing test):** call `route_request` with a long final user question (> 500 chars) and a stubbed LLM that captures the messages; assert the final user message length reflects `router_last_turn_char_limit` (800), while older history stays capped at 200.
- [ ] **Step 2:** Run → FAIL (final question truncated to 500).
- [ ] **Step 3:** Add `router_last_turn_char_limit: int = 800` to `config.py` (Settings field + the construction at ~line 612 + docstring) and `.env.example`. In `route_request`, send the final user message sliced to `settings.router_last_turn_char_limit` (replace the `question[:500]`); keep older tail at 200.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(router): widen latest-turn context window for routing (I5)`.

### Task 10: I7 — DataGate catches epoch-int dates

**Files:**
- Modify: `backend/app/agents/data_gate.py` `_check_value_ranges` (~284, date branch)
- Test: `backend/tests/unit/test_data_gate.py`

- [ ] **Step 1 (failing test):** a `date`-kind column whose value is an int epoch far outside range (e.g. `99999999999999` ms or a tiny int) is flagged (fail when `data_gate_hard_checks_enabled`, else warn). A valid epoch (now, in seconds) is NOT flagged.
- [ ] **Step 2:** Run → FAIL (ints skip the date check).
- [ ] **Step 3:** Add an `isinstance(val, (int, float))` branch for `kind=="date"`: interpret as epoch seconds and epoch ms; if neither year is within `[year_min, year_max]`, `fail()`/`warn()` per `data_gate_hard_checks_enabled`.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `fix(data_gate): flag epoch-int dates outside plausible range (I7)`.

### Task 11: Full verification

- [ ] **Step 1:** `cd backend && .venv/bin/ruff format --check app/ tests/ && .venv/bin/ruff check app/ tests/`
- [ ] **Step 2:** `.venv/bin/mypy app/ --ignore-missing-imports`
- [ ] **Step 3:** `make test-all` (unit+integration) and confirm combined coverage ≥ 72%.
- [ ] **Step 4:** If green, the branch is ready for PR.

## Self-Review

- **Spec coverage:** B1→T3, B2→T5, B3→T2(adapter)+T6(orch/I4), B4→T4, I2/I3→T7, I4→T6, I5→T9, I6→T8, I7→T10, I1→documented-only (no task, by design). CONTRACT-0→T1. All covered.
- **Placeholder scan:** no TBD/TODO; each task names exact files and a concrete test assertion.
- **Type consistency:** `merge_nonleading_system` and `_tool_exc_to_directive` signatures match between definition (T1/T5) and consumption (T2/T5). `router_last_turn_char_limit` named consistently (T9).
