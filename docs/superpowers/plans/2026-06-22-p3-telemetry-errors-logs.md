# P3 — Telemetry, Error Catalog & Filterable Logs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist failures from **both** planes into the dedup'd `error_log` catalog, expose filterable logs/errors/run-history APIs, emit run SLI metrics, and add retention sweeps — so every query, run, and error is in the database, queryable with filters, and instrumented against the SLOs.

**Architecture:** The chat `TracePersistenceService` upserts failed traces into `error_log` (source `query`); the P1 `RunCoordinator` already upserts failed runs (source `run`). `LogsService` gains filterable `list_errors` + status update; new routes expose errors, run history, and the existing `/runs/{id}/events` journal (from P1). `RunCoordinator` emits run counters + duration + time-to-first-progress into the existing `MetricsCollector`. A maintenance sweep enforces `indexing_run_events` and `error_log` retention.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 async, pytest (asyncio auto).

**Source spec:** `…/2026-06-22-sync-and-observability-redesign-design.md` (§5.1 error_log, §5.5 logs/errors/runs endpoints, §5.6 SLO metrics, §8 logging coverage & filters). **Depends on:** P0 (`ErrorLog`, `ErrorLogService`, `IndexingRun*`), P1 (`RunCoordinator`, `/runs` router).

## Global Constraints

- **Greenfield — no backward compatibility.**
- Locked interfaces consumed: `ErrorLogService.upsert(db, *, project_id, source, kind, message, failure_kind=None, sample_ref=None, meta=None)`; `IndexingRun`, `IndexingRunEvent`, `ErrorLog`; metrics accessor `from app.core.metrics import get_metrics_collector` with `.inc(name, amount=1, **labels)` and `.add(name, value, **labels)`; maintenance loop `_maintenance_loop` in `app/main.py:133`.
- New settings → `app/config.py` + `backend/.env.example`.
- Python 3.12, line length 100, ruff `0.15.15`, mypy clean, async-only, coverage ≥ 72%.
- Conventional commits ending with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- Run commands from `backend/` via `.venv/bin/<tool>`.

## File Structure

- Modify `app/services/error_log_service.py` — add `upsert_from_trace(db, trace)`.
- Modify `app/services/trace_persistence_service.py` — upsert failed traces into `error_log` (`finalize_trace` ~line 190 and the `_persist_workflow` failed path).
- Modify `app/services/logs_service.py` — `list_errors(...)`, `update_error_status(...)`, `list_runs(...)`.
- Modify `app/api/routes/logs.py` — `GET /{project}/errors`, `PATCH /{project}/errors/{id}`, `GET /{project}/runs`.
- Modify `app/api/routes/projects.py` — `GET /{project_id}/runs` (history list, mirrors logs).
- Modify `app/services/run_coordinator.py` — emit metrics in `finish` + time-to-first-progress in `_apply_event`/`step`.
- Modify `app/api/routes/metrics.py` — surface run counters + `error_log` open gauge.
- Create `app/services/telemetry_retention.py` — sweep; Modify `app/main.py` maintenance loop + `app/config.py`.
- Tests under `tests/unit/services/`, `tests/unit/api/`.

Reuse the P0 in-memory `session` fixture.

---

### Task 1: Error catalog from the query plane

**Files:**
- Modify: `app/services/error_log_service.py`
- Modify: `app/services/trace_persistence_service.py`
- Test: `tests/unit/services/test_error_log_from_trace.py`

**Interfaces:**
- Produces: `ErrorLogService.upsert_from_trace(db, trace: RequestTrace) -> ErrorLog` — `source="query"`, `kind="chat"`, `message=trace.error_message`, `failure_kind=trace.failure_kind`, `sample_ref=trace.id`, `meta={"user_id": trace.user_id, "workflow_id": trace.workflow_id}`.
- `TracePersistenceService` upserts when a trace is persisted with `status == "failed"`.

- [ ] **Step 1: Write the failing test**

`tests/unit/services/test_error_log_from_trace.py`:

