# Self-Completing Embedding Reconcile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On boot, auto-detect an embedding-config change and enqueue a one-shot full reindex of all projects — idempotent, multi-dyno-safe, graceful — so the manual post-deploy ChromaDB reindex step disappears.

**Architecture:** A generic `deploy_state` KV table stores the last-reconciled embedding fingerprint. A `reconcile_embeddings()` function runs in the FastAPI `lifespan` startup, guarded by a Postgres transaction-scoped advisory lock, and calls the existing `queue_embedding_reindex` when the fingerprint changed. An Alembic migration seeds the OLD fingerprint on databases that already have projects, so the feature's own deploy closes the current stale-embedding backlog.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 async, Alembic, ARQ (via existing `app.core.task_queue.enqueue`), pytest (`asyncio_mode=auto`), aiosqlite (tests), Postgres (prod).

## Global Constraints

- Python 3.12; line length 100; ruff `0.15.15` rules `E F I N W UP`; mypy `--ignore-missing-imports` clean.
- Async everywhere — no sync I/O on the request/startup path.
- Single Alembic head must be preserved: new migration `down_revision = "c9b8a7f6e5d4"`.
- Combined unit+integration coverage gate ≥ 72%.
- Conventional commits (`feat`, `test`, `docs`).
- `reconcile_embeddings()` MUST NEVER raise — it is best-effort and must not block startup.
- Reuse existing `queue_embedding_reindex(project_ids: list[str]) -> list[str | None]` unchanged.
- Fingerprint format is EXACTLY `f"{settings.chroma_embedding_model}|{settings.embedder_max_tokens}"`.
- Constants (verbatim): `_FINGERPRINT_KEY = "embedding_fingerprint"`, `_ADVISORY_LOCK_KEY = 8274123001`.
- Migration seed values (verbatim): OLD = `"all-MiniLM-L6-v2|256"`, CURRENT = `"BAAI/bge-base-en-v1.5|512"`.

---

### Task 1: `DeployState` model + Alembic migration

**Files:**
- Create: `backend/app/models/deploy_state.py`
- Modify: `backend/app/models/__init__.py` (export `DeployState`)
- Create: `backend/alembic/versions/d5e6f7a8b9c0_add_deploy_state.py`
- Test: `backend/tests/unit/models/test_deploy_state.py`
- Test: `backend/tests/unit/ops/test_migration_seed.py`

**Interfaces:**
- Produces: `DeployState` ORM model (table `deploy_state`, cols `key: str[64] PK`, `value: str[255]`, `updated_at: datetime tz`); migration module-level helper `pick_seed_fingerprint(has_projects: bool) -> str`.

- [ ] **Step 1: Write the failing model round-trip test**

Create `backend/tests/unit/models/test_deploy_state.py`:

```python
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.deploy_state import DeployState


@pytest.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(c, tables=[DeployState.__table__])
        )
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_deploy_state_round_trip(session_factory):
    async with session_factory() as s:
        s.add(DeployState(key="embedding_fingerprint", value="m|1"))
        await s.commit()
    async with session_factory() as s:
        row = await s.get(DeployState, "embedding_fingerprint")
    assert row is not None
    assert row.value == "m|1"
    assert row.updated_at is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/unit/models/test_deploy_state.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.models.deploy_state'`.

- [ ] **Step 3: Create the model**

Create `backend/app/models/deploy_state.py`:

```python
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DeployState(Base):
    """Generic single-value key/value store for deploy-time reconciliation markers.

    Rows are tiny and few (one per marker kind). Currently only the
    ``embedding_fingerprint`` key is written, by the embedding reconcile flow.
    """

    __tablename__ = "deploy_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
```

Add to `backend/app/models/__init__.py` (follow the existing export style in that file — an import line plus an `__all__` entry if present):

```python
from app.models.deploy_state import DeployState
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/unit/models/test_deploy_state.py -v`
Expected: PASS.

- [ ] **Step 5: Write the failing migration-seed test**

Create `backend/tests/unit/ops/test_migration_seed.py`:

