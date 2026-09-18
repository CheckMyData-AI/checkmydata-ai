"""PRJ-10: a nightly collection is a background run, and now says so.

`run_analytics_collect` called a third-party API every night on the project's behalf and
left no `IndexingRun` at all. The consequences are the ones `run_repo_index` had before
2026-08-31, for the same reason: nothing beat a heartbeat (so nothing could tell a live
collection from a dead one), nothing appeared in `/sync-history` (so a project's owner
could not see that last night ran), and the active-tasks widget showed nothing while the
work was in flight. The only record was a log line on the worker and the per-period
journal — the first a person cannot open, the second is per period rather than per run.

The rule the row follows is the one repo indexing settled: **bookkeeping, never the
work.** A run row that cannot be written is logged, and the collection proceeds.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401 — register every mapper
from app.analytics.outcome import CollectOutcome
from app.knowledge.run_manifests import resolve_manifest, total_steps
from app.models.base import Base, enable_sqlite_fk
from app.models.connection import Connection
from app.models.indexing_run import IndexingRun
from app.models.project import Project
from app.services.analytics_collect_service import AnalyticsCollectService
from app.services.sync_history_service import HISTORY_KINDS, SyncHistoryService


@pytest_asyncio.fixture
async def db() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    enable_sqlite_fk(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def connection(db: AsyncSession) -> Connection:
    project = Project(name=f"proj-{uuid.uuid4().hex[:6]}")
    db.add(project)
    await db.commit()
    conn = Connection(
        project_id=project.id,
        name="ga4-prod",
        source_type="ga4",
        source_config_json=json.dumps({"property_ids": ["1"]}),
    )
    db.add(conn)
    await db.commit()
    await db.refresh(conn)
    return conn


async def _runs(db: AsyncSession) -> list[IndexingRun]:
    return list((await db.execute(select(IndexingRun))).scalars().all())


def test_the_kind_has_a_manifest_so_the_bar_can_move():
    manifest = resolve_manifest("analytics_collect")

    assert total_steps(manifest) == 3
    assert [step.key for step in manifest] == ["connect", "collect_reports", "summarize"]


def test_the_history_answers_for_collections_too():
    assert "analytics_collect" in HISTORY_KINDS
    assert "daily_sync" in HISTORY_KINDS, "the knowledge sync must not have been displaced"


@pytest.mark.asyncio
class TestTheRunRow:
    async def test_a_collection_mints_one_and_closes_it(
        self, db: AsyncSession, connection: Connection
    ):
        service = AnalyticsCollectService()
        run = await service._start_run(db, connection.id, trigger="schedule")
        assert run is not None

        outcome = CollectOutcome()
        outcome.rows_written = 12
        outcome.periods_ok = 4
        await service._finish_run(db, run, outcome)

        rows = await _runs(db)
        assert len(rows) == 1
        assert rows[0].kind == "analytics_collect"
        assert rows[0].trigger == "schedule"
        assert rows[0].status == "completed"
        assert rows[0].connection_id == connection.id
        assert json.loads(rows[0].meta_json)["rows_written"] == 12

    async def test_a_run_that_wrote_nothing_and_errored_is_failed(
        self, db: AsyncSession, connection: Connection
    ):
        service = AnalyticsCollectService()
        run = await service._start_run(db, connection.id, trigger="schedule")
        assert run is not None

        outcome = CollectOutcome()
        outcome.errors.append("the credential was refused")
        await service._finish_run(db, run, outcome)

        rows = await _runs(db)
        assert rows[0].status == "failed"
        assert rows[0].error is not None and "refused" in rows[0].error

    async def test_a_partial_run_completed(self, db: AsyncSession, connection: Connection):
        """Rows landed and the rest is owed in the journal — that is not a failed run."""
        service = AnalyticsCollectService()
        run = await service._start_run(db, connection.id, trigger="schedule")
        assert run is not None

        outcome = CollectOutcome()
        outcome.rows_written = 3
        outcome.errors.append("one property did not answer")
        assert outcome.status == "partial"
        await service._finish_run(db, run, outcome)

        assert (await _runs(db))[0].status == "completed"

    async def test_a_deleted_connection_mints_nothing(self, db: AsyncSession):
        assert await AnalyticsCollectService()._start_run(db, "gone", trigger="schedule") is None

    async def test_the_collection_proceeds_when_the_row_cannot_be_written(
        self, db: AsyncSession, connection: Connection
    ):
        """Bookkeeping, never the work."""
        with patch(
            "app.services.run_coordinator.RunCoordinator.start",
            new=AsyncMock(side_effect=RuntimeError("no database for the run row")),
        ):
            run = await AnalyticsCollectService()._start_run(db, connection.id, trigger="schedule")

        assert run is None
        assert await _runs(db) == []

    async def test_a_second_collection_does_not_mint_a_second_active_row(
        self, db: AsyncSession, connection: Connection
    ):
        """`uq_indexing_runs_active_one` is the database's rule; this respects it."""
        service = AnalyticsCollectService()
        first = await service._start_run(db, connection.id, trigger="schedule")
        assert first is not None

        second = await service._start_run(db, connection.id, trigger="manual")

        assert second is None
        assert len(await _runs(db)) == 1


@pytest.mark.asyncio
async def test_the_project_history_lists_the_collection(db: AsyncSession, connection: Connection):
    service = AnalyticsCollectService()
    run = await service._start_run(db, connection.id, trigger="schedule")
    assert run is not None
    run.started_at = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=30)
    await service._finish_run(db, run, CollectOutcome())

    history: list[dict[str, Any]] = await SyncHistoryService().list_for_project(
        db, connection.project_id
    )

    assert [row["kind"] for row in history] == ["analytics_collect"]
    assert history[0]["connection_id"] == connection.id
    assert history[0]["status"] == "completed"
    assert (history[0]["duration_seconds"] or 0) > 0


@pytest.mark.asyncio
async def test_collect_itself_mints_steps_and_closes_the_run(
    db: AsyncSession, connection: Connection
):
    """The wiring, not the helpers: `collect()` is what the worker and the route call."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _one_session():
        yield db

    service = AnalyticsCollectService(adapter_factory=lambda conn: _NoReports())
    with (
        patch("app.models.base.async_session_factory", _one_session),
        patch("app.services.analytics_collect_service._COLLECT_LOCK_TTL_SECONDS", 60),
    ):
        outcome = await service.collect(connection.id, trigger="schedule")

    assert outcome.status == "ok"
    rows = await _runs(db)
    assert len(rows) == 1, "the collection ran outside any run row"
    assert rows[0].status == "completed"
    assert rows[0].trigger == "schedule"
    assert rows[0].current_step == "summarize", (
        "a run whose step never moves reads as stuck in the active-tasks widget"
    )
    assert rows[0].progress_pct == 100


class _NoReports:
    """A vendor that connects and offers nothing — the run's shape is what is under test."""

    @property
    def source_type(self) -> str:
        return "ga4"

    async def connect(self, config: Any) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def test_connection(self) -> bool:
        return True

    def available_reports(self) -> list[Any]:
        return []

    async def fetch(self, report: str, period: str) -> Any:  # pragma: no cover - never called
        raise AssertionError("no reports were offered")
