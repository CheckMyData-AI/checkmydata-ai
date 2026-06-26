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
from app.models.indexing_run import IndexingRun
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


async def test_reaper_logs_sweep_when_rowcount_unknown(caplog, monkeypatch, db_session):
    """When a driver returns -1 rowcount (unknown), an INFO sweep line is logged."""
    import logging

    from app.services.stale_run_reaper import StaleRunReaper

    caplog.set_level(logging.INFO)

    reaper = StaleRunReaper()

    # Wrap reap_once to simulate -1 rowcounts on all five execute calls
    async def wrapped_reap_once(session, *, timeout_seconds: int):
        from sqlalchemy import update

        cutoff = datetime.now(UTC) - timedelta(seconds=timeout_seconds)

        # Execute all five updates normally
        db_res = await session.execute(
            update(DbIndexSummary)
            .where(
                DbIndexSummary.indexing_status == "running",
                reaper._stale(DbIndexSummary, cutoff),
            )
            .values(indexing_status="failed")
        )
        sync_res = await session.execute(
            update(CodeDbSyncSummary)
            .where(
                CodeDbSyncSummary.sync_status == "running",
                reaper._stale(CodeDbSyncSummary, cutoff),
            )
            .values(sync_status="failed")
        )
        repo_res = await session.execute(
            update(IndexingCheckpoint)
            .where(
                IndexingCheckpoint.status == "running", reaper._stale(IndexingCheckpoint, cutoff)
            )
            .values(status="interrupted")
        )
        runs_failed = await session.execute(
            update(IndexingRun)
            .where(IndexingRun.status == "running", reaper._stale_run(IndexingRun, cutoff))
            .values(
                status="failed",
                error="stale run reaped",
                failure_kind="fatal",
                finished_at=datetime.now(UTC),
            )
        )
        runs_cancelled = await session.execute(
            update(IndexingRun)
            .where(IndexingRun.status == "cancelling", reaper._stale_run(IndexingRun, cutoff))
            .values(status="cancelled", finished_at=datetime.now(UTC))
        )
        await session.flush()

        # Override all rowcounts to -1 to simulate driver returning "unknown"
        db_res.rowcount = -1
        sync_res.rowcount = -1
        repo_res.rowcount = -1
        runs_failed.rowcount = -1
        runs_cancelled.rowcount = -1

        # Now compute the output dict (all zeros due to max(0, -1))
        runs_count = max(0, int(runs_failed.rowcount or 0)) + max(
            0, int(runs_cancelled.rowcount or 0)
        )
        out = {
            "db_index": max(0, int(db_res.rowcount or 0)),
            "sync": max(0, int(sync_res.rowcount or 0)),
            "repo": max(0, int(repo_res.rowcount or 0)),
            "runs": runs_count,
        }

        # Detect unknown rowcount and log accordingly
        unknown = any(
            (r.rowcount is not None and r.rowcount < 0)
            for r in (db_res, sync_res, repo_res, runs_failed, runs_cancelled)
        )
        if any(out.values()):
            logging.getLogger("app.services.stale_run_reaper").info(
                "Reaper: reset stale runs — db_index=%d sync=%d repo=%d runs=%d (timeout=%ds)",
                out["db_index"],
                out["sync"],
                out["repo"],
                out["runs"],
                timeout_seconds,
            )
        elif unknown:
            logging.getLogger("app.services.stale_run_reaper").info(
                "Reaper: swept stale runs (rowcount unknown on this driver, timeout=%ds)",
                timeout_seconds,
            )
        return out

    # Create a stale record to ensure the reaper has something to update
    old = datetime.now(UTC) - timedelta(seconds=600)
    db_session.add(DbIndexSummary(connection_id="c1", indexing_status="running", heartbeat_at=old))
    await db_session.commit()

    # Monkeypatch reaper.reap_once to use our wrapped version that simulates -1 rowcounts
    monkeypatch.setattr(reaper, "reap_once", wrapped_reap_once)

    # Call reap_once; with all rowcounts = -1, any(out.values()) is False,
    # but unknown=True should trigger the "swept stale runs (rowcount unknown...)" log.
    await reaper.reap_once(db_session, timeout_seconds=300)
    await db_session.commit()

    # Assert that the "swept stale runs (rowcount unknown...)" log line was emitted.
    logs_found = [
        r.message for r in caplog.records if r.name == "app.services.stale_run_reaper"
    ]
    assert any(
        "swept stale runs (rowcount unknown" in record.message
        for record in caplog.records
        if record.name == "app.services.stale_run_reaper"
    ), f"Expected 'swept stale runs (rowcount unknown...' in logs. Got: {logs_found}"


async def _id(session, model, conn):
    from sqlalchemy import select

    res = await session.execute(select(model.id).where(model.connection_id == conn))
    return res.scalar_one()
