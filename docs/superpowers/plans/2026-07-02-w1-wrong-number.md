# W1 — Wrong-Number Correctness (Intelligence Remediation)

**Plan date:** 2026-07-02 · **Wave:** W1 (parallel Group G1 with W4, after W0) · **Spec:**
`docs/superpowers/specs/2026-07-02-intelligence-remediation-design.md` §3 (W1 scope) · **Audit:**
`docs/INTELLIGENCE_AUDIT_2026-07.md` §4 (DATA-*) + §7 (SYNC-L1) + §2 (prod-validation row).

## Goal

Close the "confidently-wrong-number" defect class on both execution paths: stop presenting
truncated result sets as complete populations (DATA-01/02/04/12), teach the SQL agent explicit
arithmetic-correctness rules (DATA-03), run the DataGate hard-checks on the single-query path with
`Decimal` awareness (DATA-06/07), stop mis-classifying national-format phone numbers (DATA-05),
render missing chart values as gaps rather than zeros (DATA-09), make the required-filter guard
data-driven and *satisfiable* so a legitimate revenue query is never blocked to death (SYNC-L1,
elevated to Critical by the single real prod `query_failures` row), and make the answer validator /
investigation agent truncation-honest (DATA-16/17). A final batch closes the Low findings
(DATA-14/15/18/19/20/21/22).

Every wrong-number test asserts the *number is correct or explicitly refused/flagged* — never that
a bogus total silently ships.

## Architecture

Two execution paths reach the user (see CLAUDE.md "Request lifecycle"): the **flat unified loop**
(`orchestrator._run_tool_loop` → `SQLAgent._handle_execute_query`) and the **multi-stage pipeline**
(`StageExecutor._run_sql_stage` → `DataGate` → `response_builder.build_pipeline_response`). W1
touches leaf transforms and gates that both paths share:

- `app/services/data_processor.py` — in-memory `aggregate_data` / `filter_data` / `cohort_window`
  transforms that today drop `truncated` when they rebuild `QueryResult`.
- `app/agents/data_gate.py` — intermediate quality gate; its numeric predicate excludes `Decimal`
  and its truncation check ignores the authoritative `qr.truncated`.
- `app/agents/sql_agent.py` — single-query handler `_handle_execute_query` (line 450) and its
  `_run_sanity_checks` hook (line 965) — the wiring point for the shared `ResultValidation` gate.
- `app/agents/prompts/sql_prompt.py` — SQL-agent system prompt (the PRINCIPLES block, lines 93-105).
- `app/agents/response_builder.py` — synthesis-message builder (lines 217-298) and pipeline-response
  builder (lines 43-104).
- `app/agents/tool_dispatcher.py` — `process_data` result formatting (the "complete dataset" line,
  619).
- `app/services/phone_country_service.py` — E.164 prefix matcher.
- `app/viz/chart.py` — chart series builder (`_pivot_grouped` line 231, `_build_series` line 291).
- `app/core/required_filter_guard.py` — the 2-column hardcoded guard.
- `app/agents/answer_validator.py` — LLM answer-quality gate.
- `app/agents/investigation_agent.py` — "wrong data" deep-dive diagnostics.

**W0 dependency.** W0 (Foundations) lands the shared contracts this wave consumes: `derive_result`
(C-A), the `ResultValidation` gate (C-B/C-C), the `Decimal`-aware DataGate predicate (part of
C-B/C-C, verified in W0), and the three new metric counters (C-G). This plan **consumes** those
verbatim; it does not redefine them. Where a task depends on a W0 artifact it is tagged
`depends:[W0-...]`. Task 1 has a *pre-flight* step that asserts the W0 symbol exists and short-
circuits with a clear message if W0 has not merged — so an isolated implementer fails fast rather
than re-implementing the contract.

## Tech Stack

Python 3.12, FastAPI, SQLAlchemy 2.0 async, `pytest` with `asyncio_mode = "auto"` (no
`@pytest.mark.asyncio` needed — async test functions are collected automatically). Linting:
`ruff` (line length 100, rules `E F I N W UP`), `mypy --ignore-missing-imports`. Run tests via
`backend/.venv/bin/pytest`. `Decimal` from stdlib `decimal`. All commands below assume CWD
`/Users/sshlg/DATA/checkmydata-ai/backend`.

## Global Constraints

(From spec §2 + §6, and CLAUDE.md conventions.)

- **`QueryResult.truncated` is authoritative** (C-A). Any derived `QueryResult` carries it forward;
  any summary path surfaces it. Never present a truncated aggregate as a full-population total.
- **All derived results use `derive_result`** (C-A) — no hand-rolled `QueryResult(...)` in the
  transform paths.
- **DataGate is `Decimal`-aware and `qr.truncated`-first** (C-B/C-C, closes DATA-07/DATA-12).
- **`ResultValidation.evaluate` is the one post-result gate for both paths** (C-B/C-C). W1 wires the
  single-query path to it; W3 wires the pipeline (`ORCH-A01`). No W1 task edits `stage_executor.py`.
- **Required-filter guard must be satisfiable** (C-F): if a required filter cannot be satisfied
  after `k` attempts, **DEGRADE to a warning surfaced to the user — never hard-fail a legitimate
  query.** Emit `filter_guard_degrade_total`.
- **Honest degradation, no silent swallow.** Every external call keeps its existing try/except with
  a structured `logger.debug(..., exc_info=True)`; no secret leakage.
- **TDD, mandatory.** Each task: write failing test → run and confirm FAIL → minimal impl → run and
  confirm PASS → conventional commit. No task is done without a green test.
- **File ownership is disjoint per task within W1** and disjoint from W4 (per spec §5). No two W1
  tasks write the same file except where explicitly sequenced (Task 6 and Task 12 both touch
  `data_gate.py` — Task 12 depends on Task 6).
- **`make check` (ruff format+check, mypy, unit+integration, coverage ≥72%) must be green** before
  the wave is handed off (Task 15).
- **Docs updated in the same change** (CLAUDE.md feature-flags table, `backend/.env.example`,
  `API.md`) for any new setting.

---

## Interfaces consumed from W0 (verbatim — do not redefine)

These are copied verbatim from spec §2. W1 imports and calls them; changes require a spec amendment.

### C-A — `truncated` propagation (`app/connectors/base.py`)

```python
def derive_result(base: QueryResult, rows: list[tuple], *,
                  extra_truncation: bool = False, columns: list[str] | None = None,
                  **overrides) -> QueryResult:
    """Carry-forward constructor: truncated = base.truncated or extra_truncation."""
```

### C-B/C-C — unified post-result validation (`app/agents/result_validation.py`, NEW in W0)

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
  to override `qr.truncated`. Collaborators are the real `AgentResultValidator` result-gate and the
  free function `sql_results_reconcile` (there is no `SqlResultGate`/`SqlResultReconciliation`).
- Composes: `DataGate` hard-checks (**Decimal-aware**, **`qr.truncated`-aware** — closes
  DATA-07/DATA-12), the `AgentResultValidator` gate, zero-rows re-query + `sql_results_reconcile`.
- Invoked by **both** the flat loop (`orchestrator._run_tool_loop` post-dispatch) and the pipeline
  (`stage_executor._run_sql_stage`) — closes ORCH-A01, DATA-06.

### C-F — required-filter guard (`app/core/required_filter_guard.py`)

Becomes **data-driven** from `required_filters_json` (parse `col = val` / `col IS NULL`), replacing
the 2-key hardcode. **Satisfiability rule:** if a required filter cannot be satisfied by the
generated SQL after `k` attempts, **DEGRADE to a warning surfaced to the user — never hard-fail the
answer.** Guard emits metric `filter_guard_degrade_total`.

### C-G — metrics (`app/core/metrics.py`, existing)

New counters `datagate_block_total`, `filter_guard_degrade_total` are emitted via the existing
`MetricsCollector.inc(name: str, amount: int = 1, **labels: str)` obtained from
`get_metrics_collector()`.

---

## Task dependency graph & parallel groups (within W1)

```
Task 1 (C-A helper import guard + aggregate)  ── depends:[W0-C-A]
Task 2 (filter_data truncated)                ── depends:[Task 1]  (same file, sequence)
Task 3 (cohort_window truncated + refuse)     ── depends:[Task 2]  (same file, sequence)
Task 4 (tool_dispatcher "complete dataset")   ── depends:[W0-C-A]  (independent file)
Task 5 (sql_prompt correctness rules)         ── independent
Task 6 (DataGate Decimal predicate)           ── depends:[W0]      (data_gate.py)
Task 7 (response_builder synthesis PARTIAL)   ── independent
Task 8 (response_builder pipeline PARTIAL)    ── depends:[Task 7]  (same file, sequence)
Task 9 (phone E.164)                          ── independent
Task 10 (DataGate single-query via ResultVal) ── depends:[W0-C-B/C-C, Task 6]  (sql_agent.py)
Task 11 (chart null≠0)                         ── independent
Task 12 (DataGate truncation qr.truncated)    ── depends:[Task 6]  (same file, sequence)
Task 13 (required_filter_guard satisfiable)   ── depends:[W0-C-F]  (independent file)
Task 14 (answer_validator + investigation)    ── depends:[Task 1]  (uses derive_result semantics)
Task 15 (Low batch + make check + docs)       ── depends:[all above]
```

Same-file sequences: `data_processor.py` = Tasks 1→2→3; `data_gate.py` = Tasks 6→12;
`response_builder.py` = Tasks 7→8. Everything else is independent-file and may interleave. Task 15
is the sequential closer.

---

## Task 1 — DATA-01a: `aggregate_data` propagates `truncated`; refuse in-memory sum/count over truncated input

**depends:[W0-C-A]**

**Scene.** `DataProcessor._aggregate_data` (`app/services/data_processor.py:258-348`) groups rows
in memory and rebuilds a `QueryResult` at line 335 **omitting `truncated=`**, so `truncated`
silently defaults to `False`. Aggregating a 10 000-row-capped set then presents the total as a
full-population figure (audit DATA-01, Critical). Fix: carry `truncated` forward via C-A
`derive_result`, and for **additive** aggregations (`sum`, `count`, `count_distinct`) over a
truncated input, refuse to emit a bogus total — instead emit a clearly-flagged partial value the
summary must surface.

**Files:**
- `backend/app/services/data_processor.py` (edit `_aggregate_data`, lines 258-348; the
  `QueryResult(...)` build at 335-340 and the `summary` at 342-346).
- `backend/tests/unit/test_data_processor.py` (add tests).

**Interfaces:**

Consumes (W0, verbatim):
```python
# app/connectors/base.py
def derive_result(base: QueryResult, rows: list[tuple], *,
                  extra_truncation: bool = False, columns: list[str] | None = None,
                  **overrides) -> QueryResult:
    """Carry-forward constructor: truncated = base.truncated or extra_truncation."""
```

Produces (this task): no signature change to `_aggregate_data`; behavior change only. The
`ProcessedData.summary` gains a `PARTIAL DATA:` prefix line when the input was truncated and an
additive aggregation was requested. `_AGG_ADDITIVE_OVER_ROWS` module constant added:
```python
_AGG_ADDITIVE_OVER_ROWS: frozenset[str] = frozenset({"sum", "count", "count_distinct"})
```

### Steps

