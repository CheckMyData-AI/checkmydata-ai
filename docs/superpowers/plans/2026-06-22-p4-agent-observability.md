# P4 — Agent-Lifecycle Observability Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Guarantee that every agent capability (build queries, work with data, search data, validate data, answer, converse, handle errors) emits a correctly-typed span **and** that validation failures land in the `error_log` catalog — so nothing on the agent path is silent and the logs UI can filter agent failures.

**Architecture:** The orchestrator/stage-executor are already span-instrumented; this milestone closes gaps rather than rebuilding. We add explicit `span_type="validation"` to the DataGate and answer-validation emits, and a single `ErrorLogService.upsert_validation_failure(...)` invoked when DataGate hard-blocks or the AnswerValidator fails closed. A coverage test pins the `classify_span_type` mapping so future steps stay typed.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 async, pytest (asyncio auto).

**Source spec:** `…/2026-06-22-sync-and-observability-redesign-design.md` (§6 agent query-lifecycle correctness; §8 logging coverage). **Depends on:** P0 (`ErrorLog`, `ErrorLogService`), P1, P3 (query-plane error catalog).

## Global Constraints

- **Greenfield — no backward compatibility.** No orchestrator rewrite — additive observability only.
- Existing anchors (verified): `stage_executor._emit_data_gate` (`agents/stage_executor.py:296`, `:1025`); `stage_executor` stage validation `self._validator.validate_async(...)` (`:278`); orchestrator `_validate_partial_answer` (`agents/orchestrator.py:1384`); DataGate verdict object `DataGateOutcome` with `.errors`/`.suggestions` (`agents/data_gate.py:45`); `AnswerValidator` fail-closed path (`agents/answer_validator.py:114`); span-type classifier `classify_span_type` (`services/trace_persistence_service.py:87`).
- Locked interface consumed: `ErrorLogService.upsert(db, *, project_id, source, kind, message, failure_kind=None, sample_ref=None, meta=None)`.
- `span_type` values: `llm_call | db_query | rag | tool_call | sub_agent | viz | validation | other`.
- Python 3.12, line length 100, ruff `0.15.15`, mypy clean, async-only, coverage ≥ 72%.
- Conventional commits ending with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- Run commands from `backend/` via `.venv/bin/<tool>`.

## File Structure

- Modify `app/services/error_log_service.py` — `upsert_validation_failure(...)`.
- Modify `app/agents/stage_executor.py` — `_emit_data_gate` carries `span_type="validation"` and upserts an error_log entry on hard-block.
- Modify `app/agents/orchestrator.py` — answer-validation fail-closed emits a `validation` span + error_log entry.
- Modify `app/services/trace_persistence_service.py` — ensure `classify_span_type` maps `data_gate`/`answer_validate` to `validation` (add any missing keys).
- Tests under `tests/unit/services/`, `tests/unit/agents/`.

Reuse the P0 in-memory `session` fixture.

---

### Task 1: `ErrorLogService.upsert_validation_failure`

**Files:**
- Modify: `app/services/error_log_service.py`
- Test: `tests/unit/services/test_error_log_validation.py`

**Interfaces:**
- Produces: `ErrorLogService.upsert_validation_failure(db, *, project_id, kind, message, sample_ref=None, meta=None) -> ErrorLog` — thin wrapper over `upsert(source="span", failure_kind="data_missing", ...)`; `kind` ∈ `data_gate|answer`.

- [ ] **Step 1: Write the failing test**

`tests/unit/services/test_error_log_validation.py`:

```python
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
import app.models  # noqa: F401
from app.models.error_log import ErrorLog
from app.services.error_log_service import ErrorLogService


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    s = sm()
    try:
        yield s
    finally:
        await s.close()
        await engine.dispose()


async def test_validation_failure_cataloged(session: AsyncSession):
    await ErrorLogService().upsert_validation_failure(
        session, project_id="p", kind="data_gate",
        message="percentage 142% exceeds 100", sample_ref="wf-1")
    rows = (await session.execute(select(ErrorLog).where(ErrorLog.project_id == "p"))).scalars().all()
    assert len(rows) == 1
    assert rows[0].source == "span"
    assert rows[0].kind == "data_gate"
    assert rows[0].failure_kind == "data_missing"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/unit/services/test_error_log_validation.py -v`
Expected: FAIL — `AttributeError: 'ErrorLogService' object has no attribute 'upsert_validation_failure'`.

