# P1 — Run Lifecycle Wiring — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every repo-index / db-index / code-DB-sync trigger create a persisted `IndexingRun`, stream first-class progress, and become the single source of truth for status, cancel, retry, and stuck-run recovery — in both in-process and ARQ modes.

**Architecture:** Triggers call `RunCoordinator.start()` (P0) to create the run and mint `workflow_id`, return `{run_id, workflow_id}` in the 202, and pass `wf_id` into the pipeline so it reuses it instead of beginning its own. A single `tracker` **persistence hook** maps every workflow event for a known run into the `IndexingRun` projection + `IndexingRunEvent` journal + progress (via the P0 step manifest). `pipeline-status` / `tasks/active` are rebuilt on `indexing_runs`. Cancel/retry endpoints and the reaper operate on `indexing_runs`.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 async, ARQ, pytest (asyncio auto).

**Source spec:** `docs/superpowers/specs/2026-06-22-sync-and-observability-redesign-design.md` (§4, §5.4, §5.5). **Depends on:** P0 (`docs/superpowers/plans/2026-06-22-p0-run-lifecycle-contracts.md`) — its contracts are locked.

## Global Constraints

- **Greenfield — no backward compatibility.** Remove the legacy `{"status":"started"}` 202 bodies; the new bodies are `{"status","run_id","workflow_id","connection_id"?}`.
- Locked P0 interfaces (consumed verbatim):
  - `RunCoordinator.start(db, *, kind, project_id, connection_id=None, trigger="manual", force_full=False) -> IndexingRun`
  - `RunCoordinator.finish(run, status, error=None, failure_kind=None)`
  - `RunCoordinator.request_cancel(db, run_id) -> bool`
  - `RunCoordinator.retry(db, run_id, *, force_full) -> IndexingRun`
  - `RunAlreadyActive(.run_id)`, `RunCancelled`
  - `IndexingRun`, `IndexingRunEvent`, `ErrorLog` models; manifests `resolve_manifest/step_position/progress_for/total_steps`.
- `tracker.add_persistence_hook(cb)` exists (`core/workflow_tracker.py:103`) and is awaited on every broadcast (`_deliver_local`). The chat `TracePersistenceService` is already a hook; ours is additive.
- The pipelines own their `wf_id` today: `pipeline_runner.run(...)` already **accepts** `wf_id` (`knowledge/pipeline_runner.py:127`); `DbIndexPipeline.run` and `CodeDbSyncPipeline.run` **begin their own** (`db_index_pipeline.py:279`, `code_db_sync_pipeline.py:59`) and must accept an optional `wf_id`.
- Python 3.12, line length 100, ruff `0.15.15` (`E F I N W UP`), mypy clean, async-only, coverage ≥ 72%.
- Conventional commits ending with: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- Run commands from `backend/` via `.venv/bin/<tool>`.

## File Structure

- Modify `app/services/run_coordinator.py` — add the persistence hook (`attach`, `_on_event`, `_apply_event`) sharing P0's projection logic.
- Modify `app/main.py` (lifespan startup ~line 123) and `app/worker.py` (`startup` ~line 243) — register the hook.
- Modify `app/api/routes/connections.py` — rewire `index_database`, `trigger_sync`, the `_dispatch_*` helpers, and the `_run_*_background` runners to thread `wf_id`; add cancel/retry routes.
- Modify `app/knowledge/db_index_pipeline.py`, `app/knowledge/code_db_sync_pipeline.py` — `run(..., wf_id: str | None = None)`.
- Modify `app/api/routes/repos.py` — `_spawn_repo_index` via `RunCoordinator.start`; ARQ branch returns real `run_id`/`workflow_id`.
- Modify `app/worker.py` — `run_db_index`/`run_code_db_sync`/`run_repo_index` accept + thread `wf_id`.
- Modify `app/services/pipeline_status_service.py` — rebuild on `indexing_runs`.
- Modify `app/api/routes/tasks.py` — `tasks/active` from `indexing_runs`.
- Modify `app/services/stale_run_reaper.py` — flip stale `indexing_runs`.
- Modify `app/core/workflow_events.py` — tolerant `WorkflowEvent` reconstruction.
- Add `app/api/routes/runs.py` (cancel/retry/detail/events) + register in `app/main.py`.
- Tests under `tests/unit/services/`, `tests/unit/api/`, `tests/integration/`.

Reuse the in-memory `session` fixture from P0 (`tests/unit/test_insight_reconcile_tz.py` pattern).

---

### Task 1: RunCoordinator persistence hook (projection + journal + progress)

**Files:**
- Modify: `app/services/run_coordinator.py`
- Test: `tests/unit/services/test_run_coordinator_hook.py`

**Interfaces:**
- Produces: `RunCoordinator.attach()` — registers `self._on_event` via `tracker.add_persistence_hook`; idempotent.
- Produces: `RunCoordinator._on_event(event: WorkflowEvent) -> None` — opens its own session, finds the `IndexingRun` by `event.workflow_id` (cache miss → DB lookup; non-run workflows ignored), then `_apply_event`.
- Produces: `RunCoordinator._apply_event(db, run, event)` — `pipeline_start`→no-op (start() already wrote it); manifest step `started`→set `current_step`/`step_index`/heartbeat + journal; `completed`→set `progress_pct` + journal; `pipeline_end`→terminal (`finish`-equivalent) + `ErrorLog` upsert on failure; unknown steps→journal at `info` only.

- [ ] **Step 1: Write the failing test**

`tests/unit/services/test_run_coordinator_hook.py`:

