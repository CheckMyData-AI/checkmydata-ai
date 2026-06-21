# Orchestrator Hardening Sweep — Design Spec

**Date:** 2026-06-21
**Status:** Approved (design); pending implementation plan
**Scope:** B1–B4 + I2/I3, I4, I5, I6, I7 (I1 documented-only — see §I1)
**Author:** analysis of `backend/app/agents/orchestrator.py` and the orchestration stack

---

## 1. Background

A full read-through of the orchestration stack (`OrchestratorAgent`, `router`,
`tool_dispatcher`, `sql_agent`, `stage_executor`, `data_gate`, `validation`,
`answer_validator`, `response_builder`, LLM adapters) surfaced 4 correctness
bugs and 7 improvement opportunities. This spec locks the contracts for fixing
all of them in one hardening sweep.

Findings reference IDs (B = bug, I = improvement) are preserved from the
analysis for traceability.

## 2. Goals / Non-goals

**Goals**
- Fix correctness bugs B1, B2, B3, B4.
- Land improvements I2/I3 (retry-budget consolidation), I4 (folded into B3),
  I5 (router history), I6 (answer gate on normal path — budget-conscious),
  I7 (DataGate epoch-int dates).
- No drop in backend coverage below the 72% CI gate.
- No new runtime regressions on the OpenAI default path.

**Non-goals**
- No completion of the Phase-4 `ContextPlanner` wiring (see §I1).
- No refactor of the SQL agent's internal `ValidationLoop`/`QueryRepairer`.
- No new feature flags (per user decision: behavioral changes I2/I3/I6 apply
  directly). Exception: I5 may add one cosmetic config knob with a
  behavior-preserving default (see §I5).

## 3. Decisions locked during brainstorming

| Item | Decision |
|---|---|
| B3 fix location | **Both** levels: shared adapter helper **and** orchestrator fold. |
| I2/I3/I6 gating | **Apply directly**, no new feature flags. |
| I1 (`estimated_queries`) | **I1-a: documented-only, no code change** (it is the input to the unfinished Phase-4 ContextPlanner, not dead noise). |
| I6 cost | **Budget-conscious**: gate only *suspicious* results on the normal path; do NOT add an LLM call to every successful answer. |

## 4. File ownership & parallelization

`orchestrator.py` is a shared hotspot (touched by B1, B2, B4, I2/I3, I6, and the
orchestrator half of B3). To avoid write-conflicts across parallel agents, the
plan is **sequential-dominant** with a thin parallel wing.

| Group | Sole-owned file(s) | Findings | Parallel-safe |
|---|---|---|---|
| **CONTRACT-0** | `app/llm/_system_messages.py` (NEW) | shared helper for B3 | sequential, runs first |
| **SEQ-CORE** | `orchestrator.py`, `tool_dispatcher.py`, `validation.py` | B1, B4, B2, I2/I3, I6, B3-orch | ❌ single owner, ordered |
| **P-ADAPTER** | `app/llm/anthropic_adapter.py`, `app/llm/openrouter_adapter.py` | B3-adapter | ✅ (after CONTRACT-0) |
| **P-ROUTER** | `app/agents/router.py` | I5 | ✅ |
| **P-GATE** | `app/agents/data_gate.py` | I7 | ✅ |

Dependency order: **CONTRACT-0 → {P-ADAPTER ∥ SEQ-CORE(B3-orch)}**; P-ROUTER and
P-GATE are independent and may start immediately.

## 5. Shared contracts (locked)

### 5.1 NEW module `app/llm/_system_messages.py`

Extract the existing `_merge_nonleading_system` from `openrouter_adapter.py` into
a shared module so both the OpenRouter and Anthropic adapters use one
implementation.