- [ ] **Step 3: Write minimal implementation**

Add to `app/services/error_log_service.py`:

```python
    async def upsert_validation_failure(self, db, *, project_id, kind, message,
                                        sample_ref=None, meta=None):
        return await self.upsert(
            db, project_id=project_id, source="span", kind=kind, message=message,
            failure_kind="data_missing", sample_ref=sample_ref, meta=meta,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/unit/services/test_error_log_validation.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd backend && .venv/bin/ruff check app/ && .venv/bin/mypy app/ --ignore-missing-imports
git add backend/app/services/error_log_service.py backend/tests/unit/services/test_error_log_validation.py
git commit -m "feat(observability): error_log helper for validation failures

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: DataGate verdicts are typed validation spans + cataloged on block

**Files:**
- Modify: `app/agents/stage_executor.py` (`_emit_data_gate` ~line 1013-1044)
- Test: `tests/unit/agents/test_data_gate_observability.py`

**Interfaces:**
- `_emit_data_gate(wf_id, stage, outcome)` passes `span_type="validation"` on its emit; when `outcome.errors` is non-empty (hard block), it calls `ErrorLogService.upsert_validation_failure(..., kind="data_gate", message=outcome.error_summary(), sample_ref=wf_id, meta={"project_id": ...})` using a fresh session.

- [ ] **Step 1: Write the failing test**

`tests/unit/agents/test_data_gate_observability.py`:

```python
from __future__ import annotations

import inspect

from app.agents import stage_executor


def test_emit_data_gate_uses_validation_span_type_and_catalogs():
    src = inspect.getsource(stage_executor.StageExecutor._emit_data_gate)
    assert 'span_type="validation"' in src
    assert "upsert_validation_failure" in src
```

> A source-level assertion keeps the test hermetic (no full pipeline). The behavioral path is exercised by the integration trace tests already in the suite.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/unit/agents/test_data_gate_observability.py -v`
Expected: FAIL — neither string present.

- [ ] **Step 3: Write minimal implementation**

In `app/agents/stage_executor.py` `_emit_data_gate`, add `span_type="validation"` to the `self._tracker.emit(...)` call (line ~1025), and after the emit, when the outcome has hard errors, catalog it:

```python
        if outcome.errors:
            try:
                from app.models.base import async_session_factory
                from app.services.error_log_service import ErrorLogService

                project_id = getattr(stage, "project_id", None) or getattr(self, "_project_id", None)
                async with async_session_factory() as db:
                    await ErrorLogService().upsert_validation_failure(
                        db, project_id=project_id, kind="data_gate",
                        message=outcome.error_summary(), sample_ref=wf_id)
            except Exception:  # noqa: BLE001 — observability must never break the stage
                logger.debug("data_gate error_log upsert failed", exc_info=True)
```

> If `stage`/`self` does not expose `project_id`, thread the project id into `_emit_data_gate` from its caller (`run_stage` has `stage_ctx`/`context` with the project id). Pick the available source and pass it; do not leave `project_id` `None` when a real id is in scope.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/unit/agents/test_data_gate_observability.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd backend && .venv/bin/ruff check app/ && .venv/bin/mypy app/ --ignore-missing-imports
git add backend/app/agents/stage_executor.py backend/tests/unit/agents/test_data_gate_observability.py
git commit -m "feat(observability): DataGate verdicts typed + hard blocks cataloged

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Answer-validation fail-closed is observed + span-type coverage

**Files:**
- Modify: `app/agents/orchestrator.py` (`_validate_partial_answer` ~line 1384)
- Modify: `app/services/trace_persistence_service.py` (`classify_span_type` map, ~line 56/87)
- Test: `tests/unit/services/test_span_type_coverage.py`, `tests/unit/agents/test_answer_validation_observability.py`

**Interfaces:**
- When `_validate_partial_answer` resolves to fail-closed (answer does not address the question), the orchestrator emits a `validation` span and calls `ErrorLogService.upsert_validation_failure(..., kind="answer", ...)`.
- `classify_span_type` maps `data_gate`→`validation`, `answer`/`answer_validate`→`validation`, `validate`→`validation`, ensuring the heuristic stays correct for any non-explicit emit.

- [ ] **Step 1: Write the failing tests**

`tests/unit/services/test_span_type_coverage.py`:

```python
from __future__ import annotations

import pytest

from app.services.trace_persistence_service import classify_span_type


@pytest.mark.parametrize("step,expected", [
    ("data_gate", "validation"),
    ("answer_validate", "validation"),
    ("validate_tables", "validation"),
    ("sql_query", "db_query"),
])
def test_classify_span_type_known_steps(step, expected):
    assert classify_span_type(step) == expected
```

`tests/unit/agents/test_answer_validation_observability.py`:

```python
from __future__ import annotations

import inspect

from app.agents import orchestrator


def test_partial_answer_failclose_is_cataloged():
    src = inspect.getsource(orchestrator.OrchestratorAgent._validate_partial_answer)
    assert "upsert_validation_failure" in src
```

> Use the actual orchestrator class name in `orchestrator.py` for the `getsource` target if it differs from `OrchestratorAgent` (confirm with `grep -n "class .*Orchestrator" app/agents/orchestrator.py`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/pytest tests/unit/services/test_span_type_coverage.py tests/unit/agents/test_answer_validation_observability.py -v`
Expected: FAIL — classifier missing `data_gate`/`answer_validate` mapping and `_validate_partial_answer` lacks the catalog call.

- [ ] **Step 3: Write minimal implementation**

In `app/services/trace_persistence_service.py`, extend the step→type map (near line 56) with:

```python
    "data_gate": "validation",
    "answer_validate": "validation",
    "answer": "validation",
    "validate": "validation",
    "validate_tables": "validation",
```

(Keep existing entries; `classify_span_type` already consults this map then falls back heuristically.)

In `app/agents/orchestrator.py` `_validate_partial_answer`, when the result indicates the answer does not address the question (fail-closed), catalog it (guarded, best-effort) before returning:

```python
        if not addresses:  # the existing local that signals fail-closed
            try:
                from app.models.base import async_session_factory
                from app.services.error_log_service import ErrorLogService

                async with async_session_factory() as db:
                    await ErrorLogService().upsert_validation_failure(
                        db, project_id=self._project_id, kind="answer",
                        message="answer did not address the question (fail-closed)",
                        sample_ref=workflow_id_var.get())
            except Exception:  # noqa: BLE001
                logger.debug("answer validation error_log upsert failed", exc_info=True)
```

> Use the orchestrator's existing project-id attribute and the `workflow_id_var` already imported from `app.core.workflow_tracker` (or pass the current wf id in scope). Match the actual local variable name that represents the fail-closed verdict in `_validate_partial_answer`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/pytest tests/unit/services/test_span_type_coverage.py tests/unit/agents/test_answer_validation_observability.py -v`
Expected: PASS.

- [ ] **Step 5: Full P4 suite, lint, type-check, commit**

```bash
cd backend && .venv/bin/ruff format app/ tests/ && .venv/bin/ruff check app/ tests/ && .venv/bin/mypy app/ --ignore-missing-imports
.venv/bin/pytest tests/unit/services/test_error_log_validation.py tests/unit/agents/test_data_gate_observability.py tests/unit/services/test_span_type_coverage.py tests/unit/agents/test_answer_validation_observability.py -v
git add -A
git commit -m "feat(observability): answer-validation fail-close cataloged; span-type map

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage (§6 capability → guarantee):** build queries (`db_query` spans — existing) + work with data (DataGate verdict typed + cataloged, Task 2) + validate data (Task 2/3) + answer (Task 3) + handle errors (failures → error_log via P1/P3 + this milestone) + search data (`rag`/`tool_call` spans — existing, classifier pinned in Task 3) + converse (session events — existing trace meta). ✓

**Placeholder scan:** Tasks 2–3 give the exact added blocks; the two "confirm the actual local/class name" notes are instructions to match an existing identifier (not undefined types) — the implementer greps once and uses the real name. No `TBD`. ✓

**Type consistency:** `upsert_validation_failure(db, *, project_id, kind, message, sample_ref=None, meta=None)` consistent between Task 1 definition and Tasks 2–3 calls; `classify_span_type` keys match the parametrized test. ✓

**Risk flagged:** the source-level assertions (Tasks 2–3) verify wiring without booting the orchestrator; pair them with the existing end-to-end trace integration tests when running the full suite to confirm the spans actually persist.

---

## Execution Handoff

P4 complete. Depends on P0/P1/P3. **Next:** P5 (frontend) — the last milestone: unified runs store, Overview rich panel, global pill, Logs/Observability screen (Queries/Runs/Errors tabs + filters), and the deterministic default view.