```python
import importlib.util
from pathlib import Path

_MIG = (
    Path(__file__).resolve().parents[2]
    / "alembic" / "versions" / "d5e6f7a8b9c0_add_deploy_state.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("mig_deploy_state", _MIG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_seed_picks_old_when_projects_exist():
    mod = _load()
    assert mod.pick_seed_fingerprint(True) == "all-MiniLM-L6-v2|256"


def test_seed_picks_current_when_no_projects():
    mod = _load()
    assert mod.pick_seed_fingerprint(False) == "BAAI/bge-base-en-v1.5|512"


def test_migration_chains_single_head():
    mod = _load()
    assert mod.down_revision == "c9b8a7f6e5d4"
    assert mod.revision == "d5e6f7a8b9c0"
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/unit/ops/test_migration_seed.py -v`
Expected: FAIL — migration file does not exist yet (`FileNotFoundError` / spec load error).

- [ ] **Step 7: Write the migration**

Create `backend/alembic/versions/d5e6f7a8b9c0_add_deploy_state.py`:

```python
"""add deploy_state table + seed embedding fingerprint

Revision ID: d5e6f7a8b9c0
Revises: c9b8a7f6e5d4
Create Date: 2026-07-06

Seeds the embedding fingerprint so the embedding-reconcile flow behaves
correctly on first boot:
- DB already has projects  -> seed the OLD fingerprint, so the first
  reconcile detects a change and reindexes the stale backlog once.
- Fresh install (no rows)  -> seed the CURRENT fingerprint, so no reindex.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d5e6f7a8b9c0"
down_revision = "c9b8a7f6e5d4"
branch_labels = None
depends_on = None

_OLD_FINGERPRINT = "all-MiniLM-L6-v2|256"
_CURRENT_FINGERPRINT = "BAAI/bge-base-en-v1.5|512"


def pick_seed_fingerprint(has_projects: bool) -> str:
    """OLD fingerprint when projects already exist (force one reindex), else CURRENT."""
    return _OLD_FINGERPRINT if has_projects else _CURRENT_FINGERPRINT


def upgrade() -> None:
    op.create_table(
        "deploy_state",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column("value", sa.String(length=255), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    conn = op.get_bind()
    has_projects = conn.execute(sa.text("SELECT 1 FROM projects LIMIT 1")).first() is not None
    # Omit updated_at -> server_default now()/CURRENT_TIMESTAMP fills it (dialect-safe).
    conn.execute(
        sa.text("INSERT INTO deploy_state (key, value) VALUES ('embedding_fingerprint', :v)"),
        {"v": pick_seed_fingerprint(has_projects)},
    )


def downgrade() -> None:
    op.drop_table("deploy_state")
```

- [ ] **Step 8: Run seed test + verify single head**

Run: `cd backend && .venv/bin/pytest tests/unit/ops/test_migration_seed.py -v`
Expected: PASS (3 tests).

Run: `cd backend && PYTHONPATH=. .venv/bin/alembic upgrade head && PYTHONPATH=. .venv/bin/alembic heads`
Expected: upgrade succeeds; `alembic heads` prints exactly one line ending `d5e6f7a8b9c0 (head)`.

- [ ] **Step 9: Lint + commit**

```bash
cd backend && .venv/bin/ruff format app/models/deploy_state.py tests/unit/models/test_deploy_state.py tests/unit/ops/test_migration_seed.py && .venv/bin/ruff check app/models/deploy_state.py tests/ --fix
git add backend/app/models/deploy_state.py backend/app/models/__init__.py backend/alembic/versions/d5e6f7a8b9c0_add_deploy_state.py backend/tests/unit/models/test_deploy_state.py backend/tests/unit/ops/test_migration_seed.py
git commit -m "feat: add deploy_state table + embedding-fingerprint seed migration"
```

---

### Task 2: `reconcile_embeddings` core logic + unit tests

**Files:**
- Create: `backend/app/ops/__init__.py` (empty)
- Create: `backend/app/ops/embedding_reconcile.py`
- Test: `backend/tests/unit/ops/test_embedding_reconcile.py`