```python
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
import app.models  # noqa: F401
from app.models.error_log import ErrorLog
from app.models.request_trace import RequestTrace
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


async def test_upsert_from_failed_trace(session: AsyncSession):
    tr = RequestTrace(id="t1", project_id="p", user_id="u", workflow_id="w",
                      question="q", status="failed", error_message="timeout after 30s",
                      failure_kind="transient")
    session.add(tr)
    await session.commit()

    await ErrorLogService().upsert_from_trace(session, tr)
    rows = (await session.execute(select(ErrorLog).where(ErrorLog.project_id == "p"))).scalars().all()
    assert len(rows) == 1
    assert rows[0].source == "query"
    assert rows[0].sample_ref == "t1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/unit/services/test_error_log_from_trace.py -v`
Expected: FAIL — `AttributeError: 'ErrorLogService' object has no attribute 'upsert_from_trace'`.

- [ ] **Step 3: Write minimal implementation**

Add to `app/services/error_log_service.py` (import `RequestTrace`):

```python
from app.models.request_trace import RequestTrace
```

```python
    async def upsert_from_trace(self, db: AsyncSession, trace: RequestTrace) -> ErrorLog:
        return await self.upsert(
            db,
            project_id=trace.project_id,
            source="query",
            kind="chat",
            message=trace.error_message,
            failure_kind=getattr(trace, "failure_kind", None),
            sample_ref=trace.id,
            meta={"user_id": trace.user_id, "workflow_id": trace.workflow_id},
        )
```

In `app/services/trace_persistence_service.py`, after a trace is persisted with a failed status (inside `finalize_trace` where `trace` is committed, and in `_persist_workflow` on the failed path), call the upsert. Add near the top:

```python
from app.services.error_log_service import ErrorLogService
```

and after the failed-trace commit:

```python
                if status == "failed":
                    try:
                        await ErrorLogService().upsert_from_trace(session, trace)
                    except Exception:
                        logger.debug("error_log upsert from trace failed", exc_info=True)
```

> Apply the same guarded upsert in `_persist_workflow` wherever it sets `status="failed"` on the `RequestTrace` before commit. Keep it fire-and-forget (swallow errors) to match the service's non-blocking contract.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/unit/services/test_error_log_from_trace.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd backend && .venv/bin/ruff check app/ && .venv/bin/mypy app/ --ignore-missing-imports
git add backend/app/services/error_log_service.py backend/app/services/trace_persistence_service.py backend/tests/unit/services/test_error_log_from_trace.py
git commit -m "feat(telemetry): query-plane failures upsert into error_log catalog

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Filterable errors + run-history API

**Files:**
- Modify: `app/services/logs_service.py`
- Modify: `app/api/routes/logs.py`
- Modify: `app/api/routes/projects.py`
- Test: `tests/unit/services/test_logs_errors_runs.py`

**Interfaces:**
- `LogsService.list_errors(db, project_id, *, source=None, kind=None, failure_kind=None, status=None, date_from=None, date_to=None, page=1, page_size=50) -> {items, total, page, page_size}`.
- `LogsService.update_error_status(db, project_id, error_id, status) -> bool` (status ∈ `open|acknowledged|resolved`).
- `LogsService.list_runs(db, project_id, *, kind=None, status=None, limit=50) -> list[dict]`.
- Routes: `GET /logs/{project}/errors`, `PATCH /logs/{project}/errors/{id}` (owner), `GET /logs/{project}/runs` (owner); `GET /projects/{project_id}/runs` (viewer).

- [ ] **Step 1: Write the failing test**

`tests/unit/services/test_logs_errors_runs.py`:

```python
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
import app.models  # noqa: F401
from app.services.error_log_service import ErrorLogService
from app.services.logs_service import LogsService
from app.services.run_coordinator import RunCoordinator


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


async def test_list_and_update_errors(session: AsyncSession):
    svc = ErrorLogService()
    e = await svc.upsert(session, project_id="p", source="run", kind="db_index",
                         message="boom", failure_kind="fatal")
    logs = LogsService()
    res = await logs.list_errors(session, "p", source="run")
    assert res["total"] == 1 and res["items"][0]["kind"] == "db_index"
    ok = await logs.update_error_status(session, "p", e.id, "resolved")
    assert ok is True
    res2 = await logs.list_errors(session, "p", status="resolved")
    assert res2["total"] == 1


async def test_list_runs(session: AsyncSession):
    coord = RunCoordinator()
    run = await coord.start(session, kind="db_index", project_id="p", connection_id="c")
    await coord.finish(run, "completed")
    rows = await LogsService().list_runs(session, "p", kind="db_index")
    assert len(rows) == 1 and rows[0]["status"] == "completed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/unit/services/test_logs_errors_runs.py -v`
