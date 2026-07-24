"""FA-007: a run falsely flipped to ``failed`` by the stale-run reaper must be
reconcilable — when the still-alive pipeline later emits its terminal
``pipeline_end``, the run lands in the *true* terminal state and the reap fact
is preserved in ``meta_json`` instead of being dropped on the floor.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.core.workflow_tracker import WorkflowEvent
from app.models.base import Base
from app.models.indexing_run import IndexingRun, IndexingRunEvent
from app.services.run_coordinator import RunCoordinator
from app.services.stale_run_reaper import REAP_ERROR, StaleRunReaper


@pytest.fixture
async def session(monkeypatch: pytest.MonkeyPatch) -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    # _on_event opens its own session via the module-level factory — point it
    # at the test engine, and isolate the process-wide wf→run map per test.
    monkeypatch.setattr("app.services.run_coordinator.async_session_factory", sm)
    monkeypatch.setattr(RunCoordinator, "_wf_to_run", {})
    s = sm()
    try:
        yield s
    finally:
        await s.close()
        await engine.dispose()


async def _start_and_reap(session: AsyncSession, coord: RunCoordinator) -> IndexingRun:
    run = await coord.start(session, kind="index_repo", project_id="p", connection_id=None)
    run.heartbeat_at = datetime.now(UTC) - timedelta(seconds=10_000)
    await session.commit()

    out = await StaleRunReaper().reap_once(session, timeout_seconds=300)
    await session.commit()
    assert out["runs"] == 1
    await session.refresh(run)
    assert run.status == "failed"
    assert run.error == REAP_ERROR
    return run


async def test_reaped_run_reconciled_to_completed_on_pipeline_end(session: AsyncSession):
    coord = RunCoordinator()
    run = await _start_and_reap(session, coord)

    await coord._on_event(
        WorkflowEvent(
            workflow_id=run.workflow_id,
            step="pipeline_end",
            status="completed",
            pipeline="index_repo",
        )
    )

    await session.refresh(run)
    assert run.status == "completed"
    assert run.progress_pct == 100
    assert run.error is None
    meta = json.loads(run.meta_json)
    assert meta["reaped"]["error"] == REAP_ERROR
    assert meta["reaped"]["reaped_at"] is not None

    events = (
        (await session.execute(select(IndexingRunEvent).where(IndexingRunEvent.run_id == run.id)))
        .scalars()
        .all()
    )
    assert any(e.step == "pipeline_end" and e.status == "completed" for e in events)


async def test_reaped_run_reconciled_to_failed_on_pipeline_end(session: AsyncSession):
    coord = RunCoordinator()
    run = await _start_and_reap(session, coord)

    await coord._on_event(
        WorkflowEvent(
            workflow_id=run.workflow_id,
            step="pipeline_end",
            status="failed",
            detail="disk full",
            pipeline="index_repo",
        )
    )

    await session.refresh(run)
    assert run.status == "failed"
    assert run.error == "disk full"
    assert run.failure_kind == "fatal"
    meta = json.loads(run.meta_json)
    assert meta["reaped"]["error"] == REAP_ERROR


async def test_reaped_run_still_ignores_non_terminal_events(session: AsyncSession):
    coord = RunCoordinator()
    run = await _start_and_reap(session, coord)
    step_index_before = run.step_index

    await coord._on_event(
        WorkflowEvent(
            workflow_id=run.workflow_id,
            step="generate_docs",
            status="started",
            pipeline="index_repo",
        )
    )

    await session.refresh(run)
    assert run.status == "failed"
    assert run.error == REAP_ERROR
    assert run.step_index == step_index_before


async def test_normal_failed_run_ignores_pipeline_end(session: AsyncSession):
    """A run that failed for a real reason (no reap marker) stays untouched."""
    coord = RunCoordinator()
    run = await coord.start(session, kind="index_repo", project_id="p", connection_id=None)
    await coord.finish(session, run, "failed", error="real boom", failure_kind="fatal")

    await coord._on_event(
        WorkflowEvent(
            workflow_id=run.workflow_id,
            step="pipeline_end",
            status="completed",
            pipeline="index_repo",
        )
    )

    await session.refresh(run)
    assert run.status == "failed"
    assert run.error == "real boom"
