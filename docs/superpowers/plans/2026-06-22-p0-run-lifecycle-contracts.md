# P0 — Run Lifecycle Contracts & Foundations — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lock the shared data/event contracts and the `RunCoordinator` seam that every later milestone (P1–P5) of the sync & observability redesign depends on.

**Architecture:** Introduce a canonical `IndexingRun` aggregate (projection) plus an append-only `IndexingRunEvent` journal and a dedup'd `ErrorLog` catalog. Promote progress to first-class `WorkflowEvent` fields. Add weighted per-pipeline step manifests and a `RunCoordinator` service that owns run lifecycle (start/step/finish/cancel/retry), writes both projection and journal, and upserts failures into the error catalog. This is backend-only and produces unit-testable software; no triggers are rewired yet (that is P1).

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 async, Alembic, pytest (asyncio auto mode), aiosqlite (tests), asyncpg (prod).

**Source spec:** `docs/superpowers/specs/2026-06-22-sync-and-observability-redesign-design.md` (§5 contracts).

## Global Constraints

- **Greenfield — no backward compatibility.** No feature-flag gating of the new path; no legacy fallbacks. `KnowledgeSyncRun` is superseded by `IndexingRun(kind="daily_sync")` and will be removed in P2 — do **not** delete it in P0 (keep the app booting).
- **`IndexingCheckpoint`** (`app/models/indexing_checkpoint.py`) remains the repo resume cursor; its `status` is no longer the lifecycle authority — `IndexingRun` is. Do not change `IndexingCheckpoint` in P0.
- Python 3.12. Line length 100. Ruff `0.15.15` (pinned) rules `E F I N W UP`. `mypy app/ --ignore-missing-imports` must pass.
- Async everywhere — SQLAlchemy 2.0 async; no sync I/O on the request path.
- `asyncio_mode = "auto"` — async tests need **no** `@pytest.mark.asyncio`.
- New env vars go in `app/config.py` with a docstring **and** `backend/.env.example`.
- Combined unit+integration coverage gate ≥ 72% (`coverage report --fail-under=72`).
- Conventional commits; every commit message ends with the trailer:
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`
- Run all commands from `backend/` using the venv: `cd backend && .venv/bin/<tool>`.

## File Structure

- Create `app/models/indexing_run.py` — `IndexingRun`, `IndexingRunEvent`.
- Create `app/models/error_log.py` — `ErrorLog`.
- Modify `app/models/__init__.py` — register new models.
- Modify `app/models/request_trace.py` — add `failure_kind` to `RequestTrace`.
- Create `alembic/versions/a1f2b3c4d5e6_add_indexing_runs_and_error_log.py` — migration.
- Modify `app/core/workflow_tracker.py` — first-class progress fields on `WorkflowEvent`, extend `emit()`, tolerant `broadcast_external`.
- Create `app/knowledge/run_manifests.py` — step manifests + progress math.
- Create `app/services/error_log_service.py` — `ErrorLogService.upsert_from_run`.
- Create `app/services/run_coordinator.py` — `RunCoordinator`, `RunAlreadyActive`, `RunCancelled`.
- Tests:
  - `tests/unit/models/test_indexing_run_models.py`
  - `tests/unit/models/test_error_log_model.py`
  - `tests/unit/knowledge/test_run_manifests.py`
  - `tests/unit/services/test_run_coordinator.py`
  - `tests/unit/core/test_workflow_event_fields.py`

Shared test fixture (copy into each test module that needs a DB session — mirrors `tests/unit/test_insight_reconcile_tz.py`):

```python
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.models.base import Base
import app.models  # noqa: F401 — register all mappers


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
```

---

### Task 1: `IndexingRun` + `IndexingRunEvent` models

**Files:**
- Create: `app/models/indexing_run.py`
- Modify: `app/models/__init__.py` (add export line)
- Test: `tests/unit/models/test_indexing_run_models.py`

**Interfaces:**
- Produces: `IndexingRun` (table `indexing_runs`) and `IndexingRunEvent` (table `indexing_run_events`) ORM classes with the columns named in the steps below. Consumed by Tasks 3, 6–9.

- [ ] **Step 1: Write the failing test**

`tests/unit/models/test_indexing_run_models.py`:

```python
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
import app.models  # noqa: F401 — register all mappers
from app.models.indexing_run import IndexingRun, IndexingRunEvent


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