Expected: FAIL — `AttributeError: 'LogsService' object has no attribute 'list_errors'`.

- [ ] **Step 3: Write minimal implementation**

Add to `app/services/logs_service.py` (imports `ErrorLog`, `IndexingRun`, `select`, `func`):

```python
    async def list_errors(self, db, project_id, *, source=None, kind=None, failure_kind=None,
                          status=None, date_from=None, date_to=None, page=1, page_size=50):
        from app.models.error_log import ErrorLog

        base = select(ErrorLog).where(ErrorLog.project_id == project_id)
        cnt = select(func.count(ErrorLog.id)).where(ErrorLog.project_id == project_id)
        for col, val in (("source", source), ("kind", kind),
                         ("failure_kind", failure_kind), ("status", status)):
            if val:
                base = base.where(getattr(ErrorLog, col) == val)
                cnt = cnt.where(getattr(ErrorLog, col) == val)
        if date_from:
            base = base.where(ErrorLog.last_seen_at >= date_from)
            cnt = cnt.where(ErrorLog.last_seen_at >= date_from)
        if date_to:
            base = base.where(ErrorLog.last_seen_at <= date_to)
            cnt = cnt.where(ErrorLog.last_seen_at <= date_to)
        total = (await db.execute(cnt)).scalar_one()
        rows = (await db.execute(
            base.order_by(ErrorLog.last_seen_at.desc()).offset((page - 1) * page_size).limit(page_size)
        )).scalars().all()
        return {
            "items": [
                {"id": r.id, "source": r.source, "kind": r.kind, "failure_kind": r.failure_kind,
                 "message": r.message, "occurrences": r.occurrences, "status": r.status,
                 "sample_ref": r.sample_ref,
                 "first_seen_at": r.first_seen_at.isoformat() if r.first_seen_at else None,
                 "last_seen_at": r.last_seen_at.isoformat() if r.last_seen_at else None}
                for r in rows
            ],
            "total": total, "page": page, "page_size": page_size,
        }

    async def update_error_status(self, db, project_id, error_id, status):
        from app.models.error_log import ErrorLog

        e = await db.get(ErrorLog, error_id)
        if e is None or e.project_id != project_id or status not in ("open", "acknowledged", "resolved"):
            return False
        e.status = status
        await db.commit()
        return True

    async def list_runs(self, db, project_id, *, kind=None, status=None, limit=50):
        from app.models.indexing_run import IndexingRun

        stmt = select(IndexingRun).where(IndexingRun.project_id == project_id)
        if kind:
            stmt = stmt.where(IndexingRun.kind == kind)
        if status:
            stmt = stmt.where(IndexingRun.status == status)
        rows = (await db.execute(
            stmt.order_by(IndexingRun.created_at.desc()).limit(limit)
        )).scalars().all()
        return [
            {"id": r.id, "kind": r.kind, "status": r.status, "trigger": r.trigger,
             "progress_pct": r.progress_pct, "connection_id": r.connection_id,
             "error": r.error, "failure_kind": r.failure_kind,
             "started_at": r.started_at.isoformat() if r.started_at else None,
             "finished_at": r.finished_at.isoformat() if r.finished_at else None}
            for r in rows
        ]
```

Add routes to `app/api/routes/logs.py` (owner-only, mirroring the existing date parsing in `list_log_requests`):

