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


# --- H8: IntegrityError → RunAlreadyActiveError translation (TOCTOU race) ----


async def _async_none() -> None:
    """Async stub that returns None — simulates _find_active pre-check missing the race winner."""
    return None


async def test_start_translates_integrity_error_to_already_active(session: AsyncSession):
    """TOCTOU race: pre-check passes (returns None) but DB unique constraint fires on commit.

    The coordinator must:
    1. Catch IntegrityError and NOT let it propagate as a raw 500.
    2. Roll back the poisoned session.
    3. Raise RunAlreadyActiveError (wrapping the original IntegrityError).
    4. Leave the session usable for subsequent queries.
    """
    coord = RunCoordinator()

    # First run holds the slot — committed normally.
    run1 = await coord.start(session, kind="code_db_sync", project_id="p10", connection_id="c1")
    assert run1.status == "running"

    # Monkeypatch _find_active to return None on the PRE-CHECK so the race
    # path reaches db.commit() and the DB unique index is what fires.
    # A second call (the recovery lookup inside the except block) must be real,
    # so we count calls and only skip the first one.
    real_find_active = coord._find_active
    call_count = 0

    async def _find_active_stub(db, project_id, kind, connection_id):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return None  # simulate pre-check miss
        return await real_find_active(db, project_id, kind, connection_id)

    coord._find_active = _find_active_stub  # type: ignore[method-assign]

    with pytest.raises(RunAlreadyActiveError):
        await coord.start(session, kind="code_db_sync", project_id="p10", connection_id="c1")

    # Restore
    coord._find_active = real_find_active  # type: ignore[method-assign]

    # Session must be usable after rollback — a simple query should not raise.
    recovered = await coord._find_active(session, "p10", "code_db_sync", "c1")
    assert recovered is not None
    assert recovered.id == run1.id