```python
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.workflow_tracker import WorkflowEvent
from app.models.base import Base
import app.models  # noqa: F401
from app.models.error_log import ErrorLog
from app.models.indexing_run import IndexingRun, IndexingRunEvent
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


async def test_hook_applies_step_progress_and_terminal(session: AsyncSession):
    coord = RunCoordinator()
    run = await coord.start(session, kind="db_index", project_id="p", connection_id="c")
    wf = run.workflow_id

    # Drive the projection purely through events (as the hook would receive them).
    await coord._apply_event(session, run, WorkflowEvent(
        workflow_id=wf, step="introspect_schema", status="started", pipeline="db_index"))
    await coord._apply_event(session, run, WorkflowEvent(
        workflow_id=wf, step="introspect_schema", status="completed", pipeline="db_index"))
    await session.refresh(run)
    assert run.current_step == "introspect_schema"
    assert run.step_index == 1
    assert run.progress_pct == round(1 / 6 * 100)

    await coord._apply_event(session, run, WorkflowEvent(
        workflow_id=wf, step="pipeline_end", status="failed", detail="kaboom 7",
        pipeline="db_index"))
    await session.refresh(run)
    assert run.status == "failed"
    assert run.finished_at is not None

    errs = (await session.execute(select(ErrorLog).where(ErrorLog.project_id == "p"))).scalars().all()
    assert len(errs) == 1 and errs[0].source == "run"

    events = (await session.execute(
        select(IndexingRunEvent).where(IndexingRunEvent.run_id == run.id)
    )).scalars().all()
    assert any(e.step == "pipeline_end" for e in events)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/unit/services/test_run_coordinator_hook.py -v`
Expected: FAIL — `AttributeError: 'RunCoordinator' object has no attribute '_apply_event'`.

- [ ] **Step 3: Write minimal implementation**

In `app/services/run_coordinator.py` add imports and methods. At top add:

```python
from app.core.workflow_tracker import WorkflowEvent, tracker
from app.models.base import async_session_factory
```

Add a module-level cache and these methods to `RunCoordinator`:

```python
    _attached = False
    _wf_to_run: dict[str, str] = {}

    def attach(self) -> None:
        """Register the run-projection persistence hook (idempotent)."""
        if RunCoordinator._attached:
            return
        tracker.add_persistence_hook(self._on_event)
        RunCoordinator._attached = True

    async def _on_event(self, event: WorkflowEvent) -> None:
        run_id = RunCoordinator._wf_to_run.get(event.workflow_id)
        async with async_session_factory() as db:
            run = None
            if run_id is not None:
                run = await db.get(IndexingRun, run_id)
            if run is None:
                stmt = select(IndexingRun).where(IndexingRun.workflow_id == event.workflow_id)
                run = (await db.execute(stmt)).scalar_one_or_none()
            if run is None or run.status in ("completed", "failed", "cancelled"):
                return
            RunCoordinator._wf_to_run[event.workflow_id] = run.id
            await self._apply_event(db, run, event)

    async def _apply_event(self, db: AsyncSession, run: IndexingRun, event: WorkflowEvent) -> None:
        manifest = self._manifests.get(run.id) or resolve_manifest(
            run.kind, flags=_manifest_flags()
        )
        if event.step == "pipeline_start":
            return
        if event.step == "pipeline_end":
            terminal = "cancelled" if run.cancel_requested else (
                "failed" if event.status == "failed" else "completed"
            )
            run.status = terminal
            run.finished_at = _now()
            run.heartbeat_at = _now()
            run.version += 1
            if terminal == "completed":
                run.progress_pct = 100
            elif event.detail:
                run.error = event.detail
            await db.commit()
            await self._journal(db, run, event.step, terminal, event.detail or "")
            if terminal == "failed":
                await self._error_log.upsert_from_run(db, run)
            RunCoordinator._wf_to_run.pop(run.workflow_id, None)
            self._manifests.pop(run.id, None)
            return
        # A manifest step (or a free-form detail emit).
        try:
            position = step_position(manifest, event.step)
        except KeyError:
            await self._journal(db, run, event.step, event.status, event.detail or "")
            return
        if event.status == "started":
            run.current_step = event.step
            run.step_index = position
            run.heartbeat_at = _now()
            await db.commit()
            await self._journal(db, run, event.step, "started", event.detail or "")
        elif event.status in ("completed", "skipped"):
            run.progress_pct = progress_for(manifest, position)
            run.heartbeat_at = _now()
            run.version += 1
            await db.commit()
            await self._journal(db, run, event.step, event.status, event.detail or "",
                                elapsed_ms=event.elapsed_ms)
        elif event.status == "failed":
            await self._journal(db, run, event.step, "failed", event.detail or "",
                                elapsed_ms=event.elapsed_ms, level="error")

    async def _journal(
        self, db: AsyncSession, run: IndexingRun, step: str, status: str, detail: str = "",
        *, elapsed_ms: float | None = None, level: str = "info",
    ) -> None:
        db.add(IndexingRunEvent(
            run_id=run.id, step=step, status=status, detail=detail,
            elapsed_ms=elapsed_ms, progress_pct=run.progress_pct, level=level,
        ))
        await db.commit()
```

Also register the workflow→run mapping inside `start()` (after `await db.refresh(run)`):

```python
        RunCoordinator._wf_to_run[run.workflow_id] = run.id
```

> Note: `start()` from P0 calls `self._record(...)` which both journals **and** emits a `pipeline_start` SSE event. With the hook attached in production, the hook's `pipeline_start` is a no-op (handled above), so there is no double-write. The unit tests above call `_apply_event` directly and do not attach the hook, so they exercise the projection logic in isolation.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/unit/services/test_run_coordinator_hook.py -v`
Expected: PASS.

- [ ] **Step 5: Register the hook at startup, then commit**

In `app/main.py` lifespan, next to `start_workflow_event_subscriber()` (~line 123):

```python
    from app.services.run_coordinator import RunCoordinator

    RunCoordinator().attach()
```

In `app/worker.py` `startup` after `tracker.enable_cross_process_publish()` (~line 243):

```python
    from app.services.run_coordinator import RunCoordinator

    RunCoordinator().attach()
```