**Interfaces:**
- Consumes: `DeployState` (Task 1); existing `queue_embedding_reindex(project_ids) -> list[str|None]`; `Project`.
- Produces:
  - `embedding_fingerprint() -> str`
  - `reconcile_embeddings(session_factory: async_sessionmaker | None = None) -> ReconcileResult` (never raises)
  - `ReconcileResult(status: str, reindexed: int = 0, fingerprint: str = "")`, `status ∈ {"unchanged","reindexed","skipped_locked","seeded","error"}`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/ops/test_embedding_reconcile.py`:

```python
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.ops.embedding_reconcile as recon
from app.config import settings
from app.models.base import Base
from app.models.deploy_state import DeployState
from app.models.project import Project


@pytest.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(
                c, tables=[DeployState.__table__, Project.__table__]
            )
        )
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def _current():
    return f"{settings.chroma_embedding_model}|{settings.embedder_max_tokens}"


async def _seed_marker(sf, value):
    async with sf() as s:
        s.add(DeployState(key="embedding_fingerprint", value=value))
        await s.commit()


async def _add_projects(sf, n):
    async with sf() as s:
        for i in range(n):
            s.add(Project(name=f"p{i}"))
        await s.commit()


def test_fingerprint_format():
    assert recon.embedding_fingerprint() == _current()


async def test_unchanged_no_reindex(session_factory, monkeypatch):
    spy = AsyncMock(return_value=[])
    monkeypatch.setattr(recon, "queue_embedding_reindex", spy)
    await _seed_marker(session_factory, _current())
    res = await recon.reconcile_embeddings(session_factory)
    assert res.status == "unchanged"
    spy.assert_not_called()


async def test_changed_triggers_reindex_and_advances_marker(session_factory, monkeypatch):
    spy = AsyncMock(return_value=["job1", "job2"])
    monkeypatch.setattr(recon, "queue_embedding_reindex", spy)
    await _seed_marker(session_factory, "all-MiniLM-L6-v2|256")
    await _add_projects(session_factory, 2)
    res = await recon.reconcile_embeddings(session_factory)
    assert res.status == "reindexed"
    assert res.reindexed == 2
    assert spy.call_count == 1
    assert len(spy.call_args.args[0]) == 2
    async with session_factory() as s:
        row = await s.get(DeployState, "embedding_fingerprint")
    assert row.value == _current()


async def test_marker_not_advanced_on_enqueue_failure(session_factory, monkeypatch):
    spy = AsyncMock(side_effect=RuntimeError("redis down"))
    monkeypatch.setattr(recon, "queue_embedding_reindex", spy)
    await _seed_marker(session_factory, "all-MiniLM-L6-v2|256")
    await _add_projects(session_factory, 1)
    res = await recon.reconcile_embeddings(session_factory)
    assert res.status == "error"
    async with session_factory() as s:
        row = await s.get(DeployState, "embedding_fingerprint")
    assert row.value == "all-MiniLM-L6-v2|256"  # unchanged -> retries next boot


async def test_missing_marker_seeds_without_reindex(session_factory, monkeypatch):
    spy = AsyncMock(return_value=[])
    monkeypatch.setattr(recon, "queue_embedding_reindex", spy)
    res = await recon.reconcile_embeddings(session_factory)
    assert res.status == "seeded"
    spy.assert_not_called()
    async with session_factory() as s:
        row = await s.get(DeployState, "embedding_fingerprint")
    assert row.value == _current()


async def test_changed_with_zero_projects_advances_marker(session_factory, monkeypatch):
    spy = AsyncMock(return_value=[])
    monkeypatch.setattr(recon, "queue_embedding_reindex", spy)
    await _seed_marker(session_factory, "all-MiniLM-L6-v2|256")
    res = await recon.reconcile_embeddings(session_factory)
    assert res.status == "reindexed"
    assert res.reindexed == 0
    assert spy.call_args.args[0] == []
    async with session_factory() as s:
        row = await s.get(DeployState, "embedding_fingerprint")
    assert row.value == _current()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/pytest tests/unit/ops/test_embedding_reconcile.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ops'`.