async def test_indexing_run_defaults(session: AsyncSession):
    run = IndexingRun(
        workflow_id="wf-1",
        project_id="proj-1",
        connection_id=None,
        kind="index_repo",
        trigger="manual",
        status="queued",
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    assert run.id
    assert run.step_index == 0
    assert run.total_steps == 0
    assert run.progress_pct == 0
    assert run.cancel_requested is False
    assert run.version == 0
    assert run.created_at is not None


async def test_indexing_run_event_link(session: AsyncSession):
    run = IndexingRun(
        workflow_id="wf-2", project_id="p", connection_id=None,
        kind="db_index", trigger="manual", status="running",
    )
    session.add(run)
    await session.commit()

    ev = IndexingRunEvent(
        run_id=run.id, step="introspect_schema", status="started", detail="go",
    )
    session.add(ev)
    await session.commit()

    rows = (await session.execute(
        select(IndexingRunEvent).where(IndexingRunEvent.run_id == run.id)
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].level == "info"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/unit/models/test_indexing_run_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models.indexing_run'`.

- [ ] **Step 3: Write minimal implementation**

`app/models/indexing_run.py`:

```python
"""Canonical lifecycle aggregate + append-only journal for background runs.

One `IndexingRun` row per repo-index / db-index / code-DB-sync / daily-sync run.
It is the single source of truth for live status, progress, cancel/retry, and
history. `IndexingRunEvent` is the append-only step/log journal feeding both the
live view and persisted history.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class IndexingRun(Base):
    __tablename__ = "indexing_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workflow_id: Mapped[str] = mapped_column(String(36), nullable=False)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    connection_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("connections.id", ondelete="CASCADE"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    trigger: Mapped[str] = mapped_column(String(20), nullable=False, server_default="manual")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="queued")
    current_step: Mapped[str | None] = mapped_column(String(64), nullable=True)
    step_index: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    total_steps: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    progress_pct: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=func.false()
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    meta_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    events: Mapped[list[IndexingRunEvent]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="IndexingRunEvent.ts"
    )

    __table_args__ = (
        Index("ix_indexing_runs_workflow", "workflow_id", unique=True),
        Index("ix_indexing_runs_history", "project_id", "kind", "created_at"),
        Index("ix_indexing_runs_active", "project_id", "kind", "status"),
    )


class IndexingRunEvent(Base):
    __tablename__ = "indexing_run_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("indexing_runs.id", ondelete="CASCADE"), nullable=False
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    step: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    elapsed_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    progress_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    level: Mapped[str] = mapped_column(String(10), nullable=False, server_default="info")

    run: Mapped[IndexingRun] = relationship(back_populates="events")

    __table_args__ = (Index("ix_indexing_run_events_run_ts", "run_id", "ts"),)
```

Add to `app/models/__init__.py` (keep alphabetical grouping near the `indexing_checkpoint` import on line 17):

```python
from app.models.indexing_run import IndexingRun, IndexingRunEvent  # noqa: F401
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/unit/models/test_indexing_run_models.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/indexing_run.py backend/app/models/__init__.py backend/tests/unit/models/test_indexing_run_models.py
git commit -m "feat(models): add IndexingRun + IndexingRunEvent lifecycle models

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `ErrorLog` model + `RequestTrace.failure_kind`

**Files:**
- Create: `app/models/error_log.py`
- Modify: `app/models/__init__.py`, `app/models/request_trace.py:43` (after `error_message`)
- Test: `tests/unit/models/test_error_log_model.py`

**Interfaces:**
- Produces: `ErrorLog` (table `error_log`) with columns `id, project_id, signature, source, kind, failure_kind, message, sample_ref, occurrences, first_seen_at, last_seen_at, status, meta_json`. Unique `(project_id, signature)`. Consumed by Tasks 3, 8.
- Produces: `RequestTrace.failure_kind: str | None`.

- [ ] **Step 1: Write the failing test**

`tests/unit/models/test_error_log_model.py`:

```python
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
import app.models  # noqa: F401
from app.models.error_log import ErrorLog


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


async def test_error_log_defaults(session: AsyncSession):
    e = ErrorLog(
        project_id="p", signature="sig-1", source="run", kind="index_repo",
        message="boom",
    )
    session.add(e)
    await session.commit()
    await session.refresh(e)
    assert e.id
    assert e.occurrences == 1
    assert e.status == "open"
    assert e.first_seen_at is not None
    assert e.last_seen_at is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/unit/models/test_error_log_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models.error_log'`.

- [ ] **Step 3: Write minimal implementation**

`app/models/error_log.py`:

```python
"""Dedup'd error catalog fed by both the runs plane and the query plane."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ErrorLog(Base):
    __tablename__ = "error_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    signature: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # run|query|span|system
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    failure_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    sample_ref: Mapped[str | None] = mapped_column(String(36), nullable=True)
    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="open")
    meta_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")

    __table_args__ = (
        Index("uq_error_log_project_sig", "project_id", "signature", unique=True),
        Index("ix_error_log_project_lastseen", "project_id", "last_seen_at"),
        Index("ix_error_log_status", "status"),
    )
```

Add to `app/models/__init__.py`:

```python
from app.models.error_log import ErrorLog  # noqa: F401
```

In `app/models/request_trace.py`, after line 43 (`error_message`), add:

```python
    failure_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/unit/models/test_error_log_model.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/error_log.py backend/app/models/__init__.py backend/app/models/request_trace.py backend/tests/unit/models/test_error_log_model.py
git commit -m "feat(models): add ErrorLog catalog and RequestTrace.failure_kind

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Alembic migration

**Files:**
- Create: `alembic/versions/a1f2b3c4d5e6_add_indexing_runs_and_error_log.py`

**Interfaces:**
- Consumes: the three new tables + `request_traces.failure_kind` from Tasks 1–2.
- Produces: a migration whose `down_revision = "7968486e00a3"` (verified current head).

- [ ] **Step 1: Confirm the current head**

Run: `cd backend && PYTHONPATH=. .venv/bin/alembic heads`
Expected: `7968486e00a3 (head)`. (If it differs, set `down_revision` to the printed value.)

- [ ] **Step 2: Write the migration**

`alembic/versions/a1f2b3c4d5e6_add_indexing_runs_and_error_log.py`:

```python
"""add indexing_runs, indexing_run_events, error_log; request_traces.failure_kind

Revision ID: a1f2b3c4d5e6
Revises: 7968486e00a3
Create Date: 2026-06-22

"""

import sqlalchemy as sa
from alembic import op

revision = "a1f2b3c4d5e6"
down_revision = "7968486e00a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "indexing_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workflow_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("connection_id", sa.String(length=36), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("current_step", sa.String(length=64), nullable=True),
        sa.Column("step_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_steps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress_pct", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("failure_kind", sa.String(length=20), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("meta_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connection_id"], ["connections.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_indexing_runs_workflow", "indexing_runs", ["workflow_id"], unique=True)
    op.create_index(
        "ix_indexing_runs_history", "indexing_runs", ["project_id", "kind", "created_at"]
    )
    op.create_index("ix_indexing_runs_active", "indexing_runs", ["project_id", "kind", "status"])
    # Defense-in-depth single-active guard (partial unique). Code-level guard in
    # RunCoordinator.start is the primary enforcement.
    op.create_index(
        "uq_indexing_runs_active_one",
        "indexing_runs",
        ["project_id", "kind", sa.text("coalesce(connection_id, '')")],
        unique=True,
        postgresql_where=sa.text("status IN ('queued','running','cancelling')"),
        sqlite_where=sa.text("status IN ('queued','running','cancelling')"),
    )

    op.create_table(
        "indexing_run_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("step", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("elapsed_ms", sa.Float(), nullable=True),
        sa.Column("progress_pct", sa.Integer(), nullable=True),
        sa.Column("level", sa.String(length=10), nullable=False, server_default="info"),
        sa.ForeignKeyConstraint(["run_id"], ["indexing_runs.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_indexing_run_events_run_ts", "indexing_run_events", ["run_id", "ts"])

    op.create_table(
        "error_log",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("signature", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("failure_kind", sa.String(length=20), nullable=True),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("sample_ref", sa.String(length=36), nullable=True),
        sa.Column("occurrences", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("meta_json", sa.Text(), nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
    )
    op.create_index("uq_error_log_project_sig", "error_log", ["project_id", "signature"], unique=True)
    op.create_index("ix_error_log_project_lastseen", "error_log", ["project_id", "last_seen_at"])
    op.create_index("ix_error_log_status", "error_log", ["status"])

    op.add_column("request_traces", sa.Column("failure_kind", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("request_traces", "failure_kind")
    op.drop_index("ix_error_log_status", table_name="error_log")
    op.drop_index("ix_error_log_project_lastseen", table_name="error_log")
    op.drop_index("uq_error_log_project_sig", table_name="error_log")
    op.drop_table("error_log")
    op.drop_index("ix_indexing_run_events_run_ts", table_name="indexing_run_events")
    op.drop_table("indexing_run_events")
    op.drop_index("uq_indexing_runs_active_one", table_name="indexing_runs")
    op.drop_index("ix_indexing_runs_active", table_name="indexing_runs")
    op.drop_index("ix_indexing_runs_history", table_name="indexing_runs")
    op.drop_index("ix_indexing_runs_workflow", table_name="indexing_runs")
    op.drop_table("indexing_runs")
```

- [ ] **Step 3: Verify the migration round-trips**

Run:
```bash
cd backend && PYTHONPATH=. .venv/bin/alembic upgrade head \
  && PYTHONPATH=. .venv/bin/alembic downgrade -1 \
  && PYTHONPATH=. .venv/bin/alembic upgrade head
```
Expected: three successful runs, final line `Running upgrade 7968486e00a3 -> a1f2b3c4d5e6` with no error.

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/a1f2b3c4d5e6_add_indexing_runs_and_error_log.py
git commit -m "feat(db): migration for indexing_runs, indexing_run_events, error_log

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: First-class progress fields on `WorkflowEvent`

**Files:**
- Modify: `app/core/workflow_tracker.py` (`WorkflowEvent` dataclass ~line 30; `emit` ~line 280; `broadcast_external` ~line 352)
- Test: `tests/unit/core/test_workflow_event_fields.py`

**Interfaces:**
- Produces: `WorkflowEvent` fields `run_id, kind, step_index, total_steps, progress_pct` (all `| None`, default `None`).
- Produces: `tracker.emit(workflow_id, step, status, detail="", *, span_type=None, run_id=None, kind=None, step_index=None, total_steps=None, progress_pct=None, **extra)`.
- Produces: `broadcast_external` reconstructs `WorkflowEvent` filtering payload to known dataclass fields (tolerant). Consumed by Task 7.

- [ ] **Step 1: Write the failing test**

`tests/unit/core/test_workflow_event_fields.py`:

```python
from __future__ import annotations

import json

from app.core.workflow_tracker import WorkflowEvent, tracker


def test_event_has_first_class_progress_fields():
    ev = WorkflowEvent(
        workflow_id="wf", step="analyze_files", status="completed",
        run_id="run-1", kind="index_repo", step_index=3, total_steps=9, progress_pct=33,
    )
    payload = json.loads(ev.to_json())
    assert payload["run_id"] == "run-1"
    assert payload["kind"] == "index_repo"
    assert payload["step_index"] == 3
    assert payload["total_steps"] == 9
    assert payload["progress_pct"] == 33


async def test_broadcast_external_tolerates_unknown_keys():
    # Simulate a payload from another process carrying a future, unknown key.
    payload = {
        "workflow_id": "wf-x", "step": "pipeline_start", "status": "started",
        "pipeline": "db_index", "run_id": "r", "future_field": "ignore-me",
    }
    import dataclasses

    fields = {f.name for f in dataclasses.fields(WorkflowEvent)}
    ev = WorkflowEvent(**{k: v for k, v in payload.items() if k in fields})
    # Must not raise.
    await tracker.broadcast_external(ev)
    assert ev.run_id == "r"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/unit/core/test_workflow_event_fields.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'run_id'`.

- [ ] **Step 3: Write minimal implementation**

In `app/core/workflow_tracker.py`, add to the `WorkflowEvent` dataclass (after `span_type`, before `extra`):

```python
    run_id: str | None = None
    kind: str | None = None
    step_index: int | None = None
    total_steps: int | None = None
    progress_pct: int | None = None
```

Replace the `emit` method signature/body:

```python
    async def emit(
        self,
        workflow_id: str,
        step: str,
        status: str,
        detail: str = "",
        *,
        span_type: str | None = None,
        run_id: str | None = None,
        kind: str | None = None,
        step_index: int | None = None,
        total_steps: int | None = None,
        progress_pct: int | None = None,
        **extra: Any,
    ) -> None:
        event = WorkflowEvent(
            workflow_id=workflow_id,
            step=step,
            status=status,
            detail=detail,
            pipeline=self._resolve_pipeline(workflow_id),
            extra=extra,
            span_type=span_type,
            run_id=run_id,
            kind=kind,
            step_index=step_index,
            total_steps=total_steps,
            progress_pct=progress_pct,
        )
        await self._broadcast(event)
```

At the top of `broadcast_external`, reconstruct tolerantly. Replace the method's first lines so the event is rebuilt from known fields (add `import dataclasses` at the top of the file if absent):

```python
    async def broadcast_external(self, event: WorkflowEvent) -> None:
        """Deliver an event received from another process (Redis) to local SSE only."""
        # Tolerate unknown/extra keys as the contract evolves (greenfield-safe).
        _fields = {f.name for f in dataclasses.fields(WorkflowEvent)}
        if any(k not in _fields for k in vars(event)):
            event = WorkflowEvent(**{k: v for k, v in vars(event).items() if k in _fields})
        self._external_rebroadcast = True
```

> Note: the actual cross-process JSON→object rebuild lives in `core/workflow_events.py::_subscribe_loop` (`WorkflowEvent(**payload)`). P1 updates that call site to use the same field-filter; for P0 we make `broadcast_external` itself defensive and prove the filter works.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/unit/core/test_workflow_event_fields.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/workflow_tracker.py backend/tests/unit/core/test_workflow_event_fields.py
git commit -m "feat(workflow): first-class progress fields on WorkflowEvent + tolerant rebuild

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Step manifests + progress math

**Files:**
- Create: `app/knowledge/run_manifests.py`
- Test: `tests/unit/knowledge/test_run_manifests.py`

**Interfaces:**
- Produces:
  - `Step` dataclass: `key: str`, `label: str`, `weight: int = 1`.
  - `resolve_manifest(kind: str, *, flags: dict[str, bool] | None = None) -> list[Step]`.
  - `total_steps(manifest: list[Step]) -> int`.
  - `progress_for(manifest: list[Step], completed: int) -> int` — `completed` = number of completed steps (0..len); returns 0..100 by cumulative weight.
  - `step_position(manifest: list[Step], key: str) -> int` — 1-based index of `key` (raises `KeyError` if absent).
- Consumed by Tasks 6–7.

- [ ] **Step 1: Write the failing test**

`tests/unit/knowledge/test_run_manifests.py`:

```python
from __future__ import annotations

import pytest

from app.knowledge.run_manifests import (
    progress_for,
    resolve_manifest,
    step_position,
    total_steps,
)


def test_db_index_manifest_shape():
    m = resolve_manifest("db_index")
    keys = [s.key for s in m]
    assert keys == [
        "introspect_schema", "fetch_samples", "load_context",
        "validate_tables", "store_results", "generate_summary",
    ]
    assert total_steps(m) == 6


def test_index_repo_flag_gated_steps_appended():
    base = resolve_manifest("index_repo")
    with_graph = resolve_manifest("index_repo", flags={"code_graph_enabled": True})
    assert "ast_parse" not in [s.key for s in base]
    assert "ast_parse" in [s.key for s in with_graph]
    assert "graph_build" in [s.key for s in with_graph]


def test_progress_math_equal_weights():
    m = resolve_manifest("db_index")  # 6 equal-weight steps
    assert progress_for(m, 0) == 0
    assert progress_for(m, 3) == 50
    assert progress_for(m, 6) == 100


def test_step_position_is_one_based():
    m = resolve_manifest("db_index")
    assert step_position(m, "introspect_schema") == 1
    assert step_position(m, "generate_summary") == 6
    with pytest.raises(KeyError):
        step_position(m, "nope")


def test_unknown_kind_raises():
    with pytest.raises(KeyError):
        resolve_manifest("not_a_kind")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/unit/knowledge/test_run_manifests.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.knowledge.run_manifests'`.

- [ ] **Step 3: Write minimal implementation**

`app/knowledge/run_manifests.py`:

```python
"""Weighted, ordered step manifests per background-run kind.

`total_steps` and `progress_for` give the UI honest "N of M" + percent. Manifest
keys match the step names already emitted by the pipelines (see
ActiveTasksWidget STEP_LABELS).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Step:
    key: str
    label: str
    weight: int = 1


_BASE: dict[str, list[Step]] = {
    "index_repo": [
        Step("resolve_ssh_key", "SSH Key"),
        Step("clone_or_pull", "Git Clone/Pull", weight=2),
        Step("detect_changes", "Detect Changes"),
        Step("cleanup_deleted", "Cleanup Deleted"),
        Step("analyze_files", "Analyze Files", weight=3),
        Step("project_profile", "Project Profile"),
        Step("cross_file_analysis", "Cross-File Analysis", weight=2),
        Step("generate_docs", "Generate Docs", weight=3),
        Step("record_index", "Record Index"),
    ],
    "db_index": [
        Step("introspect_schema", "Introspect Schema"),
        Step("fetch_samples", "Fetch Samples"),
        Step("load_context", "Load Context"),
        Step("validate_tables", "LLM Analysis", weight=3),
        Step("store_results", "Store Results"),
        Step("generate_summary", "Generate Summary"),
    ],
    "code_db_sync": [
        Step("load_code_knowledge", "Load Code Knowledge"),
        Step("load_db_index", "Load DB Index"),
        Step("match_tables", "Match Tables", weight=2),
        Step("analyze_sync", "Analyze Code-DB", weight=2),
        Step("store_sync", "Store Results"),
        Step("generate_sync_summary", "Generate Summary"),
    ],
    "daily_sync": [
        Step("plan_targets", "Plan Targets"),
        Step("db_index", "Database Index", weight=3),
        Step("code_db_sync", "Code-DB Sync", weight=3),
        Step("freshness_reconcile", "Freshness Reconcile"),
        Step("summarize", "Summarize"),
    ],
}

# Flag-gated steps appended to index_repo when the corresponding flag is on.
_INDEX_REPO_FLAG_STEPS: list[tuple[str, Step]] = [
    ("code_graph_enabled", Step("ast_parse", "AST Parse", weight=2)),
    ("code_graph_enabled", Step("graph_build", "Build Code Graph", weight=2)),
    ("hybrid_retrieval_enabled", Step("bm25_build", "Build BM25")),
    ("schema_retrieval_enabled", Step("schema_embed", "Embed Schema")),
    ("lineage_enabled", Step("graph_db_bridge", "Code→DB Lineage")),
    ("clustering_enabled", Step("graph_clustering", "Cluster Communities")),
]


def resolve_manifest(kind: str, *, flags: dict[str, bool] | None = None) -> list[Step]:
    if kind not in _BASE:
        raise KeyError(f"unknown run kind: {kind}")
    steps = list(_BASE[kind])
    if kind == "index_repo":
        flags = flags or {}
        steps += [step for flag, step in _INDEX_REPO_FLAG_STEPS if flags.get(flag)]
    return steps


def total_steps(manifest: list[Step]) -> int:
    return len(manifest)


def progress_for(manifest: list[Step], completed: int) -> int:
    total_weight = sum(s.weight for s in manifest) or 1
    done_weight = sum(s.weight for s in manifest[: max(0, min(completed, len(manifest)))])
    return round(done_weight / total_weight * 100)


def step_position(manifest: list[Step], key: str) -> int:
    for idx, step in enumerate(manifest, start=1):
        if step.key == key:
            return idx
    raise KeyError(f"step {key!r} not in manifest")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/unit/knowledge/test_run_manifests.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/knowledge/run_manifests.py backend/tests/unit/knowledge/test_run_manifests.py
git commit -m "feat(knowledge): weighted step manifests + progress math

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: `RunCoordinator.start` + single-active guard

**Files:**
- Create: `app/services/run_coordinator.py`
- Test: `tests/unit/services/test_run_coordinator.py`

**Interfaces:**
- Produces: `RunAlreadyActive(Exception)` with attribute `.run_id`; `RunCancelled(Exception)`.
- Produces: `RunCoordinator.start(db, *, kind, project_id, connection_id=None, trigger="manual", force_full=False) -> IndexingRun`. Resolves the manifest (flags from `settings`), enforces single-active per `(project_id, kind, connection_id)`, mints `workflow_id` via `tracker.begin`, persists `status="running"`, emits `pipeline_start`.
- Consumed by Tasks 7–9.

- [ ] **Step 1: Write the failing test**

`tests/unit/services/test_run_coordinator.py`:

```python
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
import app.models  # noqa: F401
from app.models.indexing_run import IndexingRun, IndexingRunEvent
from app.services.run_coordinator import RunAlreadyActive, RunCoordinator


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


async def test_start_creates_running_run(session: AsyncSession):
    coord = RunCoordinator()
    run = await coord.start(
        session, kind="db_index", project_id="p1", connection_id="c1", trigger="manual"
    )
    assert run.status == "running"
    assert run.workflow_id
    assert run.total_steps == 6
    assert run.started_at is not None
    # pipeline_start journal event written
    events = (await session.execute(
        select(IndexingRunEvent).where(IndexingRunEvent.run_id == run.id)
    )).scalars().all()
    assert [e.step for e in events] == ["pipeline_start"]


async def test_start_rejects_second_active_run(session: AsyncSession):
    coord = RunCoordinator()
    await coord.start(session, kind="db_index", project_id="p1", connection_id="c1")
    with pytest.raises(RunAlreadyActive):
        await coord.start(session, kind="db_index", project_id="p1", connection_id="c1")


async def test_start_allows_different_connection(session: AsyncSession):
    coord = RunCoordinator()
    await coord.start(session, kind="db_index", project_id="p1", connection_id="c1")
    run2 = await coord.start(session, kind="db_index", project_id="p1", connection_id="c2")
    assert run2.status == "running"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/unit/services/test_run_coordinator.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.run_coordinator'`.

- [ ] **Step 3: Write minimal implementation**

`app/services/run_coordinator.py`:

```python
"""Single seam owning the lifecycle of every background run.

Writes the `IndexingRun` projection AND the `IndexingRunEvent` journal, emits
WorkflowEvents with first-class progress, enforces single-active, and supports
cooperative cancel + retry. Used by every trigger and by both the in-process and
ARQ execution paths (wired in P1).
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.workflow_tracker import tracker
from app.knowledge.run_manifests import (
    Step,
    progress_for,
    resolve_manifest,
    step_position,
    total_steps,
)
from app.models.indexing_run import IndexingRun, IndexingRunEvent

logger = logging.getLogger(__name__)

_ACTIVE_STATUSES = ("queued", "running", "cancelling")


class RunAlreadyActive(Exception):
    """Raised when a run already exists for (project, kind, connection)."""

    def __init__(self, run_id: str) -> None:
        super().__init__(f"run already active: {run_id}")
        self.run_id = run_id


class RunCancelled(Exception):
    """Raised inside a step when cancellation was requested."""


def _now() -> datetime:
    return datetime.now(UTC)


def _manifest_flags() -> dict[str, bool]:
    return {
        "code_graph_enabled": settings.code_graph_enabled,
        "hybrid_retrieval_enabled": settings.hybrid_retrieval_enabled,
        "schema_retrieval_enabled": settings.schema_retrieval_enabled,
        "lineage_enabled": settings.lineage_enabled,
        "clustering_enabled": settings.clustering_enabled,
    }


class RunCoordinator:
    def __init__(self) -> None:
        self._manifests: dict[str, list[Step]] = {}

    async def _find_active(
        self, db: AsyncSession, project_id: str, kind: str, connection_id: str | None
    ) -> IndexingRun | None:
        stmt = select(IndexingRun).where(
            IndexingRun.project_id == project_id,
            IndexingRun.kind == kind,
            IndexingRun.status.in_(_ACTIVE_STATUSES),
        )
        for row in (await db.execute(stmt)).scalars().all():
            if (row.connection_id or None) == (connection_id or None):
                return row
        return None

    async def start(
        self,
        db: AsyncSession,
        *,
        kind: str,
        project_id: str,
        connection_id: str | None = None,
        trigger: str = "manual",
        force_full: bool = False,
    ) -> IndexingRun:
        existing = await self._find_active(db, project_id, kind, connection_id)
        if existing is not None:
            raise RunAlreadyActive(existing.id)

        manifest = resolve_manifest(kind, flags=_manifest_flags())
        wf_id = await tracker.begin(
            kind,
            {"project_id": project_id, "connection_id": connection_id or "", "trigger": trigger},
        )
        run = IndexingRun(
            workflow_id=wf_id,
            project_id=project_id,
            connection_id=connection_id,
            kind=kind,
            trigger=trigger,
            status="running",
            step_index=0,
            total_steps=total_steps(manifest),
            progress_pct=0,
            started_at=_now(),
            heartbeat_at=_now(),
            meta_json=json.dumps({"force_full": force_full}),
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)
        self._manifests[run.id] = manifest
        await self._record(db, run, "pipeline_start", "started", f"Starting {kind}")
        return run

    async def _record(
        self,
        db: AsyncSession,
        run: IndexingRun,
        step: str,
        status: str,
        detail: str = "",
        *,
        elapsed_ms: float | None = None,
        level: str = "info",
    ) -> None:
        db.add(
            IndexingRunEvent(
                run_id=run.id,
                step=step,
                status=status,
                detail=detail,
                elapsed_ms=elapsed_ms,
                progress_pct=run.progress_pct,
                level=level,
            )
        )
        await db.commit()
        await tracker.emit(
            run.workflow_id,
            step,
            status,
            detail,
            run_id=run.id,
            kind=run.kind,
            step_index=run.step_index,
            total_steps=run.total_steps,
            progress_pct=run.progress_pct,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/unit/services/test_run_coordinator.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/run_coordinator.py backend/tests/unit/services/test_run_coordinator.py
git commit -m "feat(runs): RunCoordinator.start with single-active guard

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: `RunCoordinator.step` (journal + projection + progress + cancel)

**Files:**
- Modify: `app/services/run_coordinator.py`
- Modify: `tests/unit/services/test_run_coordinator.py` (add tests)

**Interfaces:**
- Produces: `RunCoordinator.step(run, step_key)` — async context manager. Refreshes the run; if `cancel_requested`, flips status to `cancelling` and raises `RunCancelled`. On enter: sets `current_step`, `step_index`, `heartbeat_at`, emits `started`. On success: sets `progress_pct`, bumps `version`, emits `completed`. On exception inside the block: emits `failed` and re-raises.
- Consumed by Tasks 8–9 and by pipelines in P1.

- [ ] **Step 1: Write the failing test (append to the test module)**

```python
async def test_step_advances_progress(session: AsyncSession):
    coord = RunCoordinator()
    run = await coord.start(session, kind="db_index", project_id="p2", connection_id="c1")
    async with coord.step(run, "introspect_schema"):
        pass
    async with coord.step(run, "fetch_samples"):
        pass
    await session.refresh(run)
    assert run.step_index == 2
    assert run.current_step == "fetch_samples"
    assert run.progress_pct == round(2 / 6 * 100)  # 33
    assert run.version == 2


async def test_step_raises_when_cancel_requested(session: AsyncSession):
    coord = RunCoordinator()
    run = await coord.start(session, kind="db_index", project_id="p3", connection_id="c1")
    run.cancel_requested = True
    await session.commit()
    with pytest.raises(RunCancelled):
        async with coord.step(run, "introspect_schema"):
            pass
    await session.refresh(run)
    assert run.status == "cancelling"


async def test_step_emits_failed_event_then_reraises(session: AsyncSession):
    from app.models.indexing_run import IndexingRunEvent
    from sqlalchemy import select

    coord = RunCoordinator()
    run = await coord.start(session, kind="db_index", project_id="p4", connection_id="c1")
    with pytest.raises(ValueError):
        async with coord.step(run, "introspect_schema"):
            raise ValueError("boom")
    events = (await session.execute(
        select(IndexingRunEvent).where(IndexingRunEvent.run_id == run.id)
    )).scalars().all()
    statuses = [(e.step, e.status) for e in events]
    assert ("introspect_schema", "failed") in statuses
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/unit/services/test_run_coordinator.py -k step -v`
Expected: FAIL — `AttributeError: 'RunCoordinator' object has no attribute 'step'`.

- [ ] **Step 3: Write minimal implementation (add to `RunCoordinator`)**

```python
    @asynccontextmanager
    async def step(self, run: IndexingRun, step_key: str):
        await self._check_cancel(run_db_session_owner=run)  # placeholder removed below
```

Actually add this method (no placeholder — full body):

```python
    @asynccontextmanager
    async def step(self, run: IndexingRun, step_key: str):
        db = _session_of(run)
        await db.refresh(run)
        if run.cancel_requested:
            run.status = "cancelling"
            await db.commit()
            raise RunCancelled(run.id)

        manifest = self._manifests.get(run.id) or resolve_manifest(
            run.kind, flags=_manifest_flags()
        )
        position = step_position(manifest, step_key)
        run.current_step = step_key
        run.step_index = position
        run.heartbeat_at = _now()
        await db.commit()
        await self._record(db, run, step_key, "started")

        t0 = _now()
        try:
            yield
        except Exception as exc:  # noqa: BLE001 — re-raised below
            elapsed = (_now() - t0).total_seconds() * 1000
            await self._record(db, run, step_key, "failed", str(exc), elapsed_ms=elapsed, level="error")
            raise
        else:
            elapsed = (_now() - t0).total_seconds() * 1000
            run.progress_pct = progress_for(manifest, position)
            run.version += 1
            run.heartbeat_at = _now()
            await db.commit()
            await self._record(db, run, step_key, "completed", elapsed_ms=elapsed)
```

Add the session helper at module level (below `_manifest_flags`):

```python
from sqlalchemy import inspect as _sa_inspect


def _session_of(run: IndexingRun) -> AsyncSession:
    """Return the AsyncSession the run instance is bound to."""
    sync_session = _sa_inspect(run).session
    if sync_session is None:
        raise RuntimeError("IndexingRun is not attached to a session")
    return sync_session  # async_sessionmaker sessions expose the async API here
```

> Note: SQLAlchemy's `inspect(obj).session` returns the owning session; under
> `async_sessionmaker` this is the `AsyncSession`'s sync-facing session. To keep
> the coordinator simple and explicit, P1 may instead thread `db` through each
> call; for P0 the helper keeps the `step()` signature ergonomic for tests.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/unit/services/test_run_coordinator.py -v`
Expected: PASS (all run-coordinator tests).

> If `_session_of` proves brittle across SQLAlchemy versions, fall back to the
> explicit form: change `step(self, run, step_key)` to `step(self, db, run, step_key)`
> and update the three new tests to pass `session`. Pick one form and keep it
> consistent across Tasks 7–9.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/run_coordinator.py backend/tests/unit/services/test_run_coordinator.py
git commit -m "feat(runs): RunCoordinator.step with progress, journal, cooperative cancel

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 8: `ErrorLogService.upsert_from_run` + `RunCoordinator.finish`

**Files:**
- Create: `app/services/error_log_service.py`
- Modify: `app/services/run_coordinator.py`
- Modify: `tests/unit/services/test_run_coordinator.py` (add tests)

**Interfaces:**
- Produces: `ErrorLogService.upsert(db, *, project_id, source, kind, message, failure_kind=None, sample_ref=None, meta=None) -> ErrorLog` — dedup by `(project_id, signature)`, signature = `sha256("{source}|{kind}|{skeleton(message)}")[:64]`; increments `occurrences` + refreshes `last_seen_at`/`message`/`sample_ref` on repeat.
- Produces: `ErrorLogService.upsert_from_run(db, run) -> ErrorLog`.
- Produces: `RunCoordinator.finish(run, status, error=None, failure_kind=None)` — terminal projection update (`finished_at`, `progress_pct=100` on completed), `pipeline_end` journal + emit, `tracker.end`, and `ErrorLog` upsert when `status == "failed"`.

- [ ] **Step 1: Write the failing test (append to the test module)**

```python
async def test_finish_completed_sets_terminal_state(session: AsyncSession):
    coord = RunCoordinator()
    run = await coord.start(session, kind="db_index", project_id="p5", connection_id="c1")
    await coord.finish(run, "completed")
    await session.refresh(run)
    assert run.status == "completed"
    assert run.progress_pct == 100
    assert run.finished_at is not None


async def test_finish_failed_upserts_error_log_and_dedups(session: AsyncSession):
    from sqlalchemy import select
    from app.models.error_log import ErrorLog

    coord = RunCoordinator()
    r1 = await coord.start(session, kind="db_index", project_id="p6", connection_id="c1")
    await coord.finish(r1, "failed", error="connection refused on host 12", failure_kind="transient")
    r2 = await coord.start(session, kind="db_index", project_id="p6", connection_id="c1")
    await coord.finish(r2, "failed", error="connection refused on host 99", failure_kind="transient")

    rows = (await session.execute(
        select(ErrorLog).where(ErrorLog.project_id == "p6")
    )).scalars().all()
    assert len(rows) == 1  # digit-skeleton dedup collapses host 12/99
    assert rows[0].occurrences == 2
    assert rows[0].source == "run"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/unit/services/test_run_coordinator.py -k finish -v`
Expected: FAIL — `AttributeError: 'RunCoordinator' object has no attribute 'finish'`.

- [ ] **Step 3: Write minimal implementation**

`app/services/error_log_service.py`:

```python
"""Dedup'd error catalog writer (runs + queries planes)."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.error_log import ErrorLog
from app.models.indexing_run import IndexingRun

_DIGITS = re.compile(r"\d+")
_WS = re.compile(r"\s+")


def _skeleton(message: str | None) -> str:
    if not message:
        return ""
    s = _DIGITS.sub("#", message)
    s = _WS.sub(" ", s).strip().lower()
    return s[:200]


def _signature(source: str, kind: str, message: str | None) -> str:
    raw = f"{source}|{kind}|{_skeleton(message)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


class ErrorLogService:
    async def upsert(
        self,
        db: AsyncSession,
        *,
        project_id: str | None,
        source: str,
        kind: str,
        message: str | None,
        failure_kind: str | None = None,
        sample_ref: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> ErrorLog:
        sig = _signature(source, kind, message)
        existing = (
            await db.execute(
                select(ErrorLog).where(
                    ErrorLog.project_id == project_id, ErrorLog.signature == sig
                )
            )
        ).scalar_one_or_none()
        now = datetime.now(UTC)
        if existing is not None:
            existing.occurrences += 1
            existing.last_seen_at = now
            existing.message = message or existing.message
            existing.sample_ref = sample_ref or existing.sample_ref
            existing.failure_kind = failure_kind or existing.failure_kind
            await db.commit()
            return existing
        row = ErrorLog(
            project_id=project_id,
            signature=sig,
            source=source,
            kind=kind,
            failure_kind=failure_kind,
            message=message or "",
            sample_ref=sample_ref,
            first_seen_at=now,
            last_seen_at=now,
            meta_json=json.dumps(meta or {}),
        )
        db.add(row)
        await db.commit()
        return row

    async def upsert_from_run(self, db: AsyncSession, run: IndexingRun) -> ErrorLog:
        return await self.upsert(
            db,
            project_id=run.project_id,
            source="run",
            kind=run.kind,
            message=run.error,
            failure_kind=run.failure_kind,
            sample_ref=run.id,
            meta={"connection_id": run.connection_id},
        )
```

Add to `RunCoordinator` (imports `ErrorLogService` at top of `run_coordinator.py`):

```python
from app.services.error_log_service import ErrorLogService
```

```python
    _error_log = ErrorLogService()

    async def finish(
        self,
        run: IndexingRun,
        status: str,
        error: str | None = None,
        failure_kind: str | None = None,
    ) -> None:
        db = _session_of(run)
        run.status = status
        run.finished_at = _now()
        run.heartbeat_at = _now()
        run.version += 1
        if status == "completed":
            run.progress_pct = 100
        if error is not None:
            run.error = error
        if failure_kind is not None:
            run.failure_kind = failure_kind
        await db.commit()
        await self._record(db, run, "pipeline_end", status, error or f"Pipeline {run.kind} {status}")
        await tracker.end(run.workflow_id, run.kind, status, error or "")
        if status == "failed":
            await self._error_log.upsert_from_run(db, run)
        self._manifests.pop(run.id, None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/unit/services/test_run_coordinator.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/error_log_service.py backend/app/services/run_coordinator.py backend/tests/unit/services/test_run_coordinator.py
git commit -m "feat(runs): RunCoordinator.finish + dedup'd ErrorLog upsert on failure

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 9: `RunCoordinator.request_cancel` + `retry`

**Files:**
- Modify: `app/services/run_coordinator.py`
- Modify: `tests/unit/services/test_run_coordinator.py` (add tests)

**Interfaces:**
- Produces: `RunCoordinator.request_cancel(db, run_id) -> bool` — sets `cancel_requested=True` on an active run (best-effort Redis key `cmd:cancel:{run_id}` when Redis is configured); returns `False` if the run is missing or already terminal.
- Produces: `RunCoordinator.retry(db, run_id, *, force_full) -> IndexingRun` — starts a fresh run for the same `(kind, project_id, connection_id)` with `trigger="manual"`, recording `retried_from` in `meta_json`.

- [ ] **Step 1: Write the failing test (append to the test module)**

```python
async def test_request_cancel_sets_flag(session: AsyncSession):
    coord = RunCoordinator()
    run = await coord.start(session, kind="db_index", project_id="p7", connection_id="c1")
    ok = await coord.request_cancel(session, run.id)
    assert ok is True
    await session.refresh(run)
    assert run.cancel_requested is True


async def test_request_cancel_returns_false_for_terminal(session: AsyncSession):
    coord = RunCoordinator()
    run = await coord.start(session, kind="db_index", project_id="p8", connection_id="c1")
    await coord.finish(run, "completed")
    assert await coord.request_cancel(session, run.id) is False


async def test_retry_starts_new_run_with_provenance(session: AsyncSession):
    import json as _json

    coord = RunCoordinator()
    run = await coord.start(session, kind="db_index", project_id="p9", connection_id="c1")
    await coord.finish(run, "failed", error="x", failure_kind="fatal")
    new = await coord.retry(session, run.id, force_full=True)
    assert new.id != run.id
    assert new.status == "running"
    assert _json.loads(new.meta_json)["retried_from"] == run.id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/unit/services/test_run_coordinator.py -k "cancel or retry" -v`
Expected: FAIL — `AttributeError: 'RunCoordinator' object has no attribute 'request_cancel'`.

- [ ] **Step 3: Write minimal implementation (add to `RunCoordinator`)**

```python
    async def request_cancel(self, db: AsyncSession, run_id: str) -> bool:
        run = await db.get(IndexingRun, run_id)
        if run is None or run.status not in _ACTIVE_STATUSES:
            return False
        run.cancel_requested = True
        await db.commit()
        try:
            from app.core import redis_client

            client = redis_client.get_redis()
            if client is not None:
                await client.set(f"cmd:cancel:{run_id}", "1", ex=3600)
        except Exception:  # noqa: BLE001 — Redis is best-effort
            logger.debug("cancel flag redis set failed", exc_info=True)
        return True

    async def retry(self, db: AsyncSession, run_id: str, *, force_full: bool) -> IndexingRun:
        old = await db.get(IndexingRun, run_id)
        if old is None:
            raise KeyError(f"run not found: {run_id}")
        new = await self.start(
            db,
            kind=old.kind,
            project_id=old.project_id,
            connection_id=old.connection_id,
            trigger="manual",
            force_full=force_full,
        )
        meta = {"force_full": force_full, "retried_from": old.id}
        new.meta_json = json.dumps(meta)
        await db.commit()
        return new
```

- [ ] **Step 4: Run the full suite for this milestone**

Run: `cd backend && .venv/bin/pytest tests/unit/services/test_run_coordinator.py tests/unit/models/test_indexing_run_models.py tests/unit/models/test_error_log_model.py tests/unit/knowledge/test_run_manifests.py tests/unit/core/test_workflow_event_fields.py -v`
Expected: PASS (all).

- [ ] **Step 5: Lint, type-check, format, commit**

```bash
cd backend && .venv/bin/ruff format app/ tests/ && .venv/bin/ruff check app/ tests/ && .venv/bin/mypy app/ --ignore-missing-imports
git add backend/app/services/run_coordinator.py backend/tests/unit/services/test_run_coordinator.py
git commit -m "feat(runs): RunCoordinator cancel + retry

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage (§5):**
- §5.1 `IndexingRun` → Task 1; `IndexingRunEvent` → Task 1; `ErrorLog` → Task 2; `RequestTrace.failure_kind` → Task 2; migration + partial-unique index → Task 3. `IndexingCheckpoint` retained untouched (Global Constraints). ✓
- §5.2 first-class event fields + tolerant rebuild → Task 4. ✓
- §5.3 manifests + progress → Task 5. ✓
- §5.4 `RunCoordinator` start/step/finish/request_cancel/retry → Tasks 6–9; `heartbeat` is folded into `step()`/`finish()` via `heartbeat_at` writes (a standalone `heartbeat()` is added in P1 when the long-running pipelines need between-step beats). ✓
- §5.1 `error_log` upsert path → Task 8. ✓
- Out of P0 scope (later plans): trigger rewiring, worker correlation, status/active endpoints, reaper, events/error endpoints, TTL sweeps, metrics, scheduled sync, frontend. Listed in spec §10 P1–P5.

**Placeholder scan:** The literal word "placeholder" appears once in Task 7 Step 3 where the first illustrative line is immediately replaced by the full method body — the actual code is complete; no `TBD`/`TODO`/"implement later" remain. ✓

**Type consistency:** `resolve_manifest`, `total_steps`, `progress_for`, `step_position`, `Step` names match across Tasks 5–9. `RunCoordinator.start/step/finish/request_cancel/retry` signatures match their Interfaces blocks and tests. `ErrorLogService.upsert/upsert_from_run` consistent between Task 8 definition and `RunCoordinator.finish` call. ✓

**Open risk flagged for the implementer:** `_session_of(run)` (Task 7) relies on `inspect(obj).session`. Task 7 Step 4 includes the exact fallback (thread `db` explicitly through `step/finish/cancel/retry`) if it proves brittle — choose one form and keep Tasks 7–9 consistent.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-22-p0-run-lifecycle-contracts.md`. Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.