```bash
cd backend && .venv/bin/ruff check app/ && .venv/bin/mypy app/ --ignore-missing-imports
git add backend/app/services/run_coordinator.py backend/app/main.py backend/app/worker.py backend/tests/unit/services/test_run_coordinator_hook.py
git commit -m "feat(runs): persistence hook maps workflow events to IndexingRun projection

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Rewire DB-index trigger through RunCoordinator

**Files:**
- Modify: `app/api/routes/connections.py` (`index_database:621`, `_dispatch_db_index:59`, `_run_db_index_background:808`)
- Modify: `app/worker.py` (`run_db_index:28`)
- Modify: `app/knowledge/db_index_pipeline.py` (`run:269`, begin at `279`)
- Test: `tests/integration/test_db_index_run_lifecycle.py`

**Interfaces:**
- Consumes: `RunCoordinator.start`, `IndexingRun`.
- Produces: `index_database` returns `202 {status, run_id, workflow_id, connection_id}`. `_dispatch_db_index(connection_id, config, project_id, *, wf_id)` and `_run_db_index_background(connection_id, config, project_id, *, wf_id)` thread `wf_id`. `DbIndexPipeline.run(..., wf_id: str | None = None)` reuses it.

- [ ] **Step 1: Write the failing test**

`tests/integration/test_db_index_run_lifecycle.py`:

```python
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
import app.models  # noqa: F401
from app.models.indexing_run import IndexingRun
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


async def test_db_index_pipeline_accepts_external_wf_id(monkeypatch, session: AsyncSession):
    """DbIndexPipeline.run must reuse a provided wf_id instead of begin-ing its own."""
    from app.knowledge.db_index_pipeline import DbIndexPipeline

    begun: list[str] = []

    async def fake_begin(pipeline, ctx=None):
        begun.append("begin")
        return "should-not-be-used"

    monkeypatch.setattr("app.core.workflow_tracker.tracker.begin", fake_begin.__get__(None))
    pipe = DbIndexPipeline(db_index_batch_size=5)
    # run() will fail fast on a bad connection, but must NOT call tracker.begin
    # because we passed wf_id.
    from app.connectors.base import ConnectionConfig

    cfg = ConnectionConfig(db_type="postgres", db_host="127.0.0.1", db_port=1,
                           db_name="x", db_user="x", db_password="x")
    try:
        await pipe.run(connection_id="c", connection_config=cfg, project_id="p", wf_id="wf-ext")
    except Exception:
        pass
    assert begun == []  # begin was never called
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/integration/test_db_index_run_lifecycle.py -v`
Expected: FAIL — `TypeError: run() got an unexpected keyword argument 'wf_id'`.

- [ ] **Step 3: Write minimal implementation**

In `app/knowledge/db_index_pipeline.py`, change the `run` signature (line 269) to add `wf_id: str | None = None`, and the begin block (line 279) to reuse it:

```python
        wf_id = wf_id or await self._tracker.begin(
            "db_index",
            {"connection_id": connection_id, "project_id": project_id},
        )
```

In `app/api/routes/connections.py`, change `_dispatch_db_index` (line 59) to accept and forward `wf_id`:

```python
async def _dispatch_db_index(
    connection_id: str,
    config: ConnectionConfig,
    project_id: str,
    *,
    wf_id: str,
) -> None:
    if task_queue.is_arq_active():
        await task_queue.enqueue(
            "run_db_index",
            task_id=f"db_index:{connection_id}:{uuid.uuid4().hex[:8]}",
            connection_id=connection_id,
            project_id=project_id,
            wf_id=wf_id,
        )
        return
    task = asyncio.create_task(
        _run_db_index_background(connection_id, config, project_id, wf_id=wf_id)
    )
    task.add_done_callback(_log_task_error("DB index", connection_id))
    _db_index_tasks[connection_id] = task
```

Update `_run_db_index_background` (line 808) signature to `(..., *, wf_id: str)` and pass `wf_id=wf_id` into `pipeline.run(...)` (line 823).

Rewrite the `index_database` body (lines 638-669) so the run is created first and the wf_id threaded:

```python
    idx_start_lock = _db_index_start_locks.setdefault(connection_id, asyncio.Lock())
    async with idx_start_lock:
        existing = _db_index_tasks.get(connection_id)
        if existing and not existing.done():
            raise HTTPException(status_code=409, detail="Database indexing already in progress for this connection")

        from app.services.run_coordinator import RunAlreadyActive, RunCoordinator

        try:
            run = await RunCoordinator().start(
                db, kind="db_index", project_id=project_id, connection_id=connection_id,
                trigger="manual",
            )
        except RunAlreadyActive:
            raise HTTPException(status_code=409, detail="Database indexing already in progress for this connection")

        await _db_index_svc.set_indexing_status(db, connection_id, "running")
        await db.commit()
        await _dispatch_db_index(connection_id, config, project_id, wf_id=run.workflow_id)

    return JSONResponse(
        status_code=202,
        content={"status": "started", "run_id": run.id, "workflow_id": run.workflow_id,
                 "connection_id": connection_id},
    )