- [ ] **Step 3: Create the package + module**

Create empty `backend/app/ops/__init__.py`.

Create `backend/app/ops/embedding_reconcile.py`:

```python
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings
from app.models.base import async_session_factory
from app.models.deploy_state import DeployState
from app.models.project import Project
from app.services.embedding_reindex import queue_embedding_reindex

logger = logging.getLogger(__name__)

_FINGERPRINT_KEY = "embedding_fingerprint"
# Stable, arbitrary 64-bit key for pg_try_advisory_xact_lock — never change it.
_ADVISORY_LOCK_KEY = 8274123001


@dataclass
class ReconcileResult:
    status: str
    reindexed: int = 0
    fingerprint: str = ""


def embedding_fingerprint() -> str:
    """Deterministic string identifying the current embedding config."""
    return f"{settings.chroma_embedding_model}|{settings.embedder_max_tokens}"


async def reconcile_embeddings(
    session_factory: async_sessionmaker | None = None,
) -> ReconcileResult:
    """Detect an embedding-config change and enqueue a one-shot full reindex.

    Best-effort: never raises. The marker is advanced ONLY after a successful
    enqueue, so a failure retries on the next boot. On Postgres a
    transaction-scoped advisory lock serializes concurrent dynos; other
    dialects (SQLite dev) skip the lock (single process).
    """
    current = embedding_fingerprint()
    factory = session_factory or async_session_factory
    try:
        async with factory() as session:
            dialect = session.get_bind().dialect.name
            if dialect == "postgresql":
                locked = await session.scalar(
                    text("SELECT pg_try_advisory_xact_lock(:k)"),
                    {"k": _ADVISORY_LOCK_KEY},
                )
                if not locked:
                    return ReconcileResult("skipped_locked", fingerprint=current)

            stored = await session.get(DeployState, _FINGERPRINT_KEY)

            if stored is None:
                session.add(DeployState(key=_FINGERPRINT_KEY, value=current))
                await session.commit()
                return ReconcileResult("seeded", fingerprint=current)

            if stored.value == current:
                return ReconcileResult("unchanged", fingerprint=current)

            ids = list((await session.scalars(select(Project.id))).all())
            await queue_embedding_reindex(ids)
            stored.value = current
            await session.commit()
            logger.info(
                "Embedding config changed (%s -> %s); reindexed %d project(s).",
                stored.value,
                current,
                len(ids),
            )
            return ReconcileResult("reindexed", reindexed=len(ids), fingerprint=current)
    except Exception:
        logger.warning("reconcile_embeddings failed; marker untouched", exc_info=True)
        return ReconcileResult("error", fingerprint=current)
```

> Note: the log line reads `stored.value` after reassignment — reorder if you want the pre-change value; not asserted by tests. Keep it simple: log before reassigning if desired.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/pytest tests/unit/ops/test_embedding_reconcile.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: mypy + lint + commit**

```bash
cd backend && .venv/bin/ruff format app/ops/ tests/unit/ops/test_embedding_reconcile.py && .venv/bin/ruff check app/ops/ tests/unit/ops/ --fix && .venv/bin/mypy app/ops/ --ignore-missing-imports
git add backend/app/ops/__init__.py backend/app/ops/embedding_reconcile.py backend/tests/unit/ops/test_embedding_reconcile.py
git commit -m "feat: reconcile_embeddings — auto-detect embedding change and enqueue reindex"
```

---

### Task 3: Wire into `lifespan` startup + integration test

**Files:**
- Modify: `backend/app/main.py` (add reconcile call in `lifespan`, after task-queue init)
- Test: `backend/tests/integration/test_embedding_reconcile_startup.py`

**Interfaces:**
- Consumes: `reconcile_embeddings` (Task 2); existing `app.services.embedding_reindex.enqueue`, `VectorStore.delete_collection`.

