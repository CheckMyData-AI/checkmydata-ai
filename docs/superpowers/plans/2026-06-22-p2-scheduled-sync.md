# P2 — Scheduled Sync as First-Class Runs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make scheduled (daily) sync a visible, persisted, controllable first-class `IndexingRun(kind="daily_sync")` with sub-runs, retire the parallel `KnowledgeSyncRun` audit table, move sync-history onto `/runs`, and add per-project schedule + on-demand "sync now".

**Architecture:** The daily orchestrator (`DailyKnowledgeSyncService.run_for_project`) runs under a parent `daily_sync` run driven by `RunCoordinator` through the P0 `daily_sync` manifest (`plan_targets → db_index → code_db_sync → freshness_reconcile → summarize`). Each sub-operation (repo index / per-connection db-index / sync) creates its own child `IndexingRun`, so both the orchestration and each unit are individually visible. `KnowledgeSyncRun` and its service are removed; `/projects/{id}/sync-history` reads `indexing_runs WHERE kind='daily_sync'`. Per-project schedule columns gate the cron wave; a `sync-now` endpoint triggers a daily run manually.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 async, ARQ, Alembic, pytest (asyncio auto).

**Source spec:** `…/2026-06-22-sync-and-observability-redesign-design.md` (§5.3 daily_sync manifest, §5.5 schedule endpoints, §2.3). **Depends on:** P0 (contracts) + P1 (lifecycle wiring, `RunCoordinator` hook, child-run pattern).

## Global Constraints

- **Greenfield — no backward compatibility.** Delete `KnowledgeSyncRun`, `KnowledgeSyncRunService`, and `DailyKnowledgeSyncService.persist_run`. Drop table `knowledge_sync_runs`.
- Locked interfaces consumed: `RunCoordinator.start/step/finish`, `IndexingRun`, manifests (`daily_sync` already defined in `app/knowledge/run_manifests.py`), and the P1 child-run dispatch pattern (`_dispatch_db_index(..., wf_id=)`, `_dispatch_code_db_sync(..., wf_id=)`, `run_repo_index_task(..., wf_id=)`).
- New settings → `app/config.py` + `backend/.env.example`. Per-project overrides default to the global `daily_knowledge_sync_*` values (`config.py:293-296`).
- Python 3.12, line length 100, ruff `0.15.15`, mypy clean, async-only, coverage ≥ 72%.
- Conventional commits ending with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- Run commands from `backend/` via `.venv/bin/<tool>`.

## File Structure

- Modify `app/services/daily_knowledge_sync_service.py` — `run_for_project(project_id, *, run=None)`; sub-ops create child runs; remove `persist_run`; add a freshness re-check in the `freshness_reconcile` step.
- Modify `app/worker.py` (`run_daily_project_knowledge_sync:195`) and `app/main.py` (`_dispatch_daily_knowledge_sync_wave:665`, cron loop) — create the parent `daily_sync` run via `RunCoordinator`; honor per-project schedule.
- Modify `app/models/project.py` — add `sync_schedule_enabled`, `sync_schedule_hour`.
- Delete `app/models/knowledge_sync_run.py`, `app/services/knowledge_sync_run_service.py`; remove their imports (`app/models/__init__.py:20`).
- Modify `app/api/routes/projects.py` (`sync-history:454`) — read `indexing_runs`; add `GET/PUT /{id}/sync-schedule`, `POST /{id}/sync-now`.
- Create `alembic/versions/b2c3d4e5f6a7_daily_sync_schedule_and_drop_ksr.py`.
- Tests under `tests/unit/services/`, `tests/integration/`, `tests/unit/api/`.

Reuse the P0 in-memory `session` fixture.

---

### Task 1: Migration — Project schedule columns + drop `knowledge_sync_runs`

**Files:**
- Modify: `app/models/project.py` (add two columns)
- Create: `alembic/versions/b2c3d4e5f6a7_daily_sync_schedule_and_drop_ksr.py`
- Test: migration round-trip

**Interfaces:**
- Produces: `Project.sync_schedule_enabled: bool | None`, `Project.sync_schedule_hour: int | None` (NULL ⇒ inherit global default). Drops table `knowledge_sync_runs`.

