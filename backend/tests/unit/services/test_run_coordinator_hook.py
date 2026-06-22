from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.core.workflow_tracker import WorkflowEvent
from app.models.base import Base
from app.models.error_log import ErrorLog
from app.models.indexing_run import IndexingRunEvent
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

    await coord._apply_event(
        session,
        run,
        WorkflowEvent(
            workflow_id=wf, step="introspect_schema", status="started", pipeline="db_index"
        ),
    )
    await coord._apply_event(
        session,
        run,
        WorkflowEvent(
            workflow_id=wf, step="introspect_schema", status="completed", pipeline="db_index"
        ),
    )
    await session.refresh(run)
    assert run.current_step == "introspect_schema"
    assert run.step_index == 1
    assert run.progress_pct == round(1 / 8 * 100)  # db_index total weight 8

    await coord._apply_event(
        session,
        run,
        WorkflowEvent(
            workflow_id=wf,
            step="pipeline_end",
            status="failed",
            detail="kaboom 7",
            pipeline="db_index",
        ),
    )
    await session.refresh(run)
    assert run.status == "failed"
    assert run.finished_at is not None

    errs = (
        (await session.execute(select(ErrorLog).where(ErrorLog.project_id == "p"))).scalars().all()
    )
    assert len(errs) == 1 and errs[0].source == "run"

    events = (
        (await session.execute(select(IndexingRunEvent).where(IndexingRunEvent.run_id == run.id)))
        .scalars()
        .all()
    )
    assert any(e.step == "pipeline_end" for e in events)


async def test_hook_skips_coordinated_events_with_run_id(session: AsyncSession):
    """_on_event must ignore events that already carry run_id (coordinator-persisted)."""
    coord = RunCoordinator()
    run = await coord.start(session, kind="db_index", project_id="p2", connection_id="c")
    before = run.step_index
    # An event with run_id set is a coordinator echo — the hook must not touch the run.
    await coord._on_event(
        WorkflowEvent(
            workflow_id=run.workflow_id,
            step="fetch_samples",
            status="completed",
            run_id=run.id,
            kind="db_index",
        )
    )
    await session.refresh(run)
    assert run.step_index == before