```

In `app/worker.py` `run_db_index` (line 28), add `wf_id: str` to the signature and pass `wf_id=wf_id` into `pipeline.run(...)` (line 56):

```python
async def run_db_index(ctx: dict, *, connection_id: str, project_id: str, wf_id: str) -> None:  # noqa: ARG001
    ...
        result = await pipeline.run(
            connection_id=connection_id, connection_config=config,
            project_id=project_id, wf_id=wf_id,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/integration/test_db_index_run_lifecycle.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd backend && .venv/bin/ruff check app/ && .venv/bin/mypy app/ --ignore-missing-imports
git add backend/app/api/routes/connections.py backend/app/worker.py backend/app/knowledge/db_index_pipeline.py backend/tests/integration/test_db_index_run_lifecycle.py
git commit -m "feat(runs): db-index trigger creates IndexingRun and threads wf_id

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Rewire code-DB sync trigger through RunCoordinator

**Files:**
- Modify: `app/api/routes/connections.py` (`trigger_sync:925`, `_dispatch_code_db_sync:92`, `_run_sync_background:1054`, `maybe_autostart_sync:172`)
- Modify: `app/worker.py` (`run_code_db_sync:118`)
- Modify: `app/knowledge/code_db_sync_pipeline.py` (`run:50`, begin at `59`)
- Test: `tests/integration/test_sync_run_lifecycle.py`

**Interfaces:**
- Mirror of Task 2 for `kind="code_db_sync"`: `_dispatch_code_db_sync(connection_id, project_id, *, wf_id)`, `_run_sync_background(connection_id, project_id, *, wf_id)`, `CodeDbSyncPipeline.run(..., wf_id: str | None = None)`, `run_code_db_sync(ctx, *, connection_id, project_id, wf_id)`. `trigger_sync` returns `202 {status, run_id, workflow_id, connection_id}`.
- `maybe_autostart_sync` creates the run with `trigger="chain"` and threads its `wf_id`.

- [ ] **Step 1: Write the failing test**

`tests/integration/test_sync_run_lifecycle.py`:

```python
from __future__ import annotations

import pytest

from app.knowledge.code_db_sync_pipeline import CodeDbSyncPipeline


async def test_sync_pipeline_accepts_external_wf_id(monkeypatch):
    begun: list[str] = []

    async def fake_begin(*a, **k):
        begun.append("begin")
        return "unused"

    monkeypatch.setattr("app.core.workflow_tracker.tracker.begin", fake_begin)
    pipe = CodeDbSyncPipeline()
    try:
        await pipe.run(connection_id="c", project_id="p", wf_id="wf-ext")
    except Exception:
        pass
    assert begun == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/integration/test_sync_run_lifecycle.py -v`
Expected: FAIL — `TypeError: run() got an unexpected keyword argument 'wf_id'`.

- [ ] **Step 3: Write minimal implementation**

In `app/knowledge/code_db_sync_pipeline.py`, add `wf_id: str | None = None` to `run` (line 50) and reuse at the begin (line 59):

```python
        wf_id = wf_id or await self._tracker.begin(
            "code_db_sync", {"connection_id": connection_id, "project_id": project_id},
        )
```

In `app/api/routes/connections.py`:
- `_dispatch_code_db_sync(connection_id, project_id, *, wf_id)` — add `wf_id=wf_id` to the `enqueue(...)` call and to `_run_sync_background(connection_id, project_id, wf_id=wf_id)`.
- `_run_sync_background(connection_id, project_id, *, wf_id)` — pass `wf_id=wf_id` into `pipeline.run(...)` (line 1065).
- `trigger_sync` body (lines 962-977): create the run before dispatch and return ids:

```python
        from app.services.run_coordinator import RunAlreadyActive, RunCoordinator

        try:
            run = await RunCoordinator().start(
                db, kind="code_db_sync", project_id=conn.project_id,
                connection_id=connection_id, trigger="manual",
            )
        except RunAlreadyActive:
            raise HTTPException(status_code=409, detail="Code-DB sync already in progress for this connection")
        await _sync_svc.set_sync_status(db, connection_id, "running")
        await db.commit()
        project_id = conn.project_id
        await _dispatch_code_db_sync(connection_id, project_id, wf_id=run.workflow_id)

    return JSONResponse(
        status_code=202,
        content={"status": "started", "run_id": run.id, "workflow_id": run.workflow_id,
                 "connection_id": connection_id},
    )
```
- `maybe_autostart_sync` (line 204): replace `await _dispatch_code_db_sync(connection_id, project_id)` with:

```python
            run = await RunCoordinator().start(
                db, kind="code_db_sync", project_id=project_id,
                connection_id=connection_id, trigger="chain",
            )
            await _dispatch_code_db_sync(connection_id, project_id, wf_id=run.workflow_id)
```
(and `from app.services.run_coordinator import RunCoordinator` at the top of the function; the `db` here is a fresh `async_session_factory()` session already opened in that block — reuse it for `start`.)

In `app/worker.py` `run_code_db_sync` (line 118): add `wf_id: str` to the signature and `wf_id=wf_id` to `pipeline.run(...)` (line 133).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/integration/test_sync_run_lifecycle.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd backend && .venv/bin/ruff check app/ && .venv/bin/mypy app/ --ignore-missing-imports
git add backend/app/api/routes/connections.py backend/app/worker.py backend/app/knowledge/code_db_sync_pipeline.py backend/tests/integration/test_sync_run_lifecycle.py
git commit -m "feat(runs): code-DB sync trigger creates IndexingRun and threads wf_id

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Rewire repo-index trigger through RunCoordinator

**Files:**
- Modify: `app/api/routes/repos.py` (`_spawn_repo_index:192`, `run_repo_index_task:294`)
- Modify: `app/worker.py` (`run_repo_index:174`)
- Test: `tests/unit/api/test_repo_index_run.py`

**Interfaces:**
- `_spawn_repo_index` creates the run via `RunCoordinator.start(kind="index_repo", project_id, connection_id=None, trigger=...)`, uses `run.workflow_id` as the pipeline `wf_id`, and returns `{"status","run_id","workflow_id","resumed"}` in **both** modes (ARQ no longer returns `workflow_id: None`). ARQ `enqueue("run_repo_index", ..., wf_id=run.workflow_id)`.
- `run_repo_index(ctx, *, project_id, force_full, wf_id)` → `run_repo_index_task(project_id, force_full, wf_id=wf_id)` → `_run_index_background(..., wf_id, ...)` (already takes `wf_id`).

- [ ] **Step 1: Write the failing test**

`tests/unit/api/test_repo_index_run.py`:

```python
from __future__ import annotations

import inspect

from app.api.routes import repos
from app import worker


def test_run_repo_index_worker_accepts_wf_id():
    sig = inspect.signature(worker.run_repo_index)
    assert "wf_id" in sig.parameters


def test_run_repo_index_task_accepts_wf_id():
    sig = inspect.signature(repos.run_repo_index_task)
    assert "wf_id" in sig.parameters
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/unit/api/test_repo_index_run.py -v`
Expected: FAIL — `assert 'wf_id' in {...}`.

- [ ] **Step 3: Write minimal implementation**

In `app/api/routes/repos.py` `_spawn_repo_index` — replace the wf-creation/dispatch block (lines 262-291). Use the coordinator instead of `tracker.begin`:

```python
        from app.services.run_coordinator import RunAlreadyActive, RunCoordinator

        try:
            run = await RunCoordinator().start(
                db, kind="index_repo", project_id=project_id, connection_id=None,
                trigger=trigger, force_full=force_full,
            )
        except RunAlreadyActive:
            return None
        wf_id = run.workflow_id

        if task_queue.is_arq_active():
            await task_queue.enqueue(
                "run_repo_index",
                task_id=f"repo_index:{project_id}:{uuid.uuid4().hex[:8]}",
                project_id=project_id,
                force_full=force_full,
                wf_id=wf_id,
            )
            return {"status": "queued", "run_id": run.id, "workflow_id": wf_id, "resumed": resumed}

        body = IndexRequest(force_full=force_full)
        task = asyncio.create_task(
            _run_index_background(project_id, project, body, wf_id, lock),
        )
        task.add_done_callback(_make_index_done_cb(project_id))
        _indexing_tasks[project_id] = task

    return {"status": "resumed" if resumed else "started", "run_id": run.id,
            "workflow_id": wf_id, "resumed": resumed}
```

> Remove the old `wf_id = await tracker.begin("index_repo", {...})` call — the run owns the workflow id now. Keep the existing checkpoint resume logic above it untouched (`IndexingCheckpoint` is the resume cursor).

`run_repo_index_task` (line 294): add `wf_id: str | None = None`; when provided, skip the internal `tracker.begin` and use it:

```python
async def run_repo_index_task(project_id, force_full=False, *, chain_sync=True, wf_id=None):
    async with async_session_factory() as db:
        project = await _project_svc.get(db, project_id)
        if not project or not project.repo_url:
            logger.error("run_repo_index_task: project %s missing or has no repo_url", project_id[:8])
            return
        if wf_id is None:
            wf_id = await tracker.begin(
                "index_repo", {"project_id": project_id, "repo_url": project.repo_url, "trigger": "queue"})
    lock = _indexing_locks.setdefault(project_id, asyncio.Lock())
    body = IndexRequest(force_full=force_full)
    await _run_index_background(project_id, project, body, wf_id, lock, chain_sync=chain_sync)
```

In `app/worker.py` `run_repo_index` (line 174): add `wf_id: str | None = None` and forward:

```python
async def run_repo_index(ctx: dict, *, project_id: str, force_full: bool = False, wf_id: str | None = None) -> None:  # noqa: ARG001
    from app.api.routes.repos import run_repo_index_task
    await run_repo_index_task(project_id, force_full=force_full, wf_id=wf_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/unit/api/test_repo_index_run.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd backend && .venv/bin/ruff check app/ && .venv/bin/mypy app/ --ignore-missing-imports
git add backend/app/api/routes/repos.py backend/app/worker.py backend/tests/unit/api/test_repo_index_run.py
git commit -m "feat(runs): repo-index trigger returns real run_id/workflow_id in ARQ mode

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Rebuild pipeline-status + tasks/active on `indexing_runs`

**Files:**
- Modify: `app/services/pipeline_status_service.py` (`get_status`, `list_synthetic_active_tasks`)
- Modify: `app/api/routes/tasks.py` (`get_active_tasks`)
- Test: `tests/unit/services/test_pipeline_status_runs.py`

**Interfaces:**
- `PipelineStatusService.get_status(session, project_id)` reads active `IndexingRun` rows. `repo`/`db_index`/`code_db_sync` blocks gain `progress_pct, current_step, step_index, total_steps, run_id, failure_kind`. `any_running` = any active run.
- `tasks/active` returns `{workflow_id, run_id, pipeline, kind, started_at, progress_pct, extra}` from active `IndexingRun` rows (tenancy-filtered), no synthetic ids.

- [ ] **Step 1: Write the failing test**

`tests/unit/services/test_pipeline_status_runs.py`:

```python
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
import app.models  # noqa: F401
from app.services.pipeline_status_service import PipelineStatusService
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


async def test_status_reflects_active_run(session: AsyncSession):
    await RunCoordinator().start(session, kind="db_index", project_id="p", connection_id="c")
    status = await PipelineStatusService().get_status(session, "p")
    assert status["any_running"] is True
    conn = next(c for c in status["connections"] if c["connection_id"] == "c")
    assert conn["db_index"]["is_indexing"] is True
    assert conn["db_index"]["run_id"]
    assert "progress_pct" in conn["db_index"]
```

> The current `get_status` also queries `ConnectionService`/`DbIndexService`; in this unit test those return empty for an unknown connection. Implement `get_status` so the active-run scan is the source of truth for `is_indexing`/progress and merges connection display names when available (missing name → use the id).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/unit/services/test_pipeline_status_runs.py -v`
Expected: FAIL — `KeyError: 'run_id'` (current shape lacks it).

- [ ] **Step 3: Write minimal implementation**

Add a helper to `PipelineStatusService` that loads active runs and rewrite `get_status` to use it. Insert near the top of the class:

```python
    async def _active_runs(self, session, project_id):
        from app.models.indexing_run import IndexingRun
        from sqlalchemy import select

        stmt = select(IndexingRun).where(
            IndexingRun.project_id == project_id,
            IndexingRun.status.in_(("queued", "running", "cancelling")),
        )
        return (await session.execute(stmt)).scalars().all()

    @staticmethod
    def _run_block(run) -> dict:
        return {
            "is_indexing": True,
            "run_id": run.id,
            "workflow_id": run.workflow_id,
            "status": run.status,
            "current_step": run.current_step,
            "step_index": run.step_index,
            "total_steps": run.total_steps,
            "progress_pct": run.progress_pct,
            "failure_kind": run.failure_kind,
        }
```

Rewrite `get_status` so `repo`/`db_index`/`code_db_sync` `is_indexing` and progress come from `_active_runs` (grouped by `kind` + `connection_id`); keep the existing `last_indexed_*` / `synced_*` display fields from the domain services. `any_running = bool(active_runs)`. For each connection block, when no active run matches, emit `{"is_indexing": False, "progress_pct": 0, ...}` plus the existing domain status fields.

Rewrite `list_synthetic_active_tasks` to return active runs directly:

```python
    async def list_synthetic_active_tasks(self, session, *, accessible_project_ids):
        from app.models.indexing_run import IndexingRun
        from sqlalchemy import select

        if not accessible_project_ids:
            return []
        stmt = select(IndexingRun).where(
            IndexingRun.project_id.in_(list(accessible_project_ids)),
            IndexingRun.status.in_(("queued", "running", "cancelling")),
        )
        rows = (await session.execute(stmt)).scalars().all()
        return [
            {
                "workflow_id": r.workflow_id, "run_id": r.id, "pipeline": r.kind, "kind": r.kind,
                "started_at": r.started_at.timestamp() if r.started_at else 0.0,
                "progress_pct": r.progress_pct,
                "extra": {"project_id": r.project_id, "connection_id": r.connection_id},
            }
            for r in rows
        ]
```

In `app/api/routes/tasks.py` `get_active_tasks`: drop the `is_arq_active()` gate around synthetic tasks (active runs are authoritative in both modes) — always merge `tracker.get_active()` (live, in-proc) with `list_synthetic_active_tasks` (DB-backed). The existing `_merge_active_tasks` dedups by `workflow_id`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/unit/services/test_pipeline_status_runs.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd backend && .venv/bin/ruff check app/ && .venv/bin/mypy app/ --ignore-missing-imports
git add backend/app/services/pipeline_status_service.py backend/app/api/routes/tasks.py backend/tests/unit/services/test_pipeline_status_runs.py
git commit -m "feat(runs): pipeline-status and tasks/active sourced from indexing_runs

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Cancel + retry endpoints

**Files:**
- Create: `app/api/routes/runs.py`
- Modify: `app/main.py` (register router), `app/api/routes/connections.py` (cancel hooks into in-proc task dicts), `app/api/routes/repos.py` (same)
- Test: `tests/unit/api/test_runs_cancel_retry.py`

**Interfaces:**
- `POST /runs/{run_id}/cancel` → `RunCoordinator.request_cancel`; additionally cancels the matching in-process asyncio task (`_indexing_tasks` / `_db_index_tasks` / `_sync_tasks`) by resolving the run's `project_id`/`connection_id`.
- `POST /runs/{run_id}/retry` (body `{force_full: bool}`) → `RunCoordinator.retry`, then dispatches the new run via the kind's dispatcher; returns `{run_id, workflow_id}`.
- `GET /runs/{run_id}` → run projection; `GET /runs/{run_id}/events?level=` → journal.
- Membership: resolve the run's `project_id`, require `editor` for cancel/retry, `viewer` for reads.

- [ ] **Step 1: Write the failing test**

`tests/unit/api/test_runs_cancel_retry.py`:

```python
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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


async def test_cancel_sets_flag_and_returns_true(session: AsyncSession):
    coord = RunCoordinator()
    run = await coord.start(session, kind="db_index", project_id="p", connection_id="c")
    assert await coord.request_cancel(session, run.id) is True
    await session.refresh(run)
    assert run.cancel_requested is True


async def test_retry_after_failure_creates_new_run(session: AsyncSession):
    coord = RunCoordinator()
    run = await coord.start(session, kind="db_index", project_id="p", connection_id="c")
    await coord.finish(run, "failed", error="x", failure_kind="fatal")
    new = await coord.retry(session, run.id, force_full=False)
    assert new.id != run.id and new.status == "running"
```

> These exercise the coordinator primitives the routes call. A full HTTP-level test (TestClient) is added in P5 once the FE contract is fixed; here we lock the service behavior the routes depend on.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/unit/api/test_runs_cancel_retry.py -v`
Expected: PASS for `test_cancel...` and `test_retry...` only if P0 Task 9 landed; if `app/api/routes/runs.py` import is added to the test later it will fail. (This task's deliverable is the route module + wiring; run the suite after Step 3.)

- [ ] **Step 3: Write minimal implementation**

`app/api/routes/runs.py`:

```python
"""Run control + read endpoints (cancel / retry / detail / events)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.rate_limit import limiter
from app.models.indexing_run import IndexingRun, IndexingRunEvent
from app.services.membership_service import MembershipService
from app.services.run_coordinator import RunCoordinator

logger = logging.getLogger(__name__)
router = APIRouter()
_membership = MembershipService()
_coord = RunCoordinator()


async def _load_run(db: AsyncSession, run_id: str) -> IndexingRun:
    run = await db.get(IndexingRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


class RetryBody(BaseModel):
    force_full: bool = False


@router.post("/{run_id}/cancel")
@limiter.limit("20/minute")
async def cancel_run(request: Request, run_id: str, db: AsyncSession = Depends(get_db),
                     user: dict = Depends(get_current_user)):
    run = await _load_run(db, run_id)
    await _membership.require_role(db, run.project_id, user["user_id"], "editor")
    ok = await _coord.request_cancel(db, run_id)
    _cancel_inproc_task(run)
    return {"cancelled": ok, "run_id": run_id}


@router.post("/{run_id}/retry")
@limiter.limit("10/minute")
async def retry_run(request: Request, run_id: str, body: RetryBody | None = None,
                    db: AsyncSession = Depends(get_db), user: dict = Depends(get_current_user)):
    run = await _load_run(db, run_id)
    await _membership.require_role(db, run.project_id, user["user_id"], "editor")
    body = body or RetryBody()
    new = await _coord.retry(db, run_id, force_full=body.force_full)
    await _dispatch_for_kind(db, new)
    return {"run_id": new.id, "workflow_id": new.workflow_id, "status": new.status}


@router.get("/{run_id}")
async def get_run(run_id: str, db: AsyncSession = Depends(get_db),
                  user: dict = Depends(get_current_user)):
    run = await _load_run(db, run_id)
    await _membership.require_role(db, run.project_id, user["user_id"], "viewer")
    return _run_to_dict(run)


@router.get("/{run_id}/events")
async def get_run_events(run_id: str, level: str | None = Query(default=None),
                         db: AsyncSession = Depends(get_db),
                         user: dict = Depends(get_current_user)):
    run = await _load_run(db, run_id)
    await _membership.require_role(db, run.project_id, user["user_id"], "viewer")
    stmt = select(IndexingRunEvent).where(IndexingRunEvent.run_id == run_id)
    if level:
        stmt = stmt.where(IndexingRunEvent.level == level)
    rows = (await db.execute(stmt.order_by(IndexingRunEvent.ts))).scalars().all()
    return [
        {"ts": e.ts.isoformat() if e.ts else None, "step": e.step, "status": e.status,
         "detail": e.detail, "elapsed_ms": e.elapsed_ms, "progress_pct": e.progress_pct,
         "level": e.level}
        for e in rows
    ]


def _run_to_dict(run: IndexingRun) -> dict:
    return {
        "id": run.id, "kind": run.kind, "status": run.status, "trigger": run.trigger,
        "project_id": run.project_id, "connection_id": run.connection_id,
        "current_step": run.current_step, "step_index": run.step_index,
        "total_steps": run.total_steps, "progress_pct": run.progress_pct,
        "error": run.error, "failure_kind": run.failure_kind,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "workflow_id": run.workflow_id,
    }


def _cancel_inproc_task(run: IndexingRun) -> None:
    """Cancel the in-process asyncio task backing this run, if present."""
    try:
        if run.kind == "index_repo":
            from app.api.routes.repos import _indexing_tasks

            t = _indexing_tasks.get(run.project_id)
        elif run.kind == "db_index":
            from app.api.routes.connections import _db_index_tasks

            t = _db_index_tasks.get(run.connection_id or "")
        elif run.kind == "code_db_sync":
            from app.api.routes.connections import _sync_tasks

            t = _sync_tasks.get(run.connection_id or "")
        else:
            t = None
        if t is not None and not t.done():
            t.cancel()
    except Exception:  # noqa: BLE001
        logger.debug("in-proc cancel best-effort failed", exc_info=True)


async def _dispatch_for_kind(db: AsyncSession, run: IndexingRun) -> None:
    if run.kind == "db_index":
        from app.api.routes.connections import _dispatch_db_index
        from app.services.connection_service import ConnectionService

        svc = ConnectionService()
        conn = await svc.get(db, run.connection_id)
        cfg = await svc.to_config(db, conn)
        await _dispatch_db_index(run.connection_id, cfg, run.project_id, wf_id=run.workflow_id)
    elif run.kind == "code_db_sync":
        from app.api.routes.connections import _dispatch_code_db_sync

        await _dispatch_code_db_sync(run.connection_id, run.project_id, wf_id=run.workflow_id)
    elif run.kind == "index_repo":
        from app.core import task_queue

        if task_queue.is_arq_active():
            import uuid

            await task_queue.enqueue(
                "run_repo_index", task_id=f"repo_index:{run.project_id}:{uuid.uuid4().hex[:8]}",
                project_id=run.project_id, force_full=True, wf_id=run.workflow_id)
        else:
            from app.api.routes.repos import run_repo_index_task

            import asyncio

            asyncio.create_task(
                run_repo_index_task(run.project_id, force_full=True, wf_id=run.workflow_id))
```

Register in `app/main.py` (near the other `app.include_router(...)` lines):

```python
from app.api.routes import runs  # noqa: E402  (add to the existing route imports)
app.include_router(runs.router, prefix="/api/runs", tags=["runs"])
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && .venv/bin/pytest tests/unit/api/test_runs_cancel_retry.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
cd backend && .venv/bin/ruff check app/ && .venv/bin/mypy app/ --ignore-missing-imports
git add backend/app/api/routes/runs.py backend/app/main.py backend/tests/unit/api/test_runs_cancel_retry.py
git commit -m "feat(runs): cancel/retry/detail/events endpoints

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: Reaper recovers stuck `indexing_runs`

**Files:**
- Modify: `app/services/stale_run_reaper.py`
- Test: `tests/unit/services/test_reaper_indexing_runs.py`

**Interfaces:**
- `StaleRunReaper.reap_once(...)` additionally flips `IndexingRun` rows in `running`/`cancelling` whose `heartbeat_at` (or `started_at` when null) is older than the timeout → `failed` (running) / `cancelled` (cancelling), and upserts an `ErrorLog` for the failed ones. Return dict gains `"runs": <count>`.

- [ ] **Step 1: Write the failing test**

`tests/unit/services/test_reaper_indexing_runs.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
import app.models  # noqa: F401
from app.models.indexing_run import IndexingRun
from app.services.stale_run_reaper import StaleRunReaper


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


async def test_reaper_flips_stuck_run(session: AsyncSession):
    old = datetime.now(UTC) - timedelta(seconds=10_000)
    run = IndexingRun(workflow_id="wf", project_id="p", connection_id=None,
                      kind="index_repo", trigger="manual", status="running",
                      heartbeat_at=old)
    session.add(run)
    await session.commit()

    out = await StaleRunReaper().reap_once(session, timeout_seconds=300)
    await session.commit()
    await session.refresh(run)
    assert run.status == "failed"
    assert out["runs"] >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/unit/services/test_reaper_indexing_runs.py -v`
Expected: FAIL — `KeyError: 'runs'` (and run stays `running`).

- [ ] **Step 3: Write minimal implementation**

In `app/services/stale_run_reaper.py`, import the model and add an update in `reap_once` (after the existing three updates, before `flush`):

```python
from app.models.indexing_run import IndexingRun
```

```python
        runs_failed: CursorResult = await session.execute(  # type: ignore[assignment]
            update(IndexingRun)
            .where(IndexingRun.status == "running", self._stale_run(IndexingRun, cutoff))
            .values(status="failed", error="stale run reaped", failure_kind="fatal",
                    finished_at=datetime.now(UTC))
        )
        runs_cancelled: CursorResult = await session.execute(  # type: ignore[assignment]
            update(IndexingRun)
            .where(IndexingRun.status == "cancelling", self._stale_run(IndexingRun, cutoff))
            .values(status="cancelled", finished_at=datetime.now(UTC))
        )
```

Add a `_stale_run` variant (IndexingRun has `started_at` not `updated_at` for the null-heartbeat grace):

```python
    @staticmethod
    def _stale_run(model, cutoff: datetime):
        return (model.heartbeat_at.is_not(None) & (model.heartbeat_at < cutoff)) | (
            model.heartbeat_at.is_(None) & (model.started_at.is_not(None)) & (model.started_at < cutoff)
        )
```

Add to the `out` dict:

```python
            "runs": max(0, int(runs_failed.rowcount or 0)) + max(0, int(runs_cancelled.rowcount or 0)),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/unit/services/test_reaper_indexing_runs.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd backend && .venv/bin/ruff check app/ && .venv/bin/mypy app/ --ignore-missing-imports
git add backend/app/services/stale_run_reaper.py backend/tests/unit/services/test_reaper_indexing_runs.py
git commit -m "feat(runs): reaper recovers stuck indexing_runs

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 8: Tolerant cross-process event reconstruction

**Files:**
- Modify: `app/core/workflow_events.py` (`_subscribe_loop`, ~line 53)
- Test: `tests/unit/core/test_workflow_events_tolerant.py`

**Interfaces:**
- `_subscribe_loop` rebuilds `WorkflowEvent` filtering the Redis JSON payload to known dataclass fields, so new/legacy/extra keys never drop an event.

- [ ] **Step 1: Write the failing test**

`tests/unit/core/test_workflow_events_tolerant.py`:

```python
from __future__ import annotations

import dataclasses

from app.core.workflow_tracker import WorkflowEvent


def test_known_field_filter_drops_extras():
    payload = {"workflow_id": "w", "step": "s", "status": "started",
               "run_id": "r", "progress_pct": 40, "totally_new_key": 1}
    fields = {f.name for f in dataclasses.fields(WorkflowEvent)}
    ev = WorkflowEvent(**{k: v for k, v in payload.items() if k in fields})
    assert ev.run_id == "r"
    assert ev.progress_pct == 40
```

- [ ] **Step 2: Run test to verify it fails**

(It passes as written — it asserts the *pattern*. To make it a true regression of the production call site, also assert the helper exists.) Add to the test:

```python
def test_subscribe_loop_uses_field_filter():
    import inspect

    from app.core import workflow_events

    src = inspect.getsource(workflow_events._subscribe_loop)
    assert "dataclasses.fields" in src or "_KNOWN_FIELDS" in src
```

Run: `cd backend && .venv/bin/pytest tests/unit/core/test_workflow_events_tolerant.py -v`
Expected: FAIL on `test_subscribe_loop_uses_field_filter`.

- [ ] **Step 3: Write minimal implementation**

In `app/core/workflow_events.py`, replace the `WorkflowEvent(**payload)` line in `_subscribe_loop` with a filtered build:

```python
                payload = json.loads(raw)
                _known = {f.name for f in dataclasses.fields(WorkflowEvent)}
                event = WorkflowEvent(**{k: v for k, v in payload.items() if k in _known})
```

Add `import dataclasses` at the top of the file.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/unit/core/test_workflow_events_tolerant.py -v`
Expected: PASS.

- [ ] **Step 5: Full P1 suite, lint, type-check, commit**

```bash
cd backend && .venv/bin/ruff format app/ tests/ && .venv/bin/ruff check app/ tests/ && .venv/bin/mypy app/ --ignore-missing-imports
.venv/bin/pytest tests/unit/services/test_run_coordinator_hook.py tests/unit/services/test_pipeline_status_runs.py tests/unit/services/test_reaper_indexing_runs.py tests/unit/api/test_runs_cancel_retry.py tests/unit/api/test_repo_index_run.py tests/unit/core/test_workflow_events_tolerant.py tests/integration/test_db_index_run_lifecycle.py tests/integration/test_sync_run_lifecycle.py -v
git add -A
git commit -m "feat(runs): tolerant cross-process event reconstruction

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:** trigger rewiring + real ids (§4 "kills null id") → Tasks 2–4; persistence hook → Task 1; status/active on runs (§5.5) → Task 5; cancel/retry (§5.5) → Task 6; reaper recovery (§5.6 stuck-run SLO) → Task 7; tolerant cross-process bridge (§4 D) → Task 8. ✓

**Placeholder scan:** No `TBD`/`TODO`/"add error handling". Task 5 Step 3 describes the `get_status` rewrite in prose plus concrete helpers — the helper code is shown; the merge loop is specified by exact field shape. The `_run_db_index_background` / `_run_sync_background` edits name exact lines and the exact change (add `*, wf_id` + pass through). ✓

**Type consistency:** `wf_id` keyword is consistent across `_dispatch_db_index`/`_run_db_index_background`/`run_db_index`/`DbIndexPipeline.run` (Task 2) and the sync mirror (Task 3); `run.workflow_id`/`run.id` returned in all 202 bodies; `_run_block`/`_active_runs` names match between Task 5 definition and use. `request_cancel`/`retry`/`start`/`finish` signatures match P0. ✓

**Risks flagged:** (1) Task 1 `_on_event` opens its own session per event — acceptable at run cadence; if it becomes hot, batch in P3. (2) ARQ hard-cancel of an in-flight job is best-effort (Task 6 cancels in-proc tasks; ARQ relies on `cancel_requested` honored at the next step boundary by the hook marking terminal on `pipeline_end`). (3) `get_status` keeps domain display fields — verify the existing `DbIndexService.get_status`/`CodeDbSyncService.get_status` calls remain for `last_indexed_*`.

---

## Execution Handoff

P1 plan complete. It depends on P0 being merged (contracts). Execute after P0 via subagent-driven-development (recommended) or executing-plans. **Next:** P2 (scheduled sync), P3 (telemetry & errors), P4 (agent-lifecycle observability), P5 (frontend).
