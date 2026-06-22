from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.base import Base
from app.models.indexing_run import IndexingRunEvent
from app.services.run_coordinator import RunAlreadyActiveError, RunCancelledError, RunCoordinator


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


# --- start ---------------------------------------------------------------


async def test_start_creates_running_run(session: AsyncSession):
    coord = RunCoordinator()
    run = await coord.start(
        session, kind="db_index", project_id="p1", connection_id="c1", trigger="manual"
    )
    assert run.status == "running"
    assert run.workflow_id
    assert run.total_steps == 6
    assert run.started_at is not None
    events = (
        (await session.execute(select(IndexingRunEvent).where(IndexingRunEvent.run_id == run.id)))
        .scalars()
        .all()
    )
    assert [e.step for e in events] == ["pipeline_start"]


async def test_start_rejects_second_active_run(session: AsyncSession):
    coord = RunCoordinator()
    await coord.start(session, kind="db_index", project_id="p1", connection_id="c1")
    with pytest.raises(RunAlreadyActiveError):
        await coord.start(session, kind="db_index", project_id="p1", connection_id="c1")


async def test_start_allows_different_connection(session: AsyncSession):
    coord = RunCoordinator()
    await coord.start(session, kind="db_index", project_id="p1", connection_id="c1")
    run2 = await coord.start(session, kind="db_index", project_id="p1", connection_id="c2")
    assert run2.status == "running"


# --- step ----------------------------------------------------------------


async def test_step_advances_progress(session: AsyncSession):
    coord = RunCoordinator()
    run = await coord.start(session, kind="db_index", project_id="p2", connection_id="c1")
    async with coord.step(session, run, "introspect_schema"):
        pass
    async with coord.step(session, run, "fetch_samples"):
        pass
    await session.refresh(run)
    assert run.step_index == 2
    assert run.current_step == "fetch_samples"
    assert run.progress_pct == round(2 / 8 * 100)  # db_index total weight 8
    assert run.version == 2


async def test_step_raises_when_cancel_requested(session: AsyncSession):
    coord = RunCoordinator()
    run = await coord.start(session, kind="db_index", project_id="p3", connection_id="c1")
    run.cancel_requested = True
    await session.commit()
    with pytest.raises(RunCancelledError):
        async with coord.step(session, run, "introspect_schema"):
            pass
    await session.refresh(run)
    assert run.status == "cancelling"


async def test_step_emits_failed_event_then_reraises(session: AsyncSession):
    coord = RunCoordinator()
    run = await coord.start(session, kind="db_index", project_id="p4", connection_id="c1")
    with pytest.raises(ValueError):
        async with coord.step(session, run, "introspect_schema"):
            raise ValueError("boom")
    events = (
        (await session.execute(select(IndexingRunEvent).where(IndexingRunEvent.run_id == run.id)))
        .scalars()
        .all()
    )
    statuses = [(e.step, e.status) for e in events]
    assert ("introspect_schema", "failed") in statuses


# --- finish --------------------------------------------------------------


async def test_finish_completed_sets_terminal_state(session: AsyncSession):
    coord = RunCoordinator()
    run = await coord.start(session, kind="db_index", project_id="p5", connection_id="c1")
    await coord.finish(session, run, "completed")
    await session.refresh(run)
    assert run.status == "completed"
    assert run.progress_pct == 100
    assert run.finished_at is not None


async def test_finish_failed_upserts_error_log_and_dedups(session: AsyncSession):
    from app.models.error_log import ErrorLog

    coord = RunCoordinator()
    r1 = await coord.start(session, kind="db_index", project_id="p6", connection_id="c1")
    await coord.finish(
        session, r1, "failed", error="connection refused on host 12", failure_kind="transient"
    )
    r2 = await coord.start(session, kind="db_index", project_id="p6", connection_id="c1")
    await coord.finish(
        session, r2, "failed", error="connection refused on host 99", failure_kind="transient"
    )

    rows = (
        (await session.execute(select(ErrorLog).where(ErrorLog.project_id == "p6"))).scalars().all()
    )
    assert len(rows) == 1  # digit-skeleton dedup collapses host 12/99
    assert rows[0].occurrences == 2
    assert rows[0].source == "run"


# --- cancel + retry ------------------------------------------------------


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
    await coord.finish(session, run, "completed")
    assert await coord.request_cancel(session, run.id) is False


async def test_retry_starts_new_run_with_provenance(session: AsyncSession):
    import json as _json

    coord = RunCoordinator()
    run = await coord.start(session, kind="db_index", project_id="p9", connection_id="c1")
    await coord.finish(session, run, "failed", error="x", failure_kind="fatal")
    new = await coord.retry(session, run.id, force_full=True)
    assert new.id != run.id
    assert new.status == "running"
    assert _json.loads(new.meta_json)["retried_from"] == run.id