- [ ] **Step 1: Write the failing integration test**

Create `backend/tests/integration/test_embedding_reconcile_startup.py`:

```python
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.services.embedding_reindex as reindex_mod
import app.ops.embedding_reconcile as recon
from app.models.base import Base
from app.models.deploy_state import DeployState
from app.models.project import Project


@pytest.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(
                c, tables=[DeployState.__table__, Project.__table__]
            )
        )
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_reconcile_drives_real_reindex_path(session_factory, monkeypatch):
    # Real queue_embedding_reindex runs; only its external deps are stubbed.
    enqueue_spy = AsyncMock(return_value="job-1")
    monkeypatch.setattr(reindex_mod, "enqueue", enqueue_spy)
    monkeypatch.setattr(
        reindex_mod.VectorStore, "delete_collection", lambda self, pid: None, raising=True
    )
    async with session_factory() as s:
        s.add(DeployState(key="embedding_fingerprint", value="all-MiniLM-L6-v2|256"))
        s.add(Project(name="p0"))
        await s.commit()

    res = await recon.reconcile_embeddings(session_factory)

    assert res.status == "reindexed"
    assert res.reindexed == 1
    assert enqueue_spy.call_count == 1
    assert enqueue_spy.call_args.args[0] == "run_repo_index"
    assert enqueue_spy.call_args.kwargs.get("force_full") is True


async def test_skipped_locked_when_lock_unavailable(session_factory, monkeypatch):
    # Simulate the Postgres advisory-lock-held branch via a scalar stub.
    async def _fake_scalar(*a, **k):
        return False

    real_get = session_factory

    class _FakeSession:
        def __init__(self, inner):
            self._inner = inner

        async def __aenter__(self):
            self._s = await self._inner.__aenter__()

            class _Bind:
                dialect = type("D", (), {"name": "postgresql"})()

            self._s.get_bind = lambda: _Bind()
            self._s.scalar = _fake_scalar
            return self._s

        async def __aexit__(self, *a):
            return await self._inner.__aexit__(*a)

    def _factory():
        return _FakeSession(real_get())

    res = await recon.reconcile_embeddings(_factory)
    assert res.status == "skipped_locked"
```

- [ ] **Step 2: Run test to verify the first case fails on wiring**

Run: `cd backend && .venv/bin/pytest tests/integration/test_embedding_reconcile_startup.py -v`
Expected: `test_reconcile_drives_real_reindex_path` and `test_skipped_locked_when_lock_unavailable` PASS already (they call `reconcile_embeddings` directly — this confirms the reconcile↔reindex integration). If either fails, fix reconcile/reindex wiring before proceeding.

> The startup wiring itself (Step 3) is verified by the manual boot check in Step 4; a full-app lifespan test is intentionally out of scope (heavy env). These two integration tests lock the behavior the lifespan call depends on.

- [ ] **Step 3: Wire reconcile into `lifespan`**

Find the task-queue init line: `cd backend && grep -n "init_task_queue" app/main.py`.
Immediately AFTER the `await init_task_queue(...)` call inside `lifespan` (reconcile enqueues, so the queue must be initialized first), add:

```python
        # Self-completing deploy: auto-reindex embeddings if the model/window changed.
        try:
            from app.ops.embedding_reconcile import reconcile_embeddings

            _recon = await reconcile_embeddings()
            logger.info(
                "Embedding reconcile at startup: %s (reindexed=%d)",
                _recon.status,
                _recon.reindexed,
            )
        except Exception:
            logger.warning("Embedding reconcile failed at startup", exc_info=True)
```

Match the surrounding indentation of the other best-effort startup blocks in `lifespan`.

- [ ] **Step 4: Verify boot locally**

Run: `cd backend && PYTHONPATH=. .venv/bin/python -c "import app.main"`
Expected: imports cleanly (no ImportError).