```python
@router.get("/{project_id}/errors")
@limiter.limit("30/minute")
async def list_errors(request: Request, project_id: str, source: str | None = Query(None),
                      kind: str | None = Query(None), failure_kind: str | None = Query(None),
                      status: str | None = Query(None), date_from: str | None = Query(None),
                      date_to: str | None = Query(None), page: int = Query(1, ge=1),
                      page_size: int = Query(50, ge=1, le=200),
                      db: AsyncSession = Depends(get_db), user: dict = Depends(get_current_user)):
    await _membership_svc.require_role(db, project_id, user["user_id"], "owner")
    return await _logs_svc.list_errors(db, project_id, source=source, kind=kind,
                                       failure_kind=failure_kind, status=status,
                                       date_from=_parse_dt(date_from), date_to=_parse_dt(date_to),
                                       page=page, page_size=page_size)


class _ErrorStatusBody(BaseModel):
    status: str


@router.patch("/{project_id}/errors/{error_id}")
@limiter.limit("30/minute")
async def update_error(request: Request, project_id: str, error_id: str, body: _ErrorStatusBody,
                       db: AsyncSession = Depends(get_db), user: dict = Depends(get_current_user)):
    await _membership_svc.require_role(db, project_id, user["user_id"], "owner")
    ok = await _logs_svc.update_error_status(db, project_id, error_id, body.status)
    if not ok:
        raise HTTPException(status_code=400, detail="Invalid error id or status")
    return {"ok": True}


@router.get("/{project_id}/runs")
@limiter.limit("30/minute")
async def list_runs(request: Request, project_id: str, kind: str | None = Query(None),
                    status: str | None = Query(None), limit: int = Query(50, ge=1, le=200),
                    db: AsyncSession = Depends(get_db), user: dict = Depends(get_current_user)):
    await _membership_svc.require_role(db, project_id, user["user_id"], "owner")
    return await _logs_svc.list_runs(db, project_id, kind=kind, status=status, limit=limit)
```

Add `from pydantic import BaseModel` and a small `_parse_dt` helper to `logs.py` (reuse the ISO parse already in `list_log_requests`):

```python
def _parse_dt(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=UTC)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid date format") from exc
```

Add `GET /projects/{project_id}/runs` (viewer) to `app/api/routes/projects.py` delegating to `LogsService.list_runs`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/unit/services/test_logs_errors_runs.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd backend && .venv/bin/ruff check app/ && .venv/bin/mypy app/ --ignore-missing-imports
git add backend/app/services/logs_service.py backend/app/api/routes/logs.py backend/app/api/routes/projects.py backend/tests/unit/services/test_logs_errors_runs.py
git commit -m "feat(logs): filterable errors catalog + run-history endpoints

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Run SLI metrics

**Files:**
- Modify: `app/services/run_coordinator.py` (`finish`, first-step in `_apply_event`/`step`)
- Modify: `app/api/routes/metrics.py` (surface run counters + open-error gauge)
- Test: `tests/unit/services/test_run_metrics.py`

**Interfaces:**
- On run terminal: `metrics.inc("indexing_runs_total", kind=run.kind, status=run.status)` and `metrics.add("indexing_run_duration_seconds", duration, kind=run.kind)`.
- On the first manifest step completing (`step_index` 0→1): `metrics.add("indexing_run_time_to_first_progress_seconds", delta, kind=run.kind)`.
- `/api/metrics` JSON includes a `runs` block from `snapshot_counters(prefix="indexing_runs_")`.

- [ ] **Step 1: Write the failing test**

`tests/unit/services/test_run_metrics.py`:

```python
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.metrics import get_metrics_collector
from app.models.base import Base
import app.models  # noqa: F401
from app.services.run_coordinator import RunCoordinator


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


async def test_finish_emits_run_counter(session: AsyncSession):
    coord = RunCoordinator()
    run = await coord.start(session, kind="db_index", project_id="p", connection_id="c")
    await coord.finish(run, "completed")
    counters = get_metrics_collector().snapshot_counters(prefix="indexing_runs_total")
    assert any(v >= 1 for v in counters.values())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/unit/services/test_run_metrics.py -v`
Expected: FAIL — no `indexing_runs_total` counter recorded.

- [ ] **Step 3: Write minimal implementation**

In `app/services/run_coordinator.py`, import the collector:

```python
from app.core.metrics import get_metrics_collector
```

In `finish`, after the terminal commit:

```python
        try:
            mc = get_metrics_collector()
            mc.inc("indexing_runs_total", kind=run.kind, status=status)
            if run.started_at and run.finished_at:
                mc.add("indexing_run_duration_seconds",
                       (run.finished_at - run.started_at).total_seconds(), kind=run.kind)
        except Exception:  # noqa: BLE001
            logger.debug("run metrics emit failed", exc_info=True)
```

In `_apply_event` (and the explicit `step`), when a step transitions the run from `step_index == 0` to `1` on `started`, record time-to-first-progress. In the `started` branch, before setting `run.step_index = position`:

```python
            if run.step_index == 0 and run.started_at is not None:
                try:
                    get_metrics_collector().add(
                        "indexing_run_time_to_first_progress_seconds",
                        (_now() - run.started_at).total_seconds(), kind=run.kind)
                except Exception:  # noqa: BLE001
                    logger.debug("ttfp metric failed", exc_info=True)
```

In `app/api/routes/metrics.py`, add a `runs` block to the JSON payload:

```python
    run_counters = collector.snapshot_counters(prefix="indexing_runs_")
```
and include `"runs": run_counters` in the returned dict.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/unit/services/test_run_metrics.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd backend && .venv/bin/ruff check app/ && .venv/bin/mypy app/ --ignore-missing-imports
git add backend/app/services/run_coordinator.py backend/app/api/routes/metrics.py backend/tests/unit/services/test_run_metrics.py
git commit -m "feat(metrics): run counters, duration, and time-to-first-progress SLIs

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Telemetry retention sweep

**Files:**
- Create: `app/services/telemetry_retention.py`
- Modify: `app/config.py` (+ `backend/.env.example`)
- Modify: `app/main.py` (maintenance loop)
- Test: `tests/unit/services/test_telemetry_retention.py`

**Interfaces:**
- Settings: `indexing_run_events_ttl_days: int = 30`, `indexing_run_events_max_per_run: int = 500`, `error_log_ttl_days: int = 90`.
- `TelemetryRetention.sweep(db) -> dict[str, int]` deletes `IndexingRunEvent` rows older than the TTL and trims each run's events to the most-recent N; deletes `ErrorLog` rows whose `last_seen_at` is older than the error TTL. Returns counts.
- Called once per maintenance cycle from `_maintenance_loop`.

- [ ] **Step 1: Write the failing test**

`tests/unit/services/test_telemetry_retention.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
import app.models  # noqa: F401
from app.models.indexing_run import IndexingRun, IndexingRunEvent
from app.services.telemetry_retention import TelemetryRetention


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


async def test_sweep_deletes_old_events(session: AsyncSession):
    run = IndexingRun(workflow_id="w", project_id="p", connection_id=None,
                      kind="db_index", trigger="manual", status="completed")
    session.add(run)
    await session.commit()
    old = datetime.now(UTC) - timedelta(days=100)
    session.add(IndexingRunEvent(run_id=run.id, step="x", status="completed", ts=old))
    await session.commit()

    out = await TelemetryRetention().sweep(session, ttl_days=30, max_per_run=500, error_ttl_days=90)
    await session.commit()
    remaining = (await session.execute(
        select(IndexingRunEvent).where(IndexingRunEvent.run_id == run.id)
    )).scalars().all()
    assert remaining == []
    assert out["events_deleted"] >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/unit/services/test_telemetry_retention.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.telemetry_retention'`.

- [ ] **Step 3: Write minimal implementation**

`app/services/telemetry_retention.py`:

```python
"""Retention sweeps for run-event journal and error catalog."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.error_log import ErrorLog
from app.models.indexing_run import IndexingRunEvent

logger = logging.getLogger(__name__)


class TelemetryRetention:
    async def sweep(self, db: AsyncSession, *, ttl_days: int, max_per_run: int,
                    error_ttl_days: int) -> dict[str, int]:
        ev_cutoff = datetime.now(UTC) - timedelta(days=ttl_days)
        ev_res = await db.execute(delete(IndexingRunEvent).where(IndexingRunEvent.ts < ev_cutoff))
        # Per-run cap: for each run with > max_per_run events, delete the oldest overflow.
        run_ids = (await db.execute(select(IndexingRunEvent.run_id).distinct())).scalars().all()
        capped = 0
        for run_id in run_ids:
            rows = (await db.execute(
                select(IndexingRunEvent.id).where(IndexingRunEvent.run_id == run_id)
                .order_by(IndexingRunEvent.ts.desc())
            )).scalars().all()
            overflow = rows[max_per_run:]
            if overflow:
                await db.execute(delete(IndexingRunEvent).where(IndexingRunEvent.id.in_(overflow)))
                capped += len(overflow)
        err_cutoff = datetime.now(UTC) - timedelta(days=error_ttl_days)
        err_res = await db.execute(delete(ErrorLog).where(ErrorLog.last_seen_at < err_cutoff))
        await db.flush()
        out = {
            "events_deleted": max(0, int(ev_res.rowcount or 0)) + capped,
            "errors_deleted": max(0, int(err_res.rowcount or 0)),
        }
        if any(out.values()):
            logger.info("Telemetry retention: events=%d errors=%d",
                        out["events_deleted"], out["errors_deleted"])
        return out
```

Add settings to `app/config.py` (with docstrings) and `backend/.env.example`:

```python
    indexing_run_events_ttl_days: int = 30
    indexing_run_events_max_per_run: int = 500
    error_log_ttl_days: int = 90
```

In `app/main.py` maintenance loop (`_maintenance_loop` body, alongside `_periodic_insight_maintenance`), add a sweep call:

```python
async def _sweep_telemetry_retention() -> None:
    from app.services.telemetry_retention import TelemetryRetention

    try:
        async with async_session_factory() as session:
            await TelemetryRetention().sweep(
                session,
                ttl_days=settings.indexing_run_events_ttl_days,
                max_per_run=settings.indexing_run_events_max_per_run,
                error_ttl_days=settings.error_log_ttl_days,
            )
            await session.commit()
    except Exception:
        logger.warning("Telemetry retention sweep failed", exc_info=True)
```

and call `await _sweep_telemetry_retention()` inside the maintenance loop iteration (next to the other periodic maintenance calls).

- [ ] **Step 4: Run test + full P3 suite**

Run:
```bash
cd backend && .venv/bin/pytest tests/unit/services/test_error_log_from_trace.py tests/unit/services/test_logs_errors_runs.py tests/unit/services/test_run_metrics.py tests/unit/services/test_telemetry_retention.py -v
.venv/bin/ruff format app/ tests/ && .venv/bin/ruff check app/ tests/ && .venv/bin/mypy app/ --ignore-missing-imports
```
Expected: PASS; clean lint/types.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(telemetry): retention sweep for run events and error catalog

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:** error_log from both planes (§5.1, §8) → P1 (run) + Task 1 (query); filterable errors + run history (§5.5) → Task 2; SLO metrics (§5.6) → Task 3; retention/TTL (§5.1 caps, §8) → Task 4; `/runs/{id}/events` journal already in P1. ✓

**Placeholder scan:** Task 1 Step 3 names the exact insertion points (`finalize_trace` failed commit + `_persist_workflow` failed path) and shows the guarded upsert; no `TBD`/"handle errors". ✓

**Type consistency:** `ErrorLogService.upsert(...)` signature reused by `upsert_from_trace` matches P0; `LogsService.list_errors/update_error_status/list_runs` names consistent between service, routes, and tests; metric names (`indexing_runs_total`, `indexing_run_duration_seconds`, `indexing_run_time_to_first_progress_seconds`) consistent between emit and `/metrics` prefix scan. ✓

**Risk flagged:** Task 3 time-to-first-progress is emitted from `_apply_event` (hook path) — for in-process runs that also call the explicit `step()` (daily_sync composite), ensure the 0→1 guard fires once; the `step_index == 0` check makes it idempotent per run.

---

## Execution Handoff

P3 complete. Depends on P0 + P1 (P2 independent of P3). **Next:** P4 (agent-lifecycle observability hardening), P5 (frontend: runs store, overview panel, pill, logs/errors screen, default view).