```python
# app/llm/_system_messages.py
from app.llm.base import Message

def merge_nonleading_system(messages: list[Message]) -> list[Message]:
    """Fold non-leading ``system`` messages into the adjacent user turn.

    Keeps the leading run of ``system`` messages as-is; any later ``system``
    content is merged into the next ``user`` message, or appended as a trailing
    ``user`` message when no subsequent user turn exists. Provider-agnostic;
    used by adapters whose backends reject a mid-conversation ``system`` role
    (Anthropic, Bedrock-via-OpenRouter).
    """
```

- Behavior MUST be byte-for-byte identical to the current
  `openrouter_adapter._merge_nonleading_system` (verified by moving its existing
  tests to target the new module).
- `openrouter_adapter.py` imports and delegates to it (keeps a thin private
  alias `_merge_nonleading_system = merge_nonleading_system` if existing tests
  import the old name).

### 5.2 NEW orchestrator helper `_tool_exc_to_directive`

```python
# OrchestratorAgent (orchestrator.py), staticmethod
@staticmethod
def _tool_exc_to_directive(exc: BaseException, tool_name: str) -> tuple[str, str]:
    """Map a tool-dispatch exception to (user_error_text, llm_directive).

    Returns the human-readable error string and the corrective directive that
    is appended to the tool message so the LLM retries (transient) or adjusts /
    proceeds (fatal). Mirrors the logic currently inlined in the parallel-tool
    branch of ``_run_tool_loop`` so the single-call branch can reuse it.
    """
```

- Extracted verbatim from the existing parallel-branch logic
  (`orchestrator.py` ~lines 1170-1224). The parallel branch is refactored to
  call this helper too (no behavior change there).
- `_ClarificationRequestError` is NOT handled here — it is re-raised by the
  caller in both branches.

### 5.3 No signature changes to public APIs