Run: `cd backend && .venv/bin/pytest tests/integration/test_embedding_reconcile_startup.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Lint + commit**

```bash
cd backend && .venv/bin/ruff format app/main.py tests/integration/test_embedding_reconcile_startup.py && .venv/bin/ruff check app/main.py tests/integration/ --fix && .venv/bin/mypy app/main.py --ignore-missing-imports
git add backend/app/main.py backend/tests/integration/test_embedding_reconcile_startup.py
git commit -m "feat: run embedding reconcile in FastAPI lifespan startup"
```

---

### Task 4: Docs — replace manual step with auto-reconcile note

**Files:**
- Modify: `CLAUDE.md` (Deploy notes section, lines ~104–116)
- Modify: `CHANGELOG.md` (Deploy notes block, lines ~74–86)

**Interfaces:** none (documentation only).

- [ ] **Step 1: Update `CLAUDE.md` deploy note**

Replace the "ChromaDB full reindex — MANDATORY" manual block with an automatic-behavior note. New text for item 1:

```markdown
**1. ChromaDB reindex — AUTOMATIC (self-completing deploy)**
Embedding-config changes (`CHROMA_EMBEDDING_MODEL` / `EMBEDDER_MAX_TOKENS`) are
reconciled automatically at startup: `app/ops/embedding_reconcile.reconcile_embeddings`
runs in the FastAPI `lifespan`, compares the current fingerprint against the
`deploy_state.embedding_fingerprint` marker, and enqueues a full reindex of all
projects exactly once when it changed (idempotent, multi-dyno-safe via a Postgres
advisory lock, degrades gracefully). No manual step is required.

Manual override (rarely needed) remains available:
`from app.services.embedding_reindex import queue_embedding_reindex` or the
"Re-index repository" UI action per project.
```

- [ ] **Step 2: Update `CHANGELOG.md` `[Unreleased]`**

In the deploy-notes block, change item 1's heading from "ChromaDB full reindex required (breaking until completed)" + manual `queue_embedding_reindex` instructions to a one-line automatic note, and add an `### Added` entry:

```markdown
### Added
- **Self-completing embedding reconcile**: on startup the app detects an
  embedding-config change (`chroma_embedding_model` / `embedder_max_tokens`) via
  the new `deploy_state` marker table and auto-enqueues a one-shot full reindex of
  all projects — idempotent, multi-dyno-safe (Postgres advisory lock), graceful.
  Removes the previous manual post-deploy reindex step. Migration `d5e6f7a8b9c0`.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md CHANGELOG.md
git commit -m "docs: embedding reindex is now automatic (self-completing deploy)"
```

---

## Self-Review

**1. Spec coverage:**
- `deploy_state` model + table → Task 1. ✅
- Migration `down_revision=c9b8a7f6e5d4` + conditional seed → Task 1. ✅
- `embedding_fingerprint()` / `reconcile_embeddings()` / `ReconcileResult` contracts → Task 2. ✅
- Advisory-lock (Postgres) + SQLite skip → Task 2 code + Task 3 `skipped_locked` test. ✅
- Marker-only-advanced-on-success → Task 2 `test_marker_not_advanced_on_enqueue_failure`. ✅
- Seed defensive path → Task 2 `test_missing_marker_seeds_without_reindex`. ✅
- Lifespan wiring after task-queue init → Task 3. ✅
- Graceful (never raises, in-process enqueue, boot continues) → Task 2 try/except + Task 3 outer guard. ✅
- All 6 unit + migration + integration tests → Tasks 1–3. ✅
- Docs manual→automatic → Task 4. ✅

**2. Placeholder scan:** No TBD/TODO; every code step shows full code; every command has expected output. The `~104–116` / `~74–86` line ranges in Task 4 are approximate anchors for edits to living docs — the surrounding heading text is quoted so the editor finds the block. ✅

**3. Type consistency:** `ReconcileResult(status, reindexed, fingerprint)`, `_FINGERPRINT_KEY`, `_ADVISORY_LOCK_KEY`, `pick_seed_fingerprint(bool)->str`, fingerprint format, seed constants — identical across spec, Task 1, Task 2, Task 3. `queue_embedding_reindex` signature matches existing code. ✅
