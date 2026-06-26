from datetime import UTC, datetime, timedelta

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import app.models.code_db_sync  # noqa: F401
import app.models.db_index  # noqa: F401
import app.models.indexing_checkpoint  # noqa: F401
import app.models.indexing_run  # noqa: F401
from app.models.base import Base
from app.models.code_db_sync import CodeDbSyncSummary
from app.models.db_index import DbIndexSummary
from app.models.indexing_checkpoint import IndexingCheckpoint
from app.services.stale_run_reaper import StaleRunReaper


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()


async def test_reaps_stale_db_index_running(db_session):
    old = datetime.now(UTC) - timedelta(seconds=600)
    db_session.add(DbIndexSummary(connection_id="c1", indexing_status="running", heartbeat_at=old))
    await db_session.commit()

    out = await StaleRunReaper().reap_once(db_session, timeout_seconds=300)
    await db_session.commit()

    assert out["db_index"] == 1
    svc_row = await db_session.get(DbIndexSummary, (await _id(db_session, DbIndexSummary, "c1")))
    assert svc_row.indexing_status == "failed"


async def test_does_not_reap_fresh_heartbeat(db_session):
    fresh = datetime.now(UTC) - timedelta(seconds=10)
    db_session.add(CodeDbSyncSummary(connection_id="c2", sync_status="running", heartbeat_at=fresh))
    await db_session.commit()

    out = await StaleRunReaper().reap_once(db_session, timeout_seconds=300)
    assert out["sync"] == 0


async def test_null_heartbeat_with_recent_update_is_spared(db_session):
    # Newly started run: heartbeat_at NULL but updated_at just now → must survive.
    db_session.add(DbIndexSummary(connection_id="c3", indexing_status="running", heartbeat_at=None))
    await db_session.commit()
    out = await StaleRunReaper().reap_once(db_session, timeout_seconds=300)
    assert out["db_index"] == 0


async def test_reaps_stale_checkpoint_to_interrupted(db_session):
    old = datetime.now(UTC) - timedelta(seconds=600)
    cp = IndexingCheckpoint(
        project_id="p1", workflow_id="wf", head_sha="", status="running", heartbeat_at=old
    )
    db_session.add(cp)
    await db_session.commit()

    out = await StaleRunReaper().reap_once(db_session, timeout_seconds=300)
    await db_session.commit()
    assert out["repo"] == 1
    await db_session.refresh(cp)
    assert cp.status == "interrupted"


async def test_idempotent_second_run_is_noop(db_session):
    old = datetime.now(UTC) - timedelta(seconds=600)
    db_session.add(DbIndexSummary(connection_id="c4", indexing_status="running", heartbeat_at=old))
    await db_session.commit()
    r = StaleRunReaper()
    await r.reap_once(db_session, timeout_seconds=300)
    await db_session.commit()
    out2 = await r.reap_once(db_session, timeout_seconds=300)
    assert out2["db_index"] == 0


async def test_reaper_logs_sweep_when_rowcount_unknown(caplog):
    """When a driver returns -1 rowcount (unknown), an INFO sweep line is logged.

    This test exercises the real reaper.reap_once() with a fake session
    that forces all execute() calls to return -1 rowcount.
    """
    import logging
    from unittest.mock import AsyncMock, MagicMock

    caplog.set_level(logging.INFO)

    reaper = StaleRunReaper()

    # Create a fake result object with rowcount = -1
    class FakeResult:
        rowcount = -1

    # Create a fake session that returns the fake result on every execute(),
    # and supports flush() as an async no-op.
    fake_session = MagicMock()
    fake_session.execute = AsyncMock(return_value=FakeResult())
    fake_session.flush = AsyncMock()

    # Call the REAL reaper.reap_once with the fake session.
    # All five execute() calls will return FakeResult (rowcount=-1),
    # so out will be all zeros, but unknown=True will trigger the sweep log.
    out = await reaper.reap_once(fake_session, timeout_seconds=300)

    # Verify all counts are 0 (max(0, -1) = 0).
    assert out == {"db_index": 0, "sync": 0, "repo": 0, "runs": 0}

    # Assert the "swept stale runs (rowcount unknown...)" log was emitted.
    logs_found = [r.message for r in caplog.records if r.name == "app.services.stale_run_reaper"]
    assert any(
        "swept stale runs (rowcount unknown" in record.message
        for record in caplog.records
        if record.name == "app.services.stale_run_reaper"
    ), f"Expected 'swept stale runs (rowcount unknown...' in logs. Got: {logs_found}"


async def _id(session, model, conn):
    from sqlalchemy import select

    res = await session.execute(select(model.id).where(model.connection_id == conn))
    return res.scalar_one()