- [ ] **Pre-flight (W0 gate).** Add at the top of the new test module region:
```python
import pytest
from app.connectors import base as _base

pytestmark = pytest.mark.skipif(
    not hasattr(_base, "derive_result"),
    reason="W0 C-A derive_result not merged yet — this task depends on W0.",
)
```
  This makes the task fail fast (skip, not error) if W0 has not landed, rather than re-implementing
  the contract.

- [ ] **Failing test [REAL code].** Append to `backend/tests/unit/test_data_processor.py`:
```python
from decimal import Decimal

from app.connectors.base import QueryResult
from app.services.data_processor import DataProcessor


def _proc() -> DataProcessor:
    return DataProcessor(geoip=None, phone_svc=None)


def test_aggregate_data_carries_truncated_forward():
    """A truncated input must yield a truncated aggregate (DATA-01)."""
    qr = QueryResult(
        columns=["region", "amount"],
        rows=[["us", 10], ["us", 20], ["eu", 5]],
        row_count=3,
        truncated=True,
    )
    out = _proc().process(
        qr,
        "aggregate_data",
        {"group_by": ["region"], "aggregations": [("amount", "sum")]},
    )
    assert out.query_result.truncated is True


def test_aggregate_sum_over_truncated_is_flagged_partial_not_complete():
    """Additive aggregation over a truncated set must NOT present a full-population total."""
    qr = QueryResult(
        columns=["region", "amount"],
        rows=[["us", 10], ["us", 20]],
        row_count=2,
        truncated=True,
    )
    out = _proc().process(
        qr,
        "aggregate_data",
        {"group_by": ["region"], "aggregations": [("amount", "sum")]},
    )
    assert out.query_result.truncated is True
    assert "PARTIAL DATA" in out.summary
    # the numeric value is still computed over what we have, but flagged, never silently "complete"
    assert "30" in str(out.query_result.rows[0][1])


def test_aggregate_data_untruncated_input_stays_complete():
    qr = QueryResult(
        columns=["region", "amount"],
        rows=[["us", 10], ["eu", 5]],
        row_count=2,
        truncated=False,
    )
    out = _proc().process(
        qr,
        "aggregate_data",
        {"group_by": ["region"], "aggregations": [("amount", "sum")]},
    )
    assert out.query_result.truncated is False
    assert "PARTIAL DATA" not in out.summary
```

- [ ] **Run / expect FAIL.**
```
backend/.venv/bin/pytest tests/unit/test_data_processor.py -k "truncated or partial or complete" -v
```
  Expect: `test_aggregate_data_carries_truncated_forward` FAILS (`truncated is False`) and
  `test_aggregate_sum_over_truncated_is_flagged_partial_not_complete` FAILS (no `PARTIAL DATA`).

- [ ] **Minimal impl [REAL code].** In `backend/app/services/data_processor.py`, add the import and
  constant near the top:
```python
from app.connectors.base import QueryResult, derive_result  # add derive_result
```
```python
# additive aggregations whose total is meaningless / misleading over a
# truncated (row-capped) input — flag the result as partial (DATA-01).
_AGG_ADDITIVE_OVER_ROWS: frozenset[str] = frozenset({"sum", "count", "count_distinct"})
```
  Replace the `QueryResult(...)` build (lines 335-340) and the summary (lines 342-346) with:
```python
        agg_qr = derive_result(
            qr,
            result_rows,
            columns=result_columns,
            row_count=len(result_rows),
            execution_time_ms=qr.execution_time_ms,
        )

        summary = (
            f"Aggregated {len(qr.rows)} rows into {len(result_rows)} groups "
            f"by {', '.join(group_by)}. "
            f"Computed: {', '.join(f'{fn}({c})' for c, fn in agg_pairs)}."
        )
        if qr.truncated and any(
            fn.lower() in _AGG_ADDITIVE_OVER_ROWS for _c, fn in agg_pairs
        ):
            summary = (
                "PARTIAL DATA: the source result was capped/truncated, so these "
                "sum/count totals are computed over an INCOMPLETE set and are lower "
                "bounds, not full-population figures. " + summary
            )

        return ProcessedData(query_result=agg_qr, summary=summary)
```
  (`derive_result` sets `truncated = qr.truncated or extra_truncation`; `extra_truncation` defaults
  `False`, so the aggregate inherits the input's `truncated`.)

- [ ] **Run / expect PASS.**
```
backend/.venv/bin/pytest tests/unit/test_data_processor.py -k "truncated or partial or complete" -v
```
  Expect: 3 passed.

- [ ] **Commit.**
```
git add backend/app/services/data_processor.py backend/tests/unit/test_data_processor.py
git commit -m "fix(data): propagate truncated through aggregate_data; flag additive totals over truncated input (DATA-01)"
```

---

## Task 2 — DATA-01b: `filter_data` propagates `truncated`

**depends:[Task 1]** (same file, sequence)

**Scene.** `_filter_data` (`app/services/data_processor.py:397-434`) rebuilds `QueryResult` at 424
without `truncated=`. A filtered view of a truncated set is still a partial view; the flag must
survive so downstream aggregation/synthesis knows.

**Files:**
- `backend/app/services/data_processor.py` (edit `_filter_data`, the `QueryResult(...)` at 424-429).
- `backend/tests/unit/test_data_processor.py`.

**Interfaces:** Consumes C-A `derive_result` (verbatim, see Task 1). No signature change.

### Steps

- [ ] **Failing test [REAL code].** Append:
```python
def test_filter_data_carries_truncated_forward():
    qr = QueryResult(
        columns=["status", "n"],
        rows=[["ok", 1], ["ok", 2], ["bad", 3]],
        row_count=3,
        truncated=True,
    )
    out = _proc().process(qr, "filter_data", {"column": "status", "value": "ok"})
    assert out.query_result.truncated is True
    assert out.query_result.row_count == 2
```

- [ ] **Run / expect FAIL.**
```
backend/.venv/bin/pytest tests/unit/test_data_processor.py -k "filter_data_carries_truncated" -v
```
  Expect: FAIL (`truncated is False`).

- [ ] **Minimal impl [REAL code].** Replace the `QueryResult(...)` build at 424-429 with:
```python
        result_qr = derive_result(
            qr,
            filtered,
            columns=list(qr.columns),
            row_count=len(filtered),
            execution_time_ms=qr.execution_time_ms,
        )
```

- [ ] **Run / expect PASS.**
```
backend/.venv/bin/pytest tests/unit/test_data_processor.py -k "filter_data_carries_truncated" -v
```
  Expect: 1 passed.

- [ ] **Commit.**
```
git add backend/app/services/data_processor.py backend/tests/unit/test_data_processor.py
git commit -m "fix(data): propagate truncated through filter_data (DATA-01)"
```

---

## Task 3 — DATA-01c: `cohort_window` propagates `truncated` and flags cohort sums over truncated input

**depends:[Task 2]** (same file, sequence)

**Scene.** `_cohort_window` (`app/services/data_processor.py:513-672`) rebuilds `QueryResult` at 653
without `truncated=`. Worse, its per-window revenue-sum / distinct-id counts over a truncated event
set are lower bounds, not truths (audit DATA-01: "refuse in-memory sum/count/cohort over truncated
input"). Fix: carry `truncated` forward and prepend a `PARTIAL DATA:` line to the summary when the
input was truncated (cohort metrics are inherently additive over the row set).

**Files:**
- `backend/app/services/data_processor.py` (edit `_cohort_window`, the `QueryResult(...)` at 653-658
  and the `summary_parts` at 660-672).
- `backend/tests/unit/test_data_processor.py`.

**Interfaces:** Consumes C-A `derive_result` (verbatim). No signature change.

### Steps

- [ ] **Failing test [REAL code].** Append:
```python
def test_cohort_window_carries_truncated_and_flags_partial():
    qr = QueryResult(
        columns=["event_date", "revenue"],
        rows=[["2026-06-01", 100.0], ["2026-06-03", 50.0]],
        row_count=2,
        truncated=True,
    )
    out = _proc().process(
        qr,
        "cohort_window",
        {
            "release_dates": [{"tag": "v1", "date": "2026-06-01"}],
            "event_date_column": "event_date",
            "value_column": "revenue",
            "windows": [7],
            "metric": "revenue",
        },
    )
    assert out.query_result.truncated is True
    assert "PARTIAL DATA" in out.summary


def test_cohort_window_untruncated_no_partial_flag():
    qr = QueryResult(
        columns=["event_date", "revenue"],
        rows=[["2026-06-01", 100.0]],
        row_count=1,
        truncated=False,
    )
    out = _proc().process(
        qr,
        "cohort_window",
        {
            "release_dates": [{"tag": "v1", "date": "2026-06-01"}],
            "event_date_column": "event_date",
            "value_column": "revenue",
            "windows": [7],
            "metric": "revenue",
        },
    )
    assert out.query_result.truncated is False
    assert "PARTIAL DATA" not in out.summary
```

- [ ] **Run / expect FAIL.**
```
backend/.venv/bin/pytest tests/unit/test_data_processor.py -k "cohort_window_carries_truncated or cohort_window_untruncated" -v
```
  Expect: `..._carries_truncated_and_flags_partial` FAILS.

- [ ] **Minimal impl [REAL code].** Replace the `QueryResult(...)` build at 653-658 with:
```python
        result_qr = derive_result(
            qr,
            out_rows,
            columns=out_columns,
            row_count=len(out_rows),
            execution_time_ms=qr.execution_time_ms,
        )
```
  Then, inside the summary block, before the `return`, insert a partial-data prefix:
```python
        if qr.truncated:
            summary_parts.insert(
                0,
                "PARTIAL DATA: the source event set was capped/truncated, so these "
                "cohort revenue/retention values are computed over an INCOMPLETE set "
                "and are lower bounds, not full-population figures.",
            )
        return ProcessedData(query_result=result_qr, summary=" ".join(summary_parts))
```

- [ ] **Run / expect PASS.**
```
backend/.venv/bin/pytest tests/unit/test_data_processor.py -k "cohort_window_carries_truncated or cohort_window_untruncated" -v
```
  Expect: 2 passed. Then confirm no regression in the whole module:
```
backend/.venv/bin/pytest tests/unit/test_data_processor.py -v
```
  Expect: all passing.

- [ ] **Commit.**
```
git add backend/app/services/data_processor.py backend/tests/unit/test_data_processor.py
git commit -m "fix(data): propagate truncated through cohort_window and flag additive cohort metrics over truncated input (DATA-01)"
```

---

## Task 4 — DATA-02: `tool_dispatcher` stops calling a truncated set "the complete dataset"

**depends:[W0-C-A]** (reads `qr.truncated`; independent file)

**Scene.** `ToolDispatcher` `process_data` formatting (`app/agents/tool_dispatcher.py:610-620`)
tells the LLM: *"Use process_data with operation='aggregate_data' to compute groupings and
statistics over the complete dataset."* — even when `result_qr.truncated` is `True`. The LLM then
aggregates a sample as the whole (audit DATA-02, Critical). Fix: branch on `result_qr.truncated` and
never use the word "complete" for a truncated set; instead warn it is a partial/capped set.

**Files:**
- `backend/app/agents/tool_dispatcher.py` (edit the `else` branch at 610-620).
- `backend/tests/unit/test_tool_dispatcher_truncation.py` (NEW test module — no existing dedicated
  module; keep it small and focused).

**Interfaces:**

Consumes: `QueryResult.truncated: bool` (existing authoritative field). No signature change to
`_handle_process_data`.

Produces: the formatted tool text distinguishes complete vs partial. Extract a tiny pure helper for
testability:
```python
@staticmethod
def _full_data_hint(row_count: int, truncated: bool) -> str: ...
```

### Steps

- [ ] **Failing test [REAL code].** Create `backend/tests/unit/test_tool_dispatcher_truncation.py`:
```python
"""DATA-02: process_data must not call a truncated set 'complete'."""

from app.agents.tool_dispatcher import ToolDispatcher


def test_full_data_hint_marks_truncated_as_partial():
    hint = ToolDispatcher._full_data_hint(10_000, truncated=True)
    assert "complete dataset" not in hint.lower()
    assert "capped" in hint.lower() or "truncated" in hint.lower() or "partial" in hint.lower()


def test_full_data_hint_complete_for_untruncated():
    hint = ToolDispatcher._full_data_hint(42, truncated=False)
    assert "complete dataset" in hint.lower()
    assert "42" in hint
```

- [ ] **Run / expect FAIL.**
```
backend/.venv/bin/pytest tests/unit/test_tool_dispatcher_truncation.py -v
```
  Expect: FAIL — `AttributeError: ... has no attribute '_full_data_hint'`.

- [ ] **Minimal impl [REAL code].** Add the helper to `ToolDispatcher` (near
  `build_process_data_params`, ~line 625):
```python
    @staticmethod
    def _full_data_hint(row_count: int, truncated: bool) -> str:
        """Guidance line for the LLM after enrichment.

        DATA-02: never describe a row-capped/truncated result as "the complete
        dataset" — that makes the model aggregate a sample as the whole.
        """
        if truncated:
            return (
                f"WARNING: this enriched data is a CAPPED/TRUNCATED sample of "
                f"{row_count} row(s), NOT the complete dataset — any sum/count you "
                "compute over it is a lower bound. Re-run the underlying query with a "
                "tighter WHERE / server-side aggregation before reporting totals."
            )
        return (
            f"Full enriched data contains {row_count} rows. Use process_data with "
            "operation='aggregate_data' to compute groupings and statistics over "
            "the complete dataset."
        )
```
  Replace the `else` branch body at 610-620 with:
```python
        else:
            parts.append("")
            parts.append("**Sample rows (first 5):**")
            for row in result_qr.rows[:5]:
                parts.append(" | ".join(str(v) for v in row))
            if result_qr.row_count > 5:
                parts.append("\n" + self._full_data_hint(result_qr.row_count, result_qr.truncated))
```

- [ ] **Run / expect PASS.**
```
backend/.venv/bin/pytest tests/unit/test_tool_dispatcher_truncation.py -v
```
  Expect: 2 passed.

- [ ] **Commit.**
```
git add backend/app/agents/tool_dispatcher.py backend/tests/unit/test_tool_dispatcher_truncation.py
git commit -m "fix(agents): stop calling a truncated enriched set 'the complete dataset' (DATA-02)"
```

---

## Task 5 — DATA-03: SQL-correctness rules in the SQL agent prompt

**depends:** none (independent file)

**Scene.** `build_sql_system_prompt` (`app/agents/prompts/sql_prompt.py:93-105`) gives **zero**
guidance on JOIN grain/fan-out, `COUNT` vs `COUNT(DISTINCT)`, integer division, %-base, or
NULL-in-aggregate. Result: classic fan-out double-count, `count/total → 0` from integer division,
silently NULL-skipping AVG (audit DATA-03, High). Fix: add an explicit `SQL CORRECTNESS RULES` block
to the assembled prompt.

**Files:**
- `backend/app/agents/prompts/sql_prompt.py` (add a rules block to the `PRINCIPLES` section,
  ~lines 93-105).
- `backend/tests/unit/test_sql_prompt.py` (add/extend; create if absent).

**Interfaces:** Consumes: none. Produces: no signature change; `build_sql_system_prompt(...)` output
now always contains a `SQL CORRECTNESS RULES` section. Add a module constant for testability:
```python
SQL_CORRECTNESS_RULES: str  # the exact block, so tests assert on it without prompt-order coupling
```

### Steps

- [ ] **Failing test [REAL code].** Create/append
  `backend/tests/unit/test_sql_prompt.py`:
```python
"""DATA-03: SQL agent prompt teaches arithmetic-correctness rules."""

from app.agents.prompts.sql_prompt import build_sql_system_prompt


def test_prompt_contains_sql_correctness_rules():
    prompt = build_sql_system_prompt(db_type="postgres")
    low = prompt.lower()
    # JOIN grain / fan-out
    assert "fan-out" in low or "aggregate before" in low
    # COUNT vs COUNT(DISTINCT)
    assert "count(distinct" in low
    # integer division guard
    assert "1.0" in prompt or "::numeric" in low or "numeric" in low
    # NULLIF denominators
    assert "nullif" in low
    # % base must be stated
    assert "base" in low
    # NULL in aggregate
    assert "null" in low and "avg" in low


def test_prompt_correctness_rules_present_for_all_dialects():
    for db in ("postgres", "mysql", "clickhouse", "mongodb"):
        assert "SQL CORRECTNESS RULES" in build_sql_system_prompt(db_type=db)
```

- [ ] **Run / expect FAIL.**
```
backend/.venv/bin/pytest tests/unit/test_sql_prompt.py -v
```
  Expect: FAIL — `SQL CORRECTNESS RULES` absent.

- [ ] **Minimal impl [REAL code].** Add near the top of `sql_prompt.py` (after `DIALECT_HINTS`):
```python
SQL_CORRECTNESS_RULES = (
    "SQL CORRECTNESS RULES (avoid confidently-wrong numbers):\n"
    "- JOIN grain / fan-out: a one-to-many JOIN multiplies rows. Never SUM/COUNT a "
    "parent measure after joining a child table — aggregate the child to the parent "
    "grain first (subquery / CTE), then join. When unsure, verify the row count did "
    "not inflate versus the base table.\n"
    "- COUNT vs COUNT(DISTINCT): COUNT(col) counts non-NULL rows (inflated by fan-out); "
    "use COUNT(DISTINCT key) when you mean unique entities.\n"
    "- Integer division: dividing two integers truncates toward zero (e.g. 3/4 = 0). "
    "For ratios multiply by 1.0 or cast: `SUM(x) * 1.0 / NULLIF(SUM(y), 0)` (Postgres: "
    "`::numeric`).\n"
    "- Zero / NULL denominators: always wrap the divisor in NULLIF(denominator, 0) so a "
    "divide-by-zero yields NULL, never an error or a bogus 0.\n"
    "- Percentage base: state WHICH total the percentage is of (share of overall vs share "
    "within a group). Compute the base explicitly; do not assume the current filter is the "
    "whole population.\n"
    "- NULL in aggregates: SUM/AVG/COUNT(col) skip NULLs — AVG is over non-NULL rows only. "
    "If NULL should count as 0, COALESCE it first; state the denominator you used.\n"
)
```
  In `build_sql_system_prompt`, immediately after the `PRINCIPLES` `sections.append(...)` (line 105),
  add:
```python
    sections.append("")
    sections.append(SQL_CORRECTNESS_RULES)
```

- [ ] **Run / expect PASS.**
```
backend/.venv/bin/pytest tests/unit/test_sql_prompt.py -v
```
  Expect: 2 passed.

- [ ] **Commit.**
```
git add backend/app/agents/prompts/sql_prompt.py backend/tests/unit/test_sql_prompt.py
git commit -m "feat(prompt): add explicit SQL-correctness rules (JOIN grain, COUNT DISTINCT, integer division, NULLIF, %-base, NULL-in-aggregate) (DATA-03)"
```

---

## Task 6 — DATA-07: DataGate numeric predicate includes `Decimal`

**depends:[W0]** (W0 verifies/adds the Decimal predicate per C-B/C-C; this task adds W1 tests proving
currency columns are checked and closes any gap left)

**Scene.** `DataGate._check_value_ranges` (`app/agents/data_gate.py:325-449`) gates on
`numeric = isinstance(val, (int, float)) and not isinstance(val, bool)` (line 336). SQL money/rate
columns arrive as `decimal.Decimal`, so **every hard check is silently skipped for exactly the
columns where impossible values live** (audit DATA-07, High). Per spec §2 the W0 change adds
`Decimal` to the predicate; W1 adds the currency-column proof tests and, if W0 has not yet closed it,
lands the one-line predicate change.

**Files:**
- `backend/app/agents/data_gate.py` (the `numeric` predicate at line 336).
- `backend/tests/unit/test_data_gate.py` (add tests).

**Interfaces:** Consumes: `settings.data_gate_hard_checks_enabled` (existing). Produces: no signature
change; `_check_value_ranges` now treats `Decimal` as numeric.

### Steps

- [ ] **Failing test [REAL code].** Append to `backend/tests/unit/test_data_gate.py`:
```python
from decimal import Decimal

from app.agents.data_gate import DataGate
from app.agents.stage_context import PlanStage, StageContext, StageResult
from app.connectors.base import QueryResult


def _run_gate(qr: QueryResult) -> "DataGateOutcome":  # noqa: F821
    gate = DataGate(llm_semantics=False)
    stage = PlanStage(stage_id="s1", description="", tool="query_database")
    result = StageResult(stage_id="s1", status="success", query_result=qr)
    ctx = StageContext(plan=type("P", (), {"stages": [stage]})())  # minimal
    return gate.check(stage, result, ctx)


def test_datagate_flags_impossible_decimal_percent(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_gate_hard_checks_enabled", True)
    qr = QueryResult(
        columns=["conversion_pct"],
        rows=[[Decimal("150.0")]],
        row_count=1,
    )
    outcome = _run_gate(qr)
    assert not outcome.passed  # a Decimal 150% conversion must be caught, not skipped


def test_datagate_flags_negative_decimal_count(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_gate_hard_checks_enabled", True)
    qr = QueryResult(
        columns=["order_count"],
        rows=[[Decimal("-3")]],
        row_count=1,
    )
    outcome = _run_gate(qr)
    assert not outcome.passed
```
  (If the `StageContext`/`PlanStage` minimal construction in `_run_gate` does not match the real
  dataclass signatures, reuse the existing fixtures/builders already present in
  `test_data_gate.py` — check the top of that file and mirror its helper. The assertion content is
  what matters.)

- [ ] **Run / expect FAIL** (only if W0 has not landed the predicate; if W0 already did, these pass —
  which is the desired regression proof).
```
backend/.venv/bin/pytest tests/unit/test_data_gate.py -k "decimal" -v
```
  Expect: FAIL (`outcome.passed is True` because `Decimal` slipped the predicate) *unless W0 already
  closed it*.

- [ ] **Minimal impl [REAL code].** In `data_gate.py`, add the import at top:
```python
from decimal import Decimal
```
  Change line 336 from:
```python
                numeric = isinstance(val, (int, float)) and not isinstance(val, bool)
```
  to:
```python
                numeric = isinstance(val, (int, float, Decimal)) and not isinstance(val, bool)
```
  Also apply the same widening to the epoch-number branch guard (line 418):
```python
                elif kind == "date" and isinstance(val, (int, float, Decimal)) and not isinstance(
                    val, bool
                ):
```
  (`datetime.fromtimestamp(val / divisor, ...)` accepts `Decimal / int` → `Decimal`, which
  `fromtimestamp` handles; if mypy complains, wrap `float(val)`.)

- [ ] **Run / expect PASS.**
```
backend/.venv/bin/pytest tests/unit/test_data_gate.py -k "decimal" -v
```
  Expect: 2 passed.

- [ ] **Commit.**
```
git add backend/app/agents/data_gate.py backend/tests/unit/test_data_gate.py
git commit -m "fix(datagate): treat Decimal as numeric so currency/rate hard-checks are not skipped (DATA-07)"
```

---

## Task 7 — DATA-04a: synthesis summary surfaces `truncated` as a PARTIAL DATA line

**depends:** none (independent file; sequenced before Task 8, same file)

**Scene.** `ResponseBuilder.build_synthesis_messages`
(`app/agents/response_builder.py:217-298`) summarises each `SQLAgentResult` using `row_count` only
(line 251) and **never references `truncated`**. The final synthesis then states truncated totals
as complete (audit DATA-04, High). Fix: when any summarised result's `query_result.truncated` is
`True`, inject an explicit `PARTIAL DATA:` line into the `DATA COLLECTED` block so the synthesizing
LLM cannot present the total as full-population.

**Files:**
- `backend/app/agents/response_builder.py` (edit `build_synthesis_messages`, the per-result loop at
  240-257).
- `backend/tests/unit/test_chat_response_builder.py` (add test).

**Interfaces:** Consumes: `SQLAgentResult.results.truncated` (existing). Produces: no signature
change; the returned user message content contains `PARTIAL DATA` when any result was truncated.

### Steps

- [ ] **Failing test [REAL code].** Append to
  `backend/tests/unit/test_chat_response_builder.py` (mirror the existing imports/fixtures in that
  file for `SQLAgentResult` / `Message`; the skeleton below shows the assertion):
```python
def test_synthesis_surfaces_partial_data_when_truncated():
    from app.agents.response_builder import ResponseBuilder
    from app.agents.sql_agent import SQLAgentResult
    from app.connectors.base import QueryResult
    from app.llm.base import Message

    sr = SQLAgentResult(
        query="SELECT SUM(amount) FROM purchases",
        query_explanation="total revenue",
        results=QueryResult(
            columns=["total"], rows=[[123456]], row_count=1, truncated=True
        ),
    )
    msgs = ResponseBuilder.build_synthesis_messages(
        loop_messages=[Message(role="system", content="s"),
                       Message(role="user", content="revenue?")],
        sql_result=sr,
        knowledge_sources=[],
        context_window=8000,
    )
    joined = "\n".join(m.content for m in msgs)
    assert "PARTIAL DATA" in joined


def test_synthesis_no_partial_line_when_not_truncated():
    from app.agents.response_builder import ResponseBuilder
    from app.agents.sql_agent import SQLAgentResult
    from app.connectors.base import QueryResult
    from app.llm.base import Message

    sr = SQLAgentResult(
        query="SELECT SUM(amount) FROM purchases",
        query_explanation="total revenue",
        results=QueryResult(columns=["total"], rows=[[123456]], row_count=1, truncated=False),
    )
    msgs = ResponseBuilder.build_synthesis_messages(
        loop_messages=[Message(role="system", content="s"),
                       Message(role="user", content="revenue?")],
        sql_result=sr,
        knowledge_sources=[],
        context_window=8000,
    )
    joined = "\n".join(m.content for m in msgs)
    assert "PARTIAL DATA" not in joined
```
  (Confirm `SQLAgentResult`'s real field names by grepping `class SQLAgentResult` in
  `app/agents/sql_agent.py`; adjust the kwargs to match. The truncation assertion is the contract.)

- [ ] **Run / expect FAIL.**
```
backend/.venv/bin/pytest tests/unit/test_chat_response_builder.py -k "partial_data or partial_line" -v
```
  Expect: `..._surfaces_partial_data_when_truncated` FAILS.

- [ ] **Minimal impl [REAL code].** In `build_synthesis_messages`, inside the per-result loop, after
  the `data_parts.append(f"  Result: ...")` block (right after line 257) add:
```python
                if r.truncated:
                    data_parts.append(
                        "    PARTIAL DATA: this result was capped/truncated — any SUM/COUNT "
                        "shown is a LOWER BOUND over an incomplete set, NOT a full-population "
                        "total. Say so explicitly in the answer and do not present it as complete."
                    )
```

- [ ] **Run / expect PASS.**
```
backend/.venv/bin/pytest tests/unit/test_chat_response_builder.py -k "partial_data or partial_line" -v
```
  Expect: 2 passed.

- [ ] **Commit.**
```
git add backend/app/agents/response_builder.py backend/tests/unit/test_chat_response_builder.py
git commit -m "fix(synthesis): surface truncated results as a PARTIAL DATA line in the synthesis prompt (DATA-04)"
```

---

## Task 8 — DATA-04b: pipeline-response answer surfaces truncation of the shown result

**depends:[Task 7]** (same file, sequence)

**Scene.** `ResponseBuilder.build_pipeline_response`
(`app/agents/response_builder.py:43-104`) returns the pipeline `final_answer` and attaches
`last_sql_result.query_result` but never flags truncation in the user-facing answer text. A
`pipeline_complete` can present a truncated total as complete (audit DATA-04, High). Fix: when the
attached `results.truncated` is `True`, append a `PARTIAL DATA` sentence to the answer.

**Files:**
- `backend/app/agents/response_builder.py` (edit the `status == "completed"` branch, lines 78-104).
- `backend/tests/unit/test_chat_response_builder.py` (add test).

**Interfaces:** Consumes: `AgentResponse.results.truncated` (existing). Produces: no signature change;
`AgentResponse.answer` gains a `PARTIAL DATA` sentence when the shown result is truncated.

### Steps

- [ ] **Failing test [REAL code].** Append (reuse the pipeline `_StageExecutorResult` builder already
  used elsewhere in the test module if present; otherwise construct a minimal stub `exec_result`
  with a `stage_ctx` whose single stage result carries a truncated `query_result` and
  `status == "completed"`, `final_answer="Revenue is 123456."`). Assertion:
```python
def test_pipeline_response_appends_partial_data_when_truncated(pipeline_exec_result_truncated):
    from app.agents.response_builder import ResponseBuilder

    resp = ResponseBuilder.build_pipeline_response(
        pipeline_exec_result_truncated,
        wf_id="wf1",
        staleness_warning=None,
        pipeline_run_id="run1",
    )
    assert "PARTIAL DATA" in resp.answer
    assert resp.results is not None and resp.results.truncated is True
```
  Add a fixture near the top of the test module:
```python
import pytest


@pytest.fixture
def pipeline_exec_result_truncated():
    """Minimal completed pipeline exec-result whose shown result is truncated."""
    from app.agents.stage_context import PlanStage, StageContext, StageResult
    from app.connectors.base import QueryResult

    stage = PlanStage(stage_id="s1", description="revenue", tool="query_database")
    plan = type("P", (), {"stages": [stage]})()
    stage_ctx = StageContext(plan=plan)
    stage_ctx.set_result(
        "s1",
        StageResult(
            stage_id="s1",
            status="success",
            query="SELECT SUM(amount) FROM purchases",
            query_result=QueryResult(
                columns=["total"], rows=[[123456]], row_count=1, truncated=True
            ),
        ),
    )
    return type(
        "Exec",
        (),
        {
            "status": "completed",
            "final_answer": "Revenue is 123456.",
            "stage_ctx": stage_ctx,
            "checkpoint_result": None,
            "checkpoint_stage": None,
            "failed_validation": None,
            "failed_stage": None,
        },
    )()
```
  (Match `PlanStage` / `StageResult` / `StageContext` real signatures — grep `class PlanStage`,
  `class StageResult`, `class StageContext` in `app/agents/stage_context.py` and adjust kwargs.)

- [ ] **Run / expect FAIL.**
```
backend/.venv/bin/pytest tests/unit/test_chat_response_builder.py -k "pipeline_response_appends_partial" -v
```
  Expect: FAIL (no `PARTIAL DATA` in `resp.answer`).

- [ ] **Minimal impl [REAL code].** In the `status == "completed"` branch, right before the
  `return AgentResponse(...)` at line 90, compute a truncation suffix and append it to `answer`:
```python
            if last_sql_result and last_sql_result.query_result and (
                last_sql_result.query_result.truncated
            ):
                answer = (
                    f"{answer}\n\n"
                    "PARTIAL DATA: the result shown was capped/truncated, so any total "
                    "above is a lower bound over an incomplete set — not a full-population "
                    "figure. Re-run with a tighter filter or server-side aggregation for an "
                    "exact total."
                )
```

- [ ] **Run / expect PASS.**
```
backend/.venv/bin/pytest tests/unit/test_chat_response_builder.py -k "pipeline_response_appends_partial" -v
```
  Expect: 1 passed. Then full module:
```
backend/.venv/bin/pytest tests/unit/test_chat_response_builder.py -v
```

- [ ] **Commit.**
```
git add backend/app/agents/response_builder.py backend/tests/unit/test_chat_response_builder.py
git commit -m "fix(pipeline): append PARTIAL DATA notice to pipeline answer when the shown result is truncated (DATA-04)"
```

---

## Task 9 — DATA-05: phone→country requires E.164 / explicit country code; else Unknown + confidence

**depends:** none (independent file)

**Scene.** `PhoneCountryService.lookup` (`app/services/phone_country_service.py:285-298`) strips to
digits and prefix-matches with **no E.164 requirement**, so a national-format number like `7XXXXXXXXXX`
(a US/other national number without `+`) is misclassified to Russia (`+7`) — audit DATA-05, High.
Fix: only match when the input is in E.164 form (a leading `+`, or a leading `00` international
prefix). Otherwise return `Unknown` with an explicit low confidence. Add a `confidence: float` field
to `PhoneCountryResult`.

**Files:**
- `backend/app/services/phone_country_service.py` (edit `PhoneCountryResult` dataclass and `lookup`).
- `backend/tests/unit/test_phone_country_service.py` (add tests).

**Interfaces:**

Consumes: none. Produces (backward-compatible field addition):
```python
@dataclass(frozen=True)
class PhoneCountryResult:
    country_code: str
    country_name: str
    confidence: float = 1.0   # NEW: 0.0 for Unknown/ambiguous, 1.0 for E.164 match
```
`lookup(self, phone: str) -> PhoneCountryResult` signature unchanged.

**Note (needs-validation, spec §8 / audit §10):** national-format collisions were flagged for a W0
characterization test. This task's tests double as that characterization + fix.

### Steps

- [ ] **Failing test [REAL code].** Append to
  `backend/tests/unit/test_phone_country_service.py`:
```python
from app.services.phone_country_service import PhoneCountryService


def test_e164_plus_prefix_resolves():
    svc = PhoneCountryService()
    res = svc.lookup("+79991234567")
    assert res.country_code == "RU"
    assert res.confidence == 1.0


def test_national_format_without_plus_is_unknown():
    """A bare '7…' national number must NOT be mislabeled Russia (DATA-05)."""
    svc = PhoneCountryService()
    res = svc.lookup("7999123456")  # no '+', no '00' — ambiguous national format
    assert res.country_code == ""
    assert res.country_name == "Unknown"
    assert res.confidence == 0.0


def test_double_zero_international_prefix_resolves():
    svc = PhoneCountryService()
    res = svc.lookup("0033123456789")  # 00 + 33 (France)
    assert res.country_code == "FR"
    assert res.confidence == 1.0


def test_empty_is_unknown_zero_confidence():
    svc = PhoneCountryService()
    res = svc.lookup("")
    assert res.country_code == ""
    assert res.confidence == 0.0
```

- [ ] **Run / expect FAIL.**
```
backend/.venv/bin/pytest tests/unit/test_phone_country_service.py -k "e164 or national or double_zero or empty_is_unknown" -v
```
  Expect: `test_national_format_without_plus_is_unknown` FAILS (currently returns RU); the
  `confidence` assertions FAIL (`AttributeError`).

- [ ] **Minimal impl [REAL code].** Edit the dataclass:
```python
@dataclass(frozen=True)
class PhoneCountryResult:
    country_code: str
    country_name: str
    confidence: float = 1.0


_UNKNOWN = PhoneCountryResult(country_code="", country_name="Unknown", confidence=0.0)
```
  Replace `lookup`:
```python
    def lookup(self, phone: str) -> PhoneCountryResult:
        if not phone:
            return _UNKNOWN

        text = phone.strip()
        # DATA-05: only trust an explicit international form. A '+' prefix is
        # canonical E.164; a leading '00' is the ITU international call prefix.
        # A bare national number (no '+'/'00') is ambiguous — resolving it by
        # dialing-code prefix misclassifies (e.g. national '7…' -> Russia).
        if text.startswith("+"):
            digits = "".join(_DIGITS_RE.findall(text))
        elif text.startswith("00"):
            digits = "".join(_DIGITS_RE.findall(text))[2:]
        else:
            return _UNKNOWN
        if not digits:
            return _UNKNOWN

        for prefix in _SORTED_PREFIXES:
            if digits.startswith(prefix):
                cc, cn = _DIALING_CODE_MAP[prefix]
                return PhoneCountryResult(country_code=cc, country_name=cn, confidence=1.0)

        return _UNKNOWN
```

- [ ] **Run / expect PASS.**
```
backend/.venv/bin/pytest tests/unit/test_phone_country_service.py -v
```
  Expect: all passing (existing tests that pass `+`-prefixed E.164 numbers stay green; any existing
  test that relied on bare-national matching must be updated to E.164 — inspect and fix in the same
  commit, noting it in the message).

- [ ] **Commit.**
```
git add backend/app/services/phone_country_service.py backend/tests/unit/test_phone_country_service.py
git commit -m "fix(phone): require E.164/00 international form; else Unknown + zero confidence (DATA-05)"
```

---

## Task 10 — DATA-06: run DataGate hard-checks on the single-query path via C-B/C-C `ResultValidation`

**depends:[W0-C-B/C-C, Task 6]** (needs `ResultValidation` from W0 and the Decimal predicate from
Task 6)

**Scene.** DataGate hard-checks run **only on the pipeline path** (`stage_executor`), never on the
single-query flat-loop path (`SQLAgent._handle_execute_query`, `app/agents/sql_agent.py:450-562`). A
one-shot query that returns 150% conversion or a negative count is not blocked (audit DATA-06, High).
The `_run_sanity_checks` hook (line 965) is the wiring point. Per C-B/C-C, invoke the shared
`ResultValidation.evaluate` gate; a `block`/`warn` directive appends an explicit warning to the
returned tool text so the LLM (and user) see the impossible number flagged. Emit
`datagate_block_total` on a `block`.

**Files:**
- `backend/app/agents/sql_agent.py` (edit `_run_sanity_checks` / add a small `_run_result_gate`
  helper and call it from `_handle_execute_query` after `_run_sanity_checks`, lines 553-562).
- `backend/tests/unit/test_sql_agent_result_gate.py` (NEW focused module).

**Interfaces:**

Consumes (W0, verbatim):
```python
# app/agents/result_validation.py
@dataclass
class ResultDirective:
    action: Literal["accept", "warn", "requery", "block"]
    reason: str
    hints: list[str] = field(default_factory=list)

class ResultValidation:
    def __init__(self, data_gate: DataGate, result_gate: AgentResultValidator, *,
                 reconcile: Callable[[Sequence[Any]], bool] = sql_results_reconcile) -> None: ...
    def evaluate(self, qr: QueryResult, *, question: str, sql: str,
                 truncated: bool | None = None) -> ResultDirective: ...   # SYNC — no AgentContext
```
`evaluate` is **synchronous** (do NOT `await`) and takes no `AgentContext`; the collaborators are the
real `AgentResultValidator` + the free function `sql_results_reconcile`.
Also consumes `MetricsCollector.inc("datagate_block_total")` via `get_metrics_collector()`.

Produces (this task): a private async helper on `SQLAgent` (async only because it awaits the SQL
agent's own I/O around the gate — the gate call itself is sync):
```python
async def _run_result_gate(self, results: QueryResult, query: str, ctx: AgentContext) -> str:
    """Return warning text to append to the tool output when the shared
    ResultValidation gate flags the single-query result (DATA-06). Never raises."""
```

### Steps

- [ ] **Pre-flight (W0 gate).** At the top of the new test module:
```python
import importlib.util
import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("app.agents.result_validation") is None,
    reason="W0 C-B/C-C ResultValidation not merged yet — this task depends on W0.",
)
```

- [ ] **Failing test [REAL code].** Create `backend/tests/unit/test_sql_agent_result_gate.py`:
```python
"""DATA-06: single-query path runs the shared ResultValidation gate."""

import importlib.util

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("app.agents.result_validation") is None,
    reason="W0 C-B/C-C ResultValidation not merged yet — this task depends on W0.",
)

from unittest.mock import MagicMock

from app.connectors.base import QueryResult


async def test_result_gate_appends_warning_on_block(monkeypatch):
    from app.agents import sql_agent as sql_agent_mod
    from app.agents.result_validation import ResultDirective

    agent = sql_agent_mod.SQLAgent.__new__(sql_agent_mod.SQLAgent)  # bypass heavy __init__
    fake = MagicMock(  # evaluate is SYNC — a plain MagicMock, not AsyncMock
        return_value=ResultDirective(
            action="block",
            reason="Column 'conversion_pct' has value 150 out of range for a percentage.",
            hints=["Cast to ratio 0..1"],
        )
    )
    monkeypatch.setattr(
        sql_agent_mod, "_build_result_validation", lambda *a, **k: type("RV", (), {"evaluate": fake})()
    )

    qr = QueryResult(columns=["conversion_pct"], rows=[[150]], row_count=1)
    ctx = type("Ctx", (), {"user_question": "conversion?"})()
    text = await agent._run_result_gate(qr, "SELECT conversion_pct FROM t", ctx)
    assert "out of range" in text.lower() or "impossible" in text.lower()
    assert "150" in text


async def test_result_gate_silent_on_accept(monkeypatch):
    from app.agents import sql_agent as sql_agent_mod
    from app.agents.result_validation import ResultDirective

    agent = sql_agent_mod.SQLAgent.__new__(sql_agent_mod.SQLAgent)
    fake = MagicMock(return_value=ResultDirective(action="accept", reason="", hints=[]))  # SYNC
    monkeypatch.setattr(
        sql_agent_mod, "_build_result_validation", lambda *a, **k: type("RV", (), {"evaluate": fake})()
    )
    qr = QueryResult(columns=["n"], rows=[[5]], row_count=1)
    ctx = type("Ctx", (), {"user_question": "count?"})()
    assert await agent._run_result_gate(qr, "SELECT COUNT(*) FROM t", ctx) == ""
```

- [ ] **Run / expect FAIL.**
```
backend/.venv/bin/pytest tests/unit/test_sql_agent_result_gate.py -v
```
  Expect: FAIL — `SQLAgent` has no `_run_result_gate` (or the module has no `_build_result_validation`
  factory). (If W0 is not merged, the test is skipped — expected in that case.)

- [ ] **Minimal impl [REAL code].** In `app/agents/sql_agent.py`, add a module-level factory (so the
  test can monkeypatch it) near the imports:
```python
def _build_result_validation(agent: "SQLAgent"):
    """Assemble the shared ResultValidation gate (C-B/C-C). Lazy import to avoid
    an import cycle with result_validation at module load."""
    from app.agents.data_gate import DataGate
    from app.agents.result_validation import ResultValidation
    from app.agents.validation import AgentResultValidator

    # reconcile defaults to the free function sql_results_reconcile inside
    # ResultValidation — no SqlResultGate/SqlResultReconciliation classes exist.
    return ResultValidation(DataGate(), AgentResultValidator())
```
  (`ResultValidation.__init__(data_gate, result_gate, *, reconcile=sql_results_reconcile)` — the
  positional collaborators are `DataGate` + `AgentResultValidator`; `reconcile` keeps its default.)
  Add the helper method to `SQLAgent`:
```python
    async def _run_result_gate(
        self, results: QueryResult, query: str, ctx: AgentContext
    ) -> str:
        """Run the shared post-result gate on the single-query path (DATA-06).

        Returns warning text to append to the tool output when the gate flags an
        impossible/partial result; empty string on accept. Never raises."""
        try:
            gate = _build_result_validation(self)
            directive = gate.evaluate(  # SYNC — do not await
                results,
                question=getattr(ctx, "user_question", "") or query,
                sql=query,
                truncated=results.truncated,
            )
        except Exception:
            logger.debug("single-query result gate failed (non-critical)", exc_info=True)
            return ""
        if directive.action in ("block", "warn", "requery"):
            if directive.action == "block":
                try:
                    from app.core.metrics import get_metrics_collector

                    get_metrics_collector().inc("datagate_block_total", path="single_query")
                except Exception:
                    logger.debug("datagate_block_total inc failed", exc_info=True)
            hint = ("\n  " + "\n  ".join(directive.hints)) if directive.hints else ""
            return (
                f"\n\n**DATA QUALITY WARNING ({directive.action}):** "
                f"{directive.reason}{hint}"
            )
        return ""
```
  Wire it into `_handle_execute_query` after the sanity-check block (lines 555-561), before
  `return formatted`:
```python
        try:
            gate_text = await self._run_result_gate(results, loop_result.query, ctx)
            if gate_text:
                formatted += gate_text
        except Exception:
            logger.debug("result gate wiring failed (non-critical)", exc_info=True)

        return formatted
```

- [ ] **Run / expect PASS.**
```
backend/.venv/bin/pytest tests/unit/test_sql_agent_result_gate.py -v
```
  Expect: 2 passed.

- [ ] **Commit.**
```
git add backend/app/agents/sql_agent.py backend/tests/unit/test_sql_agent_result_gate.py
git commit -m "feat(sql-agent): run shared ResultValidation gate on the single-query path; flag impossible numbers (DATA-06)"
```

---

## Task 11 — DATA-09: charts render NULL / missing as a gap (null), not 0

**depends:** none (independent file)

**Scene.** In `app/viz/chart.py`, `_safe_numeric` maps NULL/unparseable → `0` (line 174-187), and
`_pivot_grouped` fills missing pivot cells with `0` (line 231) and `_build_series` maps NULLs to `0`
via `_safe_numeric` (line 291). Chart.js renders these as real zero bars/points → "0 sales in region
X" when the truth is "no data" (audit DATA-09, Med). Fix: introduce a null-preserving numeric
coercion for chart data (missing/NULL/unparseable → `None`, which Chart.js renders as a gap) and use
it for series/pivot values. Keep `_safe_numeric` for callers that genuinely need a float default (do
not change its contract), but route the series builders through a new `_chart_numeric`.

**Files:**
- `backend/app/viz/chart.py` (add `_chart_numeric`; use it in `_pivot_grouped` fill and
  `_build_series` datasets; missing-pivot-cell default `None`).
- `backend/tests/unit/test_chart.py` (add tests; create if absent — check `find tests -name
  "test_chart*.py"`).

**Interfaces:** Consumes: none. Produces:
```python
def _chart_numeric(val: Any) -> float | None:
    """NULL / missing / unparseable -> None (chart gap); numeric -> float. (DATA-09)"""
```

### Steps

- [ ] **Failing test [REAL code].** Create/append `backend/tests/unit/test_chart.py`:
```python
"""DATA-09: charts render NULL/missing as a gap (None), not 0."""

from app.connectors.base import QueryResult
from app.viz.chart import generate_bar_chart


def test_null_value_renders_as_gap_not_zero():
    result = QueryResult(
        columns=["region", "sales"],
        rows=[["us", 100], ["eu", None]],
        row_count=2,
    )
    chart = generate_bar_chart(result, {"labels_column": "region", "data_columns": ["sales"]})
    data = chart["data"]["datasets"][0]["data"]
    assert data[0] == 100.0
    assert data[1] is None  # NULL must be a gap, not 0


def test_missing_pivot_cell_is_gap_not_zero():
    from app.viz.chart import generate_line_chart

    result = QueryResult(
        columns=["month", "sales", "region"],
        rows=[["jan", 10, "us"], ["feb", 20, "eu"]],  # us has no feb, eu has no jan
        row_count=2,
    )
    chart = generate_line_chart(
        result,
        {"labels_column": "month", "data_columns": ["sales"], "group_by": "region"},
    )
    all_points = [p for ds in chart["data"]["datasets"] for p in ds["data"]]
    assert None in all_points  # the absent (region, month) cell is a gap
```

- [ ] **Run / expect FAIL.**
```
backend/.venv/bin/pytest tests/unit/test_chart.py -k "gap_not_zero" -v
```
  Expect: FAIL — `data[1] == 0.0` and no `None` in pivot points.

- [ ] **Minimal impl [REAL code].** Add near `_safe_numeric` in `chart.py`:
```python
def _chart_numeric(val: Any) -> float | None:
    """Coerce a chart data value, preserving absence as a gap.

    DATA-09: NULL / unparseable / missing must render as a Chart.js gap
    (``None``), never as a real ``0`` (which reads as "0 sales" instead of
    "no data"). Distinct from :func:`_safe_numeric`, which defaults to 0 for
    callers that need a concrete float.
    """
    if val is None:
        return None
    if isinstance(val, bool):
        return float(val)
    if isinstance(val, (int, float, Decimal)):
        return float(val)
    if isinstance(val, str):
        try:
            return float(val)
        except (ValueError, TypeError):
            return None
    return None
```
  In `_pivot_grouped`, change the value coercion (line 218) and the missing-cell fill (line 231):
```python
        val = _chart_numeric(serialize_value(row[data_idx]))
```
```python
                "data": [mapping.get(lbl, None) for lbl in labels],
```
  In `_build_series` (line 291) change:
```python
        numeric_data = [_chart_numeric(v) for v in raw_data]
```
  and the fallback loop (line 307):
```python
            numeric_data = [_chart_numeric(serialize_value(row[col_idx])) for row in result.rows]
```

- [ ] **Run / expect PASS.**
```
backend/.venv/bin/pytest tests/unit/test_chart.py -v
```
  Expect: all passing.

- [ ] **Commit.**
```
git add backend/app/viz/chart.py backend/tests/unit/test_chart.py
git commit -m "fix(viz): render NULL/missing chart values as gaps (null), not zeros (DATA-09)"
```

---

## Task 12 — DATA-12: DataGate truncation check reads authoritative `qr.truncated` first

**depends:[Task 6]** (same file, sequence)

**Scene.** `DataGate._check_truncation` (`app/agents/data_gate.py:451-463`) infers truncation only
from a round-number heuristic (`qr.row_count in common_limits`) and **ignores the authoritative
`qr.truncated`** (audit DATA-12, Med). Byte-capped truncation (where `row_count` is not a round
number) is missed; a legit `LIMIT 100` is false-flagged. Fix: check `qr.truncated` first — if set,
emit the truncation warning definitively; otherwise fall back to the heuristic.

**Files:**
- `backend/app/agents/data_gate.py` (edit `_check_truncation`, lines 451-463).
- `backend/tests/unit/test_data_gate.py` (add tests).

**Interfaces:** Consumes: `QueryResult.truncated` (existing). No signature change to
`_check_truncation`.

### Steps

- [ ] **Failing test [REAL code].** Append to `backend/tests/unit/test_data_gate.py`:
```python
def test_truncation_check_uses_authoritative_flag(monkeypatch):
    from app.agents.data_gate import DataGate, DataGateOutcome
    from app.agents.stage_context import PlanStage
    from app.connectors.base import QueryResult

    # row_count 137 is NOT a common LIMIT, but truncated=True is authoritative.
    qr = QueryResult(columns=["x"], rows=[[1]] * 137, row_count=137, truncated=True)
    outcome = DataGateOutcome()
    stage = PlanStage(stage_id="s1", description="", tool="query_database")
    DataGate._check_truncation(qr, stage, outcome)
    assert any("truncat" in w.lower() for w in outcome.warnings)


def test_truncation_check_no_false_flag_on_legit_limit():
    from app.agents.data_gate import DataGate, DataGateOutcome
    from app.agents.stage_context import PlanStage
    from app.connectors.base import QueryResult

    # LIMIT 100 that returned exactly 100 rows but the driver did NOT truncate:
    qr = QueryResult(columns=["x"], rows=[[1]] * 100, row_count=100, truncated=False)
    outcome = DataGateOutcome()
    stage = PlanStage(stage_id="s1", description="", tool="query_database")
    DataGate._check_truncation(qr, stage, outcome)
    # heuristic may still warn on the round number; assert the authoritative branch
    # did not ALSO fire a definitive truncation error. Warning-only is acceptable.
    assert outcome.passed
```

- [ ] **Run / expect FAIL.**
```
backend/.venv/bin/pytest tests/unit/test_data_gate.py -k "truncation_check_uses_authoritative" -v
```
  Expect: FAIL (137 is not a common limit and the flag is ignored → no warning).

- [ ] **Minimal impl [REAL code].** Replace the body of `_check_truncation` (lines 458-463):
```python
        # DATA-12: the driver's authoritative truncated flag wins. Byte-capped
        # truncation leaves a non-round row_count the heuristic would miss.
        if qr.truncated:
            outcome.warn(
                f"Result is truncated ({qr.row_count} rows returned; the driver "
                "capped the set) — any total over it is a lower bound.",
                suggestion="Add a tighter WHERE or aggregate server-side for a full total.",
            )
            return
        common_limits = set(settings.data_gate_common_limits)
        if qr.row_count in common_limits:
            outcome.warn(
                f"Row count ({qr.row_count}) is a common LIMIT value — result may be truncated.",
                suggestion="Verify the query's LIMIT clause returns all needed data.",
            )
```

- [ ] **Run / expect PASS.**
```
backend/.venv/bin/pytest tests/unit/test_data_gate.py -k "truncation" -v
```
  Expect: passing. Then the whole module:
```
backend/.venv/bin/pytest tests/unit/test_data_gate.py -v
```

- [ ] **Commit.**
```
git add backend/app/agents/data_gate.py backend/tests/unit/test_data_gate.py
git commit -m "fix(datagate): honor authoritative qr.truncated before the round-number heuristic (DATA-12)"
```

---

## Task 13 — SYNC-L1: data-driven, *satisfiable* required-filter guard (prod incident #1)

**depends:[W0-C-F]** (consumes the C-F contract; this task lands the data-driven parse + satisfiability
degrade + metric)

**Scene.** `check_required_filters` (`app/core/required_filter_guard.py:52-97`) enforces only two
hardcoded columns via `_FILTER_CHECKS` (`was_handled = 1`, `deleted_at IS NULL`). The single real
prod `query_failures` row (audit §2) is a **legitimate revenue query** — `"подсчитай доход за 1-29
июня 2026"` — that was **blocked to death** (3 attempts → failed) on
`required_filter_guard: missing purchases.deleted_at, purchases.was_handled`. Per C-F: (1) parse
required predicates **data-driven** from `required_filters_json` (`col = val` / `col IS NULL`)
instead of the 2-key hardcode; (2) **satisfiability rule** — after `k` attempts the guard must
**DEGRADE to a warning surfaced to the user, never hard-fail a legitimate query**; (3) emit
`filter_guard_degrade_total`.

**Files:**
- `backend/app/core/required_filter_guard.py` (add data-driven predicate compilation + a
  `check_required_filters(..., attempt: int = 1, max_attempts: int = ...)` satisfiability path +
  metric emit).
- `backend/tests/unit/test_required_filter_guard.py` (add tests, including the exact prod
  characterization).

**Interfaces:**

Consumes (C-F, verbatim intent): data-driven parse of `required_filters_json`
(`col = val` / `col IS NULL`); satisfiability degrade; metric `filter_guard_degrade_total`.
Also `MetricsCollector.inc("filter_guard_degrade_total")`.

Produces (extend the existing signature, backward-compatible defaults):
```python
def compile_filter_check(col: str, predicate: str) -> re.Pattern[str]:
    """Compile a required predicate (e.g. 'was_handled = 1', 'deleted_at IS NULL')
    into a regex that must appear in the query when the table is referenced."""

def check_required_filters(
    query: str,
    db_type: str,
    required_by_table: dict[str, set[str]] | dict[str, dict[str, str]],
    *,
    attempt: int = 1,
    max_attempts: int = 3,
) -> ValidationResult:
    """Data-driven, satisfiable guard (SYNC-L1, C-F).

    On the final attempt an unsatisfied required filter DEGRADES to a valid
    result carrying a user-facing warning (never a hard-fail), and increments
    ``filter_guard_degrade_total``."""
```
`ValidationResult` gains an optional warning surfaced upstream — reuse the existing
`ValidationResult` (add a `warning: str | None = None` field if absent; W0 owns `query_validation.py`
so if the field is missing, this task adds it minimally and notes it).

### Steps

- [ ] **Failing test [REAL code] — the prod characterization + data-driven + satisfiability.** Append
  to `backend/tests/unit/test_required_filter_guard.py`:
```python
from app.core.required_filter_guard import check_required_filters, compile_filter_check

# The exact prod-incident query (audit §2): a legitimate June revenue query that
# the 2-column hardcoded guard blocked to death.
PROD_REVENUE_QUERY = """
SELECT ROUND(SUM(amount) / 100, 2) AS revenue
FROM purchases
WHERE created_at >= '2026-06-01 00:00:00'
  AND created_at < '2026-06-30 00:00:00'
"""


def test_compile_filter_check_equality_and_is_null():
    eq = compile_filter_check("was_handled", "= 1")
    assert eq.search("... WHERE was_handled = 1 ...")
    assert not eq.search("... WHERE other = 1 ...")
    isnull = compile_filter_check("deleted_at", "IS NULL")
    assert isnull.search("... WHERE deleted_at IS NULL ...")


def test_data_driven_from_required_filters_json_dict():
    """Guard must enforce arbitrary configured predicates, not just the 2 hardcoded."""
    required = {"orders": {"is_test": "= 0"}}  # a column NOT in the old hardcode
    missing = "SELECT COUNT(*) FROM orders"
    res = check_required_filters(missing, "mysql", required, attempt=1, max_attempts=3)
    assert not res.is_valid
    ok = "SELECT COUNT(*) FROM orders WHERE is_test = 0"
    res2 = check_required_filters(ok, "mysql", required, attempt=1, max_attempts=3)
    assert res2.is_valid


def test_final_attempt_degrades_to_warning_not_hard_fail():
    """SYNC-L1: on the last attempt an unsatisfied filter DEGRADES — the legit
    revenue query must NOT be blocked to death."""
    required = {"purchases": {"was_handled": "= 1", "deleted_at": "IS NULL"}}
    res = check_required_filters(
        PROD_REVENUE_QUERY, "mysql", required, attempt=3, max_attempts=3
    )
    assert res.is_valid  # degraded, not blocked
    assert res.warning is not None
    assert "was_handled" in res.warning or "deleted_at" in res.warning


def test_degrade_increments_metric(monkeypatch):
    from app.core import metrics

    metrics._collector = metrics.MetricsCollector()  # fresh
    required = {"purchases": {"was_handled": "= 1"}}
    check_required_filters(PROD_REVENUE_QUERY, "mysql", required, attempt=3, max_attempts=3)
    counters = metrics.get_metrics_collector().snapshot_counters("filter_guard")
    assert counters.get("filter_guard_degrade_total", 0) >= 1


def test_early_attempt_still_hard_fails_to_drive_repair():
    """On non-final attempts the guard still fails so the repair loop adds the filter."""
    required = {"purchases": {"was_handled": "= 1"}}
    res = check_required_filters(
        PROD_REVENUE_QUERY, "mysql", required, attempt=1, max_attempts=3
    )
    assert not res.is_valid
```

- [ ] **Run / expect FAIL.**
```
backend/.venv/bin/pytest tests/unit/test_required_filter_guard.py -v
```
  Expect: FAIL — `compile_filter_check` missing; `check_required_filters` has no `attempt`/
  `max_attempts`; `is_test` not enforced; no degrade; no `warning`.

- [ ] **Minimal impl [REAL code].** Rewrite the data-driven core of
  `app/core/required_filter_guard.py`. Add the compiler and rewrite `check_required_filters` to be
  data-driven + satisfiable, keeping `parse_required_columns_from_hint` / `merge_required_filters`:
```python
def _predicate_to_regex(col: str, predicate: str) -> str:
    """Build a regex fragment for a required predicate string.

    Supports 'col = val', 'col IS NULL', 'col IS NOT NULL'. Falls back to a bare
    'col' presence check for anything else (advisory, still data-driven)."""
    c = re.escape(col)
    p = predicate.strip().upper()
    if p in ("IS NULL", "= NULL"):
        return rf"{c}\s+IS\s+NULL\b"
    if p in ("IS NOT NULL", "!= NULL", "<> NULL"):
        return rf"{c}\s+IS\s+NOT\s+NULL\b"
    m = re.match(r"^=\s*(.+)$", predicate.strip())
    if m:
        val = re.escape(m.group(1).strip())
        return rf"{c}\s*=\s*{val}\b"
    return rf"\b{c}\b"


def compile_filter_check(col: str, predicate: str) -> re.Pattern[str]:
    return re.compile(_predicate_to_regex(col, predicate), re.IGNORECASE)


def _normalize_required(
    required_by_table: dict[str, set[str]] | dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    """Accept either {table: {col}} (legacy) or {table: {col: predicate}} (data-driven).

    Legacy set form falls back to the built-in predicate for the 2 known columns
    and a bare-presence check otherwise, so nothing regresses."""
    legacy_pred = {"was_handled": "= 1", "deleted_at": "IS NULL"}
    out: dict[str, dict[str, str]] = {}
    for table, cols in required_by_table.items():
        if isinstance(cols, dict):
            out[table.lower()] = dict(cols)
        else:
            out[table.lower()] = {c: legacy_pred.get(c, "") for c in cols}
    return out


def check_required_filters(
    query: str,
    db_type: str,
    required_by_table: dict[str, set[str]] | dict[str, dict[str, str]],
    *,
    attempt: int = 1,
    max_attempts: int = 3,
) -> ValidationResult:
    """Fail when a referenced table is missing a configured required filter,
    but DEGRADE to a warning on the final attempt (SYNC-L1 / C-F): a legitimate
    query must never be blocked to death."""
    if db_type.lower() in {"mongodb", "mongo"} or not required_by_table:
        return ValidationResult(is_valid=True)

    normalized = _normalize_required(required_by_table)
    tables = {t.lower() for t in extract_tables(query)}
    if not tables:
        return ValidationResult(is_valid=True)

    missing: list[str] = []
    for table in tables:
        preds = normalized.get(table)
        if not preds:
            continue
        for col, predicate in sorted(preds.items()):
            pattern = compile_filter_check(col, predicate or "")
            if not pattern.search(query):
                missing.append(f"{table}.{col}")

    if not missing:
        return ValidationResult(is_valid=True)

    cols_str = ", ".join(missing)

    # Satisfiability: after the final attempt, degrade to a warning instead of a
    # hard fail so we never block a legitimate query to death (prod incident #1).
    if attempt >= max_attempts:
        try:
            from app.core.metrics import get_metrics_collector

            get_metrics_collector().inc("filter_guard_degrade_total", db_type=db_type.lower())
        except Exception:  # pragma: no cover - metrics must never break the guard
            pass
        return ValidationResult(
            is_valid=True,
            warning=(
                f"Could not apply required filter(s) after {max_attempts} attempts: {cols_str}. "
                "The answer is returned WITHOUT them — treat totals as potentially including "
                "invalid/soft-deleted rows and verify against the business definition."
            ),
        )

    return ValidationResult(
        is_valid=False,
        error=QueryError(
            error_type=QueryErrorType.UNKNOWN,
            message=(
                f"Query is missing required filter(s): {cols_str}. "
                "Add them to WHERE and retry."
            ),
            raw_error=f"required_filter_guard: missing {cols_str}",
            is_retryable=True,
            schema_hint=(
                "Required filters (from code-DB sync / schema index). Add every "
                "missing predicate to the WHERE clause before aggregating."
            ),
        ),
    )
```
  If `ValidationResult` has no `warning` field, add it in `app/core/query_validation.py`
  (`warning: str | None = None`) — minimal, backward-compatible. Then update the caller
  `ContextEnricher.validate_required_filters` to pass the attempt through: change its signature to
  `validate_required_filters(self, query, db_type, *, attempt=1, max_attempts=3)` and forward. The
  ValidationLoop call site (`app/core/validation_loop.py:147`) passes `attempt=attempt_num,
  max_attempts=self._config.max_retries`. Surface `filter_result.warning` into the loop's
  result/attempt so it reaches the user (append to the returned tool text / loop_result). *(These
  wiring edits are in files W1 owns exclusively — `context_enricher.py`, `validation_loop.py` are not
  claimed by W4 or W3 per spec §5; confirm ownership before editing and, if a conflict exists,
  sequence after the owning wave. Grep `validate_required_filters` for all callers and update each.)*

- [ ] **Run / expect PASS.**
```
backend/.venv/bin/pytest tests/unit/test_required_filter_guard.py -v
```
  Expect: all passing (including the 5 existing tests — the legacy set-form path is preserved by
  `_normalize_required`; `attempt=1` default keeps the old hard-fail behaviour for those tests).

- [ ] **Run the guard's downstream tests to catch wiring regressions.**
```
backend/.venv/bin/pytest tests/unit -k "validation_loop or context_enricher or required_filter" -v
```
  Expect: green.

- [ ] **Commit.**
```
git add backend/app/core/required_filter_guard.py backend/app/core/query_validation.py backend/app/core/context_enricher.py backend/app/core/validation_loop.py backend/tests/unit/test_required_filter_guard.py
git commit -m "fix(guard): data-driven, satisfiable required-filter guard; degrade-to-warning on final attempt + filter_guard_degrade_total metric (SYNC-L1)"
```

---

## Task 14 — DATA-16 + DATA-17: answer validator fed row_count/truncated; investigation diagnostics via read-only path + truncation-honest

**depends:[Task 1]** (relies on C-A truncated semantics being live)

**Scene A (DATA-16, Low-Med).** `AnswerValidator.validate`
(`app/agents/answer_validator.py:61-135`) judges only whether the *text* addresses the question from
`answer` + `sql_summaries` — no numbers, no `truncated`. It rubber-stamps a confidently-wrong number.
Fix: extend `validate(...)` with optional `row_count: int | None` and `truncated: bool = False`, and
inject a line into the LLM payload so a truncated result cannot be judged "addresses the question"
without acknowledgement. Scope honestly (completeness gate that KNOWS about truncation).

**Scene B (DATA-17, Low-Med).** `InvestigationAgent._handle_run_diagnostic_query`
(`app/agents/investigation_agent.py:187-212`) opens a **fresh** connector (not the read-only pooled
path), caps at 15 rows, and adds **no truncation note** — a "corrected" query then reasons from a
truncated sample and is stored as a learning, propagating the error. Fix: surface truncation
explicitly in the returned diagnostic text (the `SafetyGuard` read-only check already runs at line
194-197; keep it). Append a truncation note when `result.truncated` or `row_count > 15`.

**Files:**
- `backend/app/agents/answer_validator.py` (extend `validate`, add truncation line to payload).
- `backend/app/agents/investigation_agent.py` (edit `_handle_run_diagnostic_query`, 187-212).
- `backend/tests/unit/test_answer_validator.py` (add test; create if absent).
- `backend/tests/unit/test_investigation_agent.py` (add test).

**Interfaces:**

Produces (backward-compatible extension):
```python
async def validate(
    self, *, question: str, answer: str,
    sql_summaries: list[str] | None = None,
    row_count: int | None = None,          # NEW
    truncated: bool = False,               # NEW
    preferred_provider: str | None = None,
    model: str | None = None,
) -> AnswerValidationResult: ...
```
`_handle_run_diagnostic_query` signature unchanged; output text gains a truncation note.

### Steps

- [ ] **Failing test [REAL code] — DATA-16.** Append to
  `backend/tests/unit/test_answer_validator.py`:
```python
from unittest.mock import AsyncMock

from app.agents.answer_validator import AnswerValidator


async def test_validate_injects_truncation_into_payload():
    llm = AsyncMock()
    captured = {}

    async def _complete(*, messages, **kwargs):
        captured["user"] = messages[-1].content
        from app.llm.base import LLMResponse  # match real response type

        return LLMResponse(content='{"addresses_question": true, "confidence": 0.9, '
                                   '"is_partial": false, "reason": "ok"}')

    llm.complete = _complete
    v = AnswerValidator(llm)
    await v.validate(
        question="total revenue?",
        answer="Revenue is 123456.",
        sql_summaries=["1 row"],
        row_count=10000,
        truncated=True,
    )
    assert "PARTIAL" in captured["user"] or "truncat" in captured["user"].lower()
    assert "10000" in captured["user"]
```
  (Match `LLMResponse` / `complete` real shapes — grep `class LLMResponse` / the router `complete`
  signature and adjust; the contract is that truncation + row_count reach the payload.)

- [ ] **Failing test [REAL code] — DATA-17.** Append to
  `backend/tests/unit/test_investigation_agent.py`:
```python
async def test_diagnostic_query_surfaces_truncation(monkeypatch):
    from app.agents.investigation_agent import InvestigationAgent
    from app.connectors.base import QueryResult

    agent = InvestigationAgent.__new__(InvestigationAgent)
    agent._investigation_context = {}

    class _Conn:
        async def connect(self, cfg):
            return None

        async def disconnect(self):
            return None

        async def execute_query(self, q, *a, **k):
            return QueryResult(
                columns=["x"], rows=[[i] for i in range(20)], row_count=20, truncated=True
            )

    monkeypatch.setattr(
        "app.agents.investigation_agent.get_connector", lambda *a, **k: _Conn()
    )
    ctx = type("Ctx", (), {"connection_config": type("Cfg", (), {"db_type": "postgres",
                                                                 "ssh_exec_mode": False})()})()
    out = await agent._handle_run_diagnostic_query(
        {"query": "SELECT x FROM t", "hypothesis": "h"}, ctx
    )
    assert "truncat" in out.lower() or "capped" in out.lower()
```

- [ ] **Run / expect FAIL.**
```
backend/.venv/bin/pytest tests/unit/test_answer_validator.py -k "truncation_into_payload" tests/unit/test_investigation_agent.py -k "surfaces_truncation" -v
```
  Expect: both FAIL.

- [ ] **Minimal impl [REAL code] — DATA-16.** In `answer_validator.py`, extend `validate` params
  (add `row_count: int | None = None, truncated: bool = False`) and, after building `evidence`
  (line 88), inject:
```python
        data_facts = ""
        if row_count is not None:
            data_facts += f"\n\n## Result facts\n- rows returned: {row_count}"
            if truncated:
                data_facts += (
                    "\n- PARTIAL DATA: the result was TRUNCATED/capped — any total is a "
                    "lower bound. An answer that presents it as a complete/exact total does "
                    "NOT correctly address the question."
                )
        user_payload = (
            f"## User question\n{question.strip()}\n\n"
            f"## Agent answer\n{answer.strip()[:4000]}"
            f"{evidence}{data_facts}"
        )
```
  (Callers that already invoke `validate` keep working via the defaults; wiring callers to pass
  `row_count`/`truncated` is optional and can follow in W3 — this task delivers the capability +
  proof.)

- [ ] **Minimal impl [REAL code] — DATA-17.** In `_handle_run_diagnostic_query`, replace the row-cap
  block (lines 205-210) with a truncation-honest version:
```python
            lines = [f"Hypothesis: {hypothesis}", f"Columns: {', '.join(result.columns)}"]
            for row in result.rows[:15]:
                lines.append(" | ".join(str(v) for v in row))
            if result.row_count > 15 or result.truncated:
                lines.append(
                    f"... {max(result.row_count - 15, 0)} more rows. "
                    "WARNING: this diagnostic sample is TRUNCATED/capped — do NOT reason about "
                    "totals or store a 'corrected' query from it without re-running unbounded."
                )
            return "\n".join(lines)
```

- [ ] **Run / expect PASS.**
```
backend/.venv/bin/pytest tests/unit/test_answer_validator.py tests/unit/test_investigation_agent.py -v
```
  Expect: all passing.

- [ ] **Commit.**
```
git add backend/app/agents/answer_validator.py backend/app/agents/investigation_agent.py backend/tests/unit/test_answer_validator.py backend/tests/unit/test_investigation_agent.py
git commit -m "fix(agents): feed row_count/truncated to AnswerValidator; surface truncation in investigation diagnostics (DATA-16, DATA-17)"
```

---

## Task 15 — Low batch (DATA-14/15/18/19/20/21/22) + docs + `make check` gate

**depends:[Tasks 1-14]**

**Scene.** Close the Low findings from audit §4 as one focused cleanup task, then update docs and run
the wave gate. The Low findings (per-finding notes in the subsystem review):

- **DATA-14** — range-scan (`_check_value_ranges`) runs only on a sample cap; ensure the hard-check
  scan covers the full in-memory result (the cap already defaults to full when
  `data_gate_value_range_sample <= 0`; add a regression test asserting an out-of-range value in a
  late row is still caught).
- **DATA-15** — reconciliation exact-round bucketing: values that differ only by rounding are treated
  as mismatches. Add a tolerance (relative epsilon) test + fix in the `sql_results_reconcile`
  bucketing *(if this lives in a W3/W0-owned file, land only the test here and file the fix note; do
  not edit a file another wave owns)*.
- **DATA-18** — duplicate / null-rate false signals on legitimately-sparse columns: gate the
  duplicate warning behind a minimum sample and document that null-rate is advisory (test the
  threshold behaviour).
- **DATA-19** — COUNT semantics doc: add a short docstring note where `_compute_agg` handles
  `count` vs `count_distinct` clarifying NULL handling.
- **DATA-20** — unformatted numbers in output: ensure large integers/`Decimal` render readably in
  `tool_dispatcher` aggregation output (thousands separator) — test the formatter.
- **DATA-21** — small-fan-out cartesian miss: `_check_cross_stage_consistency` only warns above
  `cartesian_multiplier`; add a test documenting the known small-fan-out gap (assert current
  behaviour, mark as documented limitation — no over-engineering).
- **DATA-22** — distinct-value / sample-based signals unmarked as partial: where a sample drives a
  signal, label it "(sampled)" in the message.

Land only the fixes whose owning file is W1's (`data_gate.py`, `data_processor.py`,
`tool_dispatcher.py`). For any Low finding whose file is owned by another wave, add the failing test
guarded/`xfail` with a reason string referencing the owning wave and leave the fix to that wave — do
not edit another wave's file (spec §5).

**Files:**
- `backend/app/agents/data_gate.py`, `backend/app/services/data_processor.py`,
  `backend/app/agents/tool_dispatcher.py` (targeted Low fixes only).
- `backend/tests/unit/test_data_gate.py`, `test_data_processor.py`,
  `test_tool_dispatcher_truncation.py` (Low-batch tests).
- Docs: `CLAUDE.md` (feature-flags / DataGate note if a new flag added — none expected),
  `CHANGELOG.md` (`[Unreleased]` W1 entry), `API.md` (new `filter_guard_degrade_total` /
  `datagate_block_total` counters under the metrics section).

**Interfaces:** Consumes: everything from Tasks 1-14. Produces: no new public signatures beyond a
number-formatting helper in `tool_dispatcher` if needed:
```python
@staticmethod
def _fmt_cell(v: Any) -> str:  # DATA-20 readable numbers
```

### Steps

- [ ] **Failing tests [REAL code].** Add focused Low-batch tests. Example for DATA-14 + DATA-20 (the
  rest follow the same shape — one small test per finding, asserting the specific behaviour):
```python
# tests/unit/test_data_gate.py — DATA-14: late-row out-of-range still caught
def test_hard_check_scans_late_rows(monkeypatch):
    from app.agents.data_gate import DataGate, DataGateOutcome
    from app.connectors.base import QueryResult
    from app.config import settings

    monkeypatch.setattr(settings, "data_gate_hard_checks_enabled", True)
    monkeypatch.setattr(settings, "data_gate_value_range_sample", 0)  # full scan
    rows = [[10.0] for _ in range(500)] + [[150.0]]  # bad value is the LAST row
    qr = QueryResult(columns=["conversion_pct"], rows=rows, row_count=len(rows))
    gate = DataGate(llm_semantics=False)
    outcome = DataGateOutcome()
    gate._check_value_ranges(qr, outcome)
    assert not outcome.passed
```
```python
# tests/unit/test_tool_dispatcher_truncation.py — DATA-20: readable large numbers
def test_fmt_cell_thousands_separator():
    from app.agents.tool_dispatcher import ToolDispatcher
    assert ToolDispatcher._fmt_cell(1234567) == "1,234,567"
    assert ToolDispatcher._fmt_cell("text") == "text"
```

- [ ] **Run / expect FAIL.**
```
backend/.venv/bin/pytest tests/unit/test_data_gate.py -k "late_rows" tests/unit/test_tool_dispatcher_truncation.py -k "thousands" -v
```
  Expect: FAIL.

- [ ] **Minimal impl [REAL code].** DATA-20 helper in `tool_dispatcher.py`:
```python
    @staticmethod
    def _fmt_cell(v: Any) -> str:
        """Render a cell readably: thousands separators for ints/Decimal, str otherwise."""
        from decimal import Decimal

        if isinstance(v, bool):
            return str(v)
        if isinstance(v, int):
            return f"{v:,}"
        if isinstance(v, Decimal):
            return f"{v:,}"
        return str(v)
```
  Use `_fmt_cell` in the aggregation-row rendering loop (replace `str(v)` at line 607). For DATA-14,
  no code change is needed if `data_gate_value_range_sample<=0` already means full-scan (the test
  proves it); if the default is a positive cap, the test still passes by setting the flag — document
  the behaviour in `_check_value_ranges`' docstring. Apply the remaining Low fixes (DATA-18/19/22
  message labels + docstrings) minimally; `xfail` DATA-15/DATA-21 tests referencing the owning wave
  if their fix-file is not W1's.

- [ ] **Run / expect PASS + full W1 suite.**
```
backend/.venv/bin/pytest tests/unit/test_data_gate.py tests/unit/test_data_processor.py tests/unit/test_tool_dispatcher_truncation.py tests/unit/test_phone_country_service.py tests/unit/test_chart.py tests/unit/test_required_filter_guard.py tests/unit/test_sql_prompt.py tests/unit/test_answer_validator.py tests/unit/test_investigation_agent.py tests/unit/test_chat_response_builder.py tests/unit/test_sql_agent_result_gate.py -v
```
  Expect: all passing (W0-dependent modules skip cleanly if W0 is not merged in this workspace).

- [ ] **Docs.** Add a `[Unreleased]` W1 entry to `CHANGELOG.md` summarising DATA-01…22 + SYNC-L1;
  add the two new counters (`datagate_block_total`, `filter_guard_degrade_total`) to `API.md`'s
  `/api/metrics` section; confirm CLAUDE.md's DataGate / metrics prose still matches.

- [ ] **Wave gate — `make check`.**
```
cd /Users/sshlg/DATA/checkmydata-ai && make check
```
  Expect: ruff format+check clean, mypy clean, unit+integration green, coverage ≥72%. Fix any
  ruff/mypy nits (line length 100; `Decimal` import ordering `I`) in the touched files.

- [ ] **Commit.**
```
git add backend/app backend/tests CHANGELOG.md API.md CLAUDE.md
git commit -m "fix(data): W1 Low-batch (DATA-14/15/18/19/20/21/22) + docs; make check green"
```

---

## Definition of Done (wave)

- Every task above committed with a green test (or a documented `skipif`/`xfail` tied to a W0/other-
  wave dependency).
- `make check` green: ruff format+check, mypy, unit+integration, coverage ≥72% (the combined
  `--fail-under=72` gate).
- Docs updated in the same changes (CHANGELOG `[Unreleased]`, API.md metrics, CLAUDE.md prose).
- Wrong-number invariants proven by test: aggregate/percent/cohort over a truncated set is either
  computed-and-flagged (`PARTIAL DATA`) or refused — never silently presented as a complete total;
  impossible `Decimal` percentages/negative counts are caught on **both** paths; the prod revenue
  query is no longer blocked to death (degrades to a warning).

## Handoff

Runs in Group G1 (parallel with W4) on an isolated worktree
(`superpowers:using-git-worktrees`), executed via `superpowers:subagent-driven-development` with the
task dependency graph above. Two-stage review per task (spec compliance, then code quality). Tasks
tagged `depends:[W0-...]` must not start until W0 has merged into the base branch of this worktree;
their pre-flight `skipif` guards make an early start fail fast rather than silently no-op.