`AdaptivePlanner.plan()`, `AgentResultValidator.validate_sql_result()`,
`route_request()`, `DataGate.check()` keep their signatures. Only call-sites and
internal bodies change (except I5's optional config knob, §I5).

## 6. Per-finding design

### B1 — complex pipeline must use the public planner
- **File:** `orchestrator.py` `_run_complex_pipeline` (~line 1672).
- **Change:** `plan = await adaptive._llm_plan(...)` → `plan = await adaptive.plan(...)`.
- `plan()` already accepts every kwarg currently passed to `_llm_plan`
  (`table_map`, `db_type`, `preferred_provider`, `model`, `project_overview`,
  `current_datetime`, `recent_learnings`, `staleness_warning`).
- Effect: initial plans now get `_ensure_validation_criteria` (auto-injected
  `min_rows`) and the `_quick_data_plan` fallback, matching the replan path.
- The existing `if not plan:` flat-loop fallback stays as a defensive net
  (`plan()` rarely returns the quick plan, never `None`; keep the guard).
- **Trace note:** the planning step span currently wraps `_llm_plan`; it now
  wraps `plan()`. Keep the `span_type="llm_call"` step wrapper.

### B2 — single-call dispatch needs the parallel branch's safety net
- **File:** `orchestrator.py` `_run_tool_loop` single-call `else` branch
  (~lines 1227-1236).
- **Change:** wrap `await self._dispatcher.dispatch(...)` in `try/except`:
  - On `_ClarificationRequestError`: re-raise (unchanged).
  - On `Exception`: build `(err_text, directive)` via `_tool_exc_to_directive`,
    emit `tool_call:error`, store `(f"Tool '{name}' failed: {err}.{directive}", None)`
    into `executed_pairs`.
- Rationale: the single-call branch is the *most common* path (the parallel
  branch only triggers for >1 non-`process_data` call); several handlers
  (`_handle_search_codebase`, `_handle_analyze_git`, `_handle_get_release_timeline`,
  `_handle_write_code_note`) can raise non-`AgentError` exceptions that currently
  crash the whole turn and discard gathered data.

### B3 + I4 — mid-loop system messages
- **Adapter (P-ADAPTER):** `anthropic_adapter._format_messages` calls
  `merge_nonleading_system(messages)` **before** the system-hoist loop, so
  mid-conversation `system` markers are folded into a user turn (preserving
  recency) instead of being concatenated into the top-level `system` param.
  Leading `system` messages still become the `system` param.
- **Orchestrator (SEQ-CORE, I4):** in `_run_tool_loop`, the EMERGENCY and
  `budget_status` markers **remain** `role="system"` messages — the adapter-level
  fold (B3-adapter) now gives them correct recency on Anthropic/Bedrock, and
  OpenAI accepts mid-conversation system natively. The orchestrator's only I4
  job is **de-duplication**:
  - The per-iteration `budget_status` marker (~line 994) must **replace** the
    prior one instead of accumulating. Tag it with a stable sentinel prefix
    (e.g. content starting `"[Budget:"` already exists); before appending the
    new marker, remove any existing message whose content starts with that
    prefix. Search by prefix, **not** by index (the list is mutated by
    `trim_loop_messages`).
  - The EMERGENCY marker (~line 964) is appended once when `synthesis_phase`
    flips (already guarded by `if not synthesis_phase`), so it does not
    accumulate — no change needed beyond confirming the guard.
- **Why not fold into a user turn at the orchestrator level:** doing so risks
  consecutive `user` messages and loses recency after many tool turns. With the
  adapter fold in place, the role-positioning concern is solved one layer down,
  so the orchestrator keeps the simpler `role="system"` emission.
- **Invariant:** `synthesis_phase` still sets `effective_tools = None` (hard
  no-tool guarantee) — unchanged.

### B4 — remove dead cross-turn cache reuse
- **File:** `orchestrator.py` `run()` (~lines 410-417).
- `wf_id` is freshly minted per request (`tracker.begin`), so
  `self._wf_enriched.get(wf_id)` at the top of `run()` always misses. Remove the
  dead reuse block and its misleading comment.
- **Keep** `self._cleanup_stale_results(stale_seconds)` (anti-leak sweep) and the
  in-run population of `_wf_enriched`/`_wf_sql_results` (used within a single
  run via `process_data` enrichment).

### I2/I3 — consolidate empty-result retry into one owner
- **Owner of the "empty == suspicious" signal:** the orchestrator result-gate
  (`_result_gate_directive`).
- **File:** `tool_dispatcher.py` `_handle_query_database` (~lines 411-436).
- **Change:** the dispatcher's retry loop keeps retrying on `not vr.passed`
  (real validation failure) but **stops** treating a clean zero-row result as a
  retry trigger (`empty_suspicious` branch removed from the dispatcher). The
  zero-row re-query decision is made once, at the result-gate, bounded by
  `orchestrator_max_result_corrections`.
- **Centralize semantics:** keep `AgentResultValidator.validate_sql_result` as
  the single source of truth for "is this result acceptable"; the result-gate
  and dispatcher both consult it rather than each re-deriving "empty == bad".
- Applied directly (no flag). `query_empty_result_retry` setting still governs
  whether the *result-gate* re-queries on zero rows (its existing meaning).

### I5 — give the router more of the latest user turn
- **File:** `router.py` `route_request` (~lines 233-239).
- **Change:** the tail messages stay capped by `history_tail_messages`, but the
  **final user turn** is passed with a larger char limit (e.g. 800) than the
  200-char cap applied to older context.
- **Config (optional, behavior-preserving):** add
  `router_last_turn_char_limit: int = 800` to `app/config.py` (+ docstring +
  `.env.example`). Older messages keep the 200-char cap. No behavior change for
  existing short turns.

### I6 — answer gate on the normal completion path (budget-conscious)
- **File:** `orchestrator.py` `_run_tool_loop`, normal completion
  (~lines 1078-1092) and `response_type` determination (~line 1390).
- **Current:** `AnswerValidator` runs only on step_limit/timeout paths.
- **Change:** when the LLM stops calling tools (normal completion) AND the
  result is **cheaply-detected suspicious**, run the existing
  `_validate_partial_answer` gate; if it judges the answer does not address the
  question, set `response_type` to a continuable label instead of `sql_result`.
- **"Cheaply-detected suspicious"** = any of:
  - `validate_sql_result(last_sql_result)` returned warnings, OR
  - `last_sql_result.results.row_count == 0`, OR
  - the result-gate spent its correction budget this workflow
    (`_wf_suspicious` set / correction count at max).
- If none of those hold, **no** extra LLM call is made — the normal hot path is
  unchanged in cost.

### I7 — DataGate must catch epoch-int dates
- **File:** `data_gate.py` `_check_value_ranges` (~line 284).
- **Current:** date-range check only runs for `isinstance(val, str)` via
  `datetime.fromisoformat`. Epoch seconds/ms arriving as `int`/`float` (the exact
  unit-error the check exists to catch) slip through.
- **Change:** add an `isinstance(val, (int, float))` branch for `kind == "date"`
  that flags values implausible as a unix timestamp:
  - interpret the number as epoch **seconds** and as epoch **milliseconds**;
  - if *neither* interpretation falls inside `[year_min, year_max]`, flag it.
  - Honors `data_gate_hard_checks_enabled` (fail vs warn) like the string path.

### I1 — documented-only (no code change)
`RouteResult.estimated_queries` feeds `ContextLoader.build_context_pack` →
`ContextPlanner.plan`, but `build_context_pack` has **zero callers** — the
Phase-4 ContextPlanner (`context_planner_enabled=False`) is built but unwired.
This is recorded here as **known incomplete wiring**, not removed, so a future
Phase-4 enablement does not have to re-add the router signal. No code change.

## 7. Testing strategy (TDD)

Every fix: failing test → confirm fail → minimal impl → confirm pass → commit
(conventional commits, e.g. `fix(orchestrator): …`, `fix(llm): …`).

| Finding | Test (new/updated) |
|---|---|
| B1 | complex-pipeline plan has auto-injected `min_rows` on `query_database` stages |
| B2 | single-call dispatch where a handler raises → turn survives, directive surfaced, gathered data preserved |
| B3-adapter | `anthropic._format_messages`: a mid-loop `system` msg lands in a user turn, not the top `system` param; leading system still hoisted |
| B3-orch/I4 | budget/emergency markers do not accumulate across iterations; emergency note is positionally last |
| B4 | `run()` no longer references `_wf_enriched` for cross-turn reuse (regression guard); cleanup still runs |
| I2/I3 | clean zero-row result is retried by the result-gate once (not double-retried by dispatcher) |
| I5 | router receives the full latest user turn up to the new char limit |
| I6 | suspicious normal-completion answer is downgraded; clean answer makes no extra LLM call |
| I7 | epoch-int date outside range → fail/warn per `data_gate_hard_checks_enabled` |

Regression: full `make check` (ruff format+check, mypy, unit+integration) and
combined coverage ≥ 72%. Existing tests referencing `estimated_queries` and
`_merge_nonleading_system` keep passing (no removals under I1-a).

## 8. Risks & mitigations

| Risk | Mitigation |
|---|---|
| B3 adapter change alters message shape for all Anthropic calls | Move existing OpenRouter merge tests to the shared module; add Anthropic-specific test; manual smoke on a multi-turn chat |
| I2/I3 changes latency profile of genuinely-empty queries | Result-gate still re-queries once on zero rows when `query_empty_result_retry` is on; only the *duplicate* dispatcher retry is removed |
| I6 could still add cost if "suspicious" predicate is too broad | Predicate restricted to warnings / zero-row / spent-budget; explicit "no LLM call otherwise" test |
| SEQ-CORE serialization slows the plan | Accept it — correctness over parallelism; P-ROUTER/P-GATE/P-ADAPTER run in parallel |

## 9. Definition of done

- All findings in scope implemented behind the contracts above.
- `make check` green; coverage ≥ 72%.
- No new feature flags except optional `router_last_turn_char_limit`.
- I1 documented in this spec; no code change.
- Conventional commits per finding; branch off `main` (not on `main`).