- [ ] **Step 1: Add the columns to the model**

In `app/models/project.py`, add (mirroring existing column style):

```python
    sync_schedule_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    sync_schedule_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

Ensure `Boolean, Integer` are imported in that module.

- [ ] **Step 2: Write the migration**

`alembic/versions/b2c3d4e5f6a7_daily_sync_schedule_and_drop_ksr.py`:

```python
"""project sync-schedule columns; drop knowledge_sync_runs

Revision ID: b2c3d4e5f6a7
Revises: a1f2b3c4d5e6
Create Date: 2026-06-22
"""

import sqlalchemy as sa
from alembic import op

revision = "b2c3d4e5f6a7"
down_revision = "a1f2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("sync_schedule_enabled", sa.Boolean(), nullable=True))
    op.add_column("projects", sa.Column("sync_schedule_hour", sa.Integer(), nullable=True))
    op.drop_table("knowledge_sync_runs")


def downgrade() -> None:
    op.create_table(
        "knowledge_sync_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("trigger", sa.String(length=50), nullable=False, server_default="scheduled"),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("steps_json", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index("ix_knowledge_sync_runs_project_id", "knowledge_sync_runs", ["project_id"])
    op.drop_column("projects", "sync_schedule_hour")
    op.drop_column("projects", "sync_schedule_enabled")
```

- [ ] **Step 3: Verify round-trip**

Run: `cd backend && PYTHONPATH=. .venv/bin/alembic upgrade head && PYTHONPATH=. .venv/bin/alembic downgrade -1 && PYTHONPATH=. .venv/bin/alembic upgrade head`
Expected: three clean runs ending at `b2c3d4e5f6a7`.

> Note: this migration drops `knowledge_sync_runs`; Tasks 2–4 remove all code that reads/writes it, so import errors won't occur once the whole P2 plan lands. Run the full suite only at the end of Task 5.

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/project.py backend/alembic/versions/b2c3d4e5f6a7_daily_sync_schedule_and_drop_ksr.py
git commit -m "feat(db): project sync-schedule columns; drop knowledge_sync_runs

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Daily sync runs under a first-class `daily_sync` run

**Files:**
- Modify: `app/services/daily_knowledge_sync_service.py`
- Modify: `app/worker.py` (`run_daily_project_knowledge_sync:195`)
- Modify: `app/main.py` (`_dispatch_daily_knowledge_sync_wave` inner `_run_in_process:699`)
- Test: `tests/integration/test_daily_sync_run.py`

**Interfaces:**
- Produces: `DailyKnowledgeSyncService.run_for_project(project_id, *, trigger="schedule") -> KnowledgeSyncRunResult` now (a) creates a parent `IndexingRun(kind="daily_sync")` via `RunCoordinator.start`, (b) wraps each phase in `coordinator.step(run, key)` for `plan_targets`/`freshness_reconcile`/`summarize` and around the db/sync loop for `db_index`/`code_db_sync`, (c) calls `coordinator.finish(run, terminal, error, failure_kind)`. Removes `persist_run` (the run row IS the record).
- Worker `run_daily_project_knowledge_sync(ctx, *, project_id)` and main's `_run_in_process` simply call `await svc.run_for_project(project_id)` — no `tracker.begin`/`persist_run`.

- [ ] **Step 1: Write the failing test**

`tests/integration/test_daily_sync_run.py`:

```python
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
import app.models  # noqa: F401
from app.models.indexing_run import IndexingRun
from app.models.project import Project
from app.services.daily_knowledge_sync_service import DailyKnowledgeSyncService


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


async def test_daily_sync_creates_daily_run_record(monkeypatch, session: AsyncSession):
    # A project with no repo_url → service returns 'skipped', but a daily_sync run
    # row must still be created and finished (visible in history).
    p = Project(id="p", name="x", owner_id="u")  # repo_url None
    session.add(p)
    await session.commit()

    # Point the service's session factory at our in-memory DB.
    sm = async_sessionmaker(session.bind, expire_on_commit=False)
    monkeypatch.setattr("app.services.daily_knowledge_sync_service.async_session_factory", sm)
    monkeypatch.setattr("app.services.run_coordinator.async_session_factory", sm)

    svc = DailyKnowledgeSyncService()
    result = await svc.run_for_project("p")
    assert result.status == "skipped"

    runs = (await session.execute(
        select(IndexingRun).where(IndexingRun.kind == "daily_sync")
    )).scalars().all()
    assert len(runs) == 1
    assert runs[0].status in ("completed", "failed", "cancelled")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/integration/test_daily_sync_run.py -v`
Expected: FAIL — no `daily_sync` run row created (service still uses `KnowledgeSyncRun`).

- [ ] **Step 3: Write minimal implementation**

In `app/services/daily_knowledge_sync_service.py`:
- Import: `from app.services.run_coordinator import RunCoordinator`.
- Remove the `from app.models.knowledge_sync_run import KnowledgeSyncRun` import and the entire `persist_run` method.
- Wrap `run_for_project`: at the top create the parent run, and on every return path map the result status → terminal and `finish` the run. Concretely, restructure to:

```python
    async def run_for_project(self, project_id: str, *, trigger: str = "schedule") -> KnowledgeSyncRunResult:
        coord = RunCoordinator()
        async with async_session_factory() as db:
            run = await coord.start(db, kind="daily_sync", project_id=project_id,
                                    connection_id=None, trigger=trigger)
        result = await self._run_for_project_inner(project_id, run, coord)
        terminal = "failed" if result.status == _STATUS_FAILED else "completed"
        failure_kind = "fatal" if terminal == "failed" else None
        async with async_session_factory() as db:
            run = await db.get(type(run), run.id)
            await coord.finish(run, terminal, error=result.error_message, failure_kind=failure_kind)
        return result
```

- Rename the existing `run_for_project` body to `_run_for_project_inner(self, project_id, run, coord)` and wrap its phases. Use `coord.step` around the major phases. Because `coord.step` needs the run attached to a session, open one session for the orchestration and pass it. Minimal phase wrapping:

```python
    async def _run_for_project_inner(self, project_id, run, coord) -> KnowledgeSyncRunResult:
        async with async_session_factory() as db:
            run = await db.get(type(run), run.id)
            # plan_targets
            async with coord.step(run, "plan_targets"):
                project, active_connections, skip = await self._plan(project_id)
            if skip is not None:
                return skip  # finish() in caller marks completed (skipped maps to completed)
            # repo + per-connection db/sync handled inside db_index/code_db_sync steps
            async with coord.step(run, "db_index"):
                repo_steps = await self._run_repo_phase(project_id)
            ...
            async with coord.step(run, "freshness_reconcile"):
                await self._recheck_freshness(project_id)
            async with coord.step(run, "summarize"):
                pass
        return result
```

> Implementation detail: keep the existing per-connection loop logic; the change is (a) it runs inside the `db_index`/`code_db_sync` `coord.step` blocks, and (b) `_plan` extracts the early skip checks (no repo / no connections → return a `KnowledgeSyncRunResult(status=_STATUS_SKIPPED)`). The caller's `finish` maps `skipped`→`completed` (so a skipped daily run shows as a completed run with a "skipped" detail in `meta_json`). Set `run.meta_json` summary of `steps` before finishing (store via `run.meta_json = json.dumps({"steps": result.steps_json, "status": result.status})`).

In `app/worker.py` `run_daily_project_knowledge_sync` (line 195), replace the whole body with:

```python
async def run_daily_project_knowledge_sync(ctx: dict, *, project_id: str) -> None:  # noqa: ARG001
    from app.services.daily_knowledge_sync_service import DailyKnowledgeSyncService

    await DailyKnowledgeSyncService().run_for_project(project_id)
```

In `app/main.py` `_dispatch_daily_knowledge_sync_wave`, replace the inner `_run_in_process` (lines 699-729) with:

```python
                async def _run_in_process(*, project_id: str = pid) -> None:
                    from app.services.daily_knowledge_sync_service import DailyKnowledgeSyncService

                    await DailyKnowledgeSyncService().run_for_project(project_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/integration/test_daily_sync_run.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd backend && .venv/bin/ruff check app/ && .venv/bin/mypy app/ --ignore-missing-imports
git add backend/app/services/daily_knowledge_sync_service.py backend/app/worker.py backend/app/main.py backend/tests/integration/test_daily_sync_run.py
git commit -m "feat(sync): daily sync runs as a first-class daily_sync IndexingRun

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Sub-operations become child runs

**Files:**
- Modify: `app/services/daily_knowledge_sync_service.py` (`_run_repo_index`, `_run_db_index`, `_run_code_db_sync`)
- Test: `tests/integration/test_daily_sync_child_runs.py`

**Interfaces:**
- Each sub-op creates a child `IndexingRun` (kinds `index_repo`/`db_index`/`code_db_sync`, `trigger="schedule"`) via `RunCoordinator.start` and passes `wf_id=child.workflow_id` into the respective pipeline call (`run_repo_index_task(..., wf_id=)`, `DbIndexPipeline.run(..., wf_id=)`, `CodeDbSyncPipeline.run(..., wf_id=)`), then `finish`es the child. This makes each unit individually visible in `/runs` with progress.

- [ ] **Step 1: Write the failing test**

`tests/integration/test_daily_sync_child_runs.py`:

```python
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
import app.models  # noqa: F401
from app.models.indexing_run import IndexingRun
from app.services.daily_knowledge_sync_service import DailyKnowledgeSyncService


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


async def test_child_db_index_run_created(monkeypatch, session: AsyncSession):
    sm = async_sessionmaker(session.bind, expire_on_commit=False)
    monkeypatch.setattr("app.services.daily_knowledge_sync_service.async_session_factory", sm)
    monkeypatch.setattr("app.services.run_coordinator.async_session_factory", sm)

    # Stub the pipeline so _run_db_index returns completed quickly.
    async def fake_run(self, *, connection_id, connection_config, project_id, wf_id=None):
        return {"status": "ok", "tables": 1}

    monkeypatch.setattr("app.knowledge.db_index_pipeline.DbIndexPipeline.run", fake_run)
    # Stub connection lookups used by _run_db_index.
    svc = DailyKnowledgeSyncService()

    class _Cfg: ...
    monkeypatch.setattr(svc._conn_svc, "get", lambda s, cid: _make_conn(cid))
    monkeypatch.setattr(svc._conn_svc, "to_config", lambda s, c: _Cfg())
    from app.services.db_index_service import DbIndexService
    monkeypatch.setattr(DbIndexService, "get_indexing_status", lambda self, s, cid: _coro("idle"))
    monkeypatch.setattr(DbIndexService, "set_indexing_status", lambda self, s, cid, st: _coro(None))

    status, err = await svc._run_db_index("c1", "p1")
    assert status == "completed"
    runs = (await session.execute(
        select(IndexingRun).where(IndexingRun.kind == "db_index", IndexingRun.connection_id == "c1")
    )).scalars().all()
    assert len(runs) == 1


async def _coro(v):
    return v


def _make_conn(cid):
    async def _c():
        class C: id = cid
        return C()
    return _c()
```

> The stubs keep the test hermetic; the assertion that matters is that a `db_index` child run row exists for the connection.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/integration/test_daily_sync_child_runs.py -v`
Expected: FAIL — no child `db_index` run created (sub-ops don't use the coordinator yet).

- [ ] **Step 3: Write minimal implementation**

In `_run_db_index` (daily service), wrap the pipeline call with a child run. Replace the `set_indexing_status("running")` + `pipeline.run(...)` block with:

```python
            from app.services.run_coordinator import RunAlreadyActive, RunCoordinator

            coord = RunCoordinator()
            try:
                async with async_session_factory() as rdb:
                    child = await coord.start(rdb, kind="db_index", project_id=project_id,
                                              connection_id=connection_id, trigger="schedule")
            except RunAlreadyActive:
                return _STEP_SKIPPED, "db index already running"

            async with async_session_factory() as session:
                await idx_svc.set_indexing_status(session, connection_id, "running")
                await session.commit()

            from app.knowledge.db_index_pipeline import DbIndexPipeline

            pipeline = DbIndexPipeline(db_index_batch_size=settings.db_index_batch_size)
            pipeline_result = await pipeline.run(
                connection_id=connection_id, connection_config=config,
                project_id=project_id, wf_id=child.workflow_id,
            )
```

The pipeline emits via the threaded `wf_id`; the P1 persistence hook updates the child run. After the pipeline, finish the child explicitly in the `finally` (in case no `pipeline_end` was emitted by a hard failure):

```python
        finally:
            terminal = "completed" if final_status == _STEP_COMPLETED else "failed"
            async with async_session_factory() as rdb:
                cr = await rdb.get(type(child), child.id)
                if cr and cr.status in ("queued", "running", "cancelling"):
                    await coord.finish(cr, terminal, error=error,
                                       failure_kind="fatal" if terminal == "failed" else None)
            # keep existing set_indexing_status domain write
```

Apply the same child-run wrapping to `_run_code_db_sync` (kind `code_db_sync`, pass `wf_id=child.workflow_id` to `CodeDbSyncPipeline.run`) and to `_run_repo_index` (kind `index_repo`, pass `wf_id=child.workflow_id` to `run_repo_index_task`).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/integration/test_daily_sync_child_runs.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd backend && .venv/bin/ruff check app/ && .venv/bin/mypy app/ --ignore-missing-imports
git add backend/app/services/daily_knowledge_sync_service.py backend/tests/integration/test_daily_sync_child_runs.py
git commit -m "feat(sync): daily-sync sub-operations create child IndexingRuns

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Retire `KnowledgeSyncRun`; sync-history reads `indexing_runs`

**Files:**
- Delete: `app/models/knowledge_sync_run.py`, `app/services/knowledge_sync_run_service.py`
- Modify: `app/models/__init__.py:20` (remove import)
- Modify: `app/api/routes/projects.py` (`project_sync_history:454`)
- Test: `tests/unit/api/test_sync_history_runs.py`

**Interfaces:**
- `GET /projects/{id}/sync-history?limit=` returns the last N `daily_sync` runs: `[{id, status, trigger, started_at, finished_at, duration_seconds, error, progress_pct}]`.

- [ ] **Step 1: Write the failing test**

`tests/unit/api/test_sync_history_runs.py`:

```python
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
import app.models  # noqa: F401
from app.services.run_coordinator import RunCoordinator
from app.services.sync_history_service import SyncHistoryService


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


async def test_sync_history_lists_daily_runs(session: AsyncSession):
    coord = RunCoordinator()
    run = await coord.start(session, kind="daily_sync", project_id="p", connection_id=None,
                            trigger="schedule")
    await coord.finish(run, "completed")
    rows = await SyncHistoryService().list_for_project(session, "p", limit=10)
    assert len(rows) == 1
    assert rows[0]["status"] == "completed"
    assert rows[0]["kind"] == "daily_sync"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/unit/api/test_sync_history_runs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.sync_history_service'`.

- [ ] **Step 3: Write minimal implementation**

Create `app/services/sync_history_service.py`:

```python
"""History of daily_sync runs (replaces KnowledgeSyncRunService)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.indexing_run import IndexingRun


class SyncHistoryService:
    async def list_for_project(self, session: AsyncSession, project_id: str, *, limit: int = 30) -> list[dict]:
        stmt = (
            select(IndexingRun)
            .where(IndexingRun.project_id == project_id, IndexingRun.kind == "daily_sync")
            .order_by(IndexingRun.created_at.desc())
            .limit(limit)
        )
        rows = (await session.execute(stmt)).scalars().all()
        out = []
        for r in rows:
            dur = None
            if r.started_at and r.finished_at:
                dur = (r.finished_at - r.started_at).total_seconds()
            out.append({
                "id": r.id, "kind": r.kind, "status": r.status, "trigger": r.trigger,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "duration_seconds": dur, "error": r.error, "progress_pct": r.progress_pct,
            })
        return out
```

Rewrite `project_sync_history` (projects.py:454) to use it:

```python
    from app.services.sync_history_service import SyncHistoryService

    rows = await SyncHistoryService().list_for_project(db, project_id, limit=limit)
    return rows
```

Delete `app/models/knowledge_sync_run.py` and `app/services/knowledge_sync_run_service.py`, and remove the import on `app/models/__init__.py:20`.

- [ ] **Step 4: Run test + confirm no dangling imports**

Run:
```bash
cd backend && .venv/bin/pytest tests/unit/api/test_sync_history_runs.py -v
.venv/bin/python -c "import app.main"  # must import cleanly (no KnowledgeSyncRun refs)
grep -rn "KnowledgeSyncRun\|knowledge_sync_run" app/ && echo "FOUND — remove" || echo "clean"
```
Expected: test PASS; `import app.main` succeeds; grep prints `clean`.

- [ ] **Step 5: Commit**

```bash
cd backend && .venv/bin/ruff check app/ && .venv/bin/mypy app/ --ignore-missing-imports
git add -A
git commit -m "refactor(sync): retire KnowledgeSyncRun; sync-history reads indexing_runs

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Per-project schedule endpoints + cron honors them + sync-now

**Files:**
- Modify: `app/api/routes/projects.py` (add 3 routes)
- Modify: `app/main.py` (`list_eligible_projects` consumer / wave honors per-project enable)
- Modify: `app/services/daily_knowledge_sync_service.py` (`list_eligible_projects` skips per-project disabled)
- Test: `tests/unit/api/test_sync_schedule.py`

**Interfaces:**
- `GET /projects/{id}/sync-schedule` → `{enabled, hour, timezone, source, next_run}` where `enabled`/`hour` fall back to the global `daily_knowledge_sync_*` when the project columns are NULL (`source` ∈ `project|global`).
- `PUT /projects/{id}/sync-schedule` body `{enabled: bool | None, hour: int | None}` (editor) → persists overrides.
- `POST /projects/{id}/sync-now` (editor) → enqueues/starts a `daily_sync` run for the project (trigger `manual`), returns `{run_id, workflow_id}`.
- `list_eligible_projects` excludes projects whose effective `enabled` is `False`.

- [ ] **Step 1: Write the failing test**

`tests/unit/api/test_sync_schedule.py`:

```python
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
import app.models  # noqa: F401
from app.models.project import Project
from app.services.sync_schedule_service import SyncScheduleService


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


async def test_effective_schedule_falls_back_to_global(session: AsyncSession):
    p = Project(id="p", name="x", owner_id="u")  # NULL overrides
    session.add(p)
    await session.commit()
    eff = await SyncScheduleService().effective(session, "p")
    assert eff["source"] == "global"
    assert "hour" in eff and "enabled" in eff


async def test_project_override_wins(session: AsyncSession):
    p = Project(id="p2", name="x", owner_id="u", sync_schedule_enabled=False, sync_schedule_hour=5)
    session.add(p)
    await session.commit()
    eff = await SyncScheduleService().effective(session, "p2")
    assert eff["enabled"] is False
    assert eff["hour"] == 5
    assert eff["source"] == "project"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/unit/api/test_sync_schedule.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.sync_schedule_service'`.

- [ ] **Step 3: Write minimal implementation**

Create `app/services/sync_schedule_service.py`:

```python
"""Effective per-project daily-sync schedule (project override → global default)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.project_service import ProjectService


class SyncScheduleService:
    def __init__(self) -> None:
        self._projects = ProjectService()

    async def effective(self, session: AsyncSession, project_id: str) -> dict:
        project = await self._projects.get(session, project_id)
        proj_enabled = getattr(project, "sync_schedule_enabled", None)
        proj_hour = getattr(project, "sync_schedule_hour", None)
        source = "project" if (proj_enabled is not None or proj_hour is not None) else "global"
        return {
            "enabled": proj_enabled if proj_enabled is not None else settings.daily_knowledge_sync_enabled,
            "hour": proj_hour if proj_hour is not None else settings.daily_knowledge_sync_hour,
            "timezone": settings.daily_knowledge_sync_timezone,
            "source": source,
        }
```

Add the three routes to `app/api/routes/projects.py` (after `project_sync_history`). Reads require `viewer`, writes/sync-now require `editor`. `sync-now` calls:

```python
    from app.core import task_queue

    if task_queue.is_arq_active():
        from app.services.daily_knowledge_sync_service import DailyKnowledgeSyncService  # noqa: F401
        # Create the run synchronously so the client gets ids, then enqueue execution.
        from app.services.run_coordinator import RunCoordinator
        run = await RunCoordinator().start(db, kind="daily_sync", project_id=project_id,
                                           connection_id=None, trigger="manual")
        await task_queue.enqueue("run_daily_project_knowledge_sync",
                                 task_id=f"daily_sync_manual:{project_id}", project_id=project_id)
        return {"run_id": run.id, "workflow_id": run.workflow_id}
    # in-process
    import asyncio
    from app.services.daily_knowledge_sync_service import DailyKnowledgeSyncService
    asyncio.create_task(DailyKnowledgeSyncService().run_for_project(project_id, trigger="manual"))
    return {"status": "started"}
```

> Note: when ARQ is active the worker's `run_daily_project_knowledge_sync` will call `run_for_project`, which itself calls `RunCoordinator.start` — to avoid a double parent run, `run_for_project` must adopt an existing active `daily_sync` run for the project if one is already `queued/running` (reuse instead of creating). Add that adoption at the top of `run_for_project`: query an active `daily_sync` run for the project and reuse it; only `start` a new one when none exists.

In `DailyKnowledgeSyncService.list_eligible_projects`, skip projects whose effective `enabled` is False:

```python
        from app.services.sync_schedule_service import SyncScheduleService

        sched = SyncScheduleService()
        ...
            eff = await sched.effective(session, project.id)
            if not eff["enabled"]:
                continue
```

- [ ] **Step 4: Run test + full P2 suite**

Run:
```bash
cd backend && .venv/bin/pytest tests/unit/api/test_sync_schedule.py tests/integration/test_daily_sync_run.py tests/integration/test_daily_sync_child_runs.py tests/unit/api/test_sync_history_runs.py -v
.venv/bin/ruff format app/ tests/ && .venv/bin/ruff check app/ tests/ && .venv/bin/mypy app/ --ignore-missing-imports
```
Expected: PASS; clean lint/types.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(sync): per-project schedule endpoints, sync-now, cron honors overrides

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:** daily_sync first-class run (§2.3, §5.3) → Tasks 2–3; retire `KnowledgeSyncRun` + history on `/runs` (greenfield) → Task 4; per-project schedule + sync-now (§5.5) → Tasks 1+5; freshness re-check in the `freshness_reconcile` step (§3 ML loop) → Task 2 (`_recheck_freshness`). ✓

**Placeholder scan:** Task 2 Step 3 specifies the `_run_for_project_inner` restructure with the phase-wrapping shape and the exact caller `finish`; the per-connection loop logic is preserved (not rewritten) and explicitly named. No `TBD`/`TODO`. The `_recheck_freshness` body = call `KnowledgeFreshnessService` recompute (no-op persistence) — concrete. ✓

**Type consistency:** `run_for_project(project_id, *, trigger=...)` consistent across worker/main/sync-now callers; child-run `wf_id=` threading matches P1's pipeline signatures; `SyncHistoryService.list_for_project`, `SyncScheduleService.effective` names consistent between definition and tests. ✓

**Risk flagged:** Task 5 ARQ `sync-now` + worker both reaching `run_for_project` requires the **adopt-existing-run** guard (specified) to avoid duplicate parent `daily_sync` runs. Verify the single-active partial index (P0) doesn't reject the adopted reuse — adoption reuses the existing row, it does not `start` a second.

---

## Execution Handoff

P2 complete. Depends on P0 + P1. **Next:** P3 (telemetry, error catalog, filterable logs API + TTL sweeps + metrics), P4 (agent-lifecycle observability), P5 (frontend).
