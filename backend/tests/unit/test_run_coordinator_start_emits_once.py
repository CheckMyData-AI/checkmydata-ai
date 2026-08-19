"""AUD-0819-04: a run announces its start exactly once.

``RunCoordinator.start`` used to broadcast ``pipeline_start`` twice — once from
``tracker.begin`` and again from ``_record`` — so production logged four lines
per run (two emissions x emitting process + Redis-relayed subscriber) and every
SSE subscriber saw the step twice:

    00:00:12.303 app[worker.1]  workflow[859ee38d] pipeline_start: started
    00:00:12.368 app[web.1]     workflow[859ee38d] pipeline_start: started
    00:00:12.427 app[worker.1]  workflow[859ee38d] pipeline_start: started
    00:00:12.428 app[web.1]     workflow[859ee38d] pipeline_start: started

The terminal path was already written the other way round and says so in
``run_coordinator.py`` ("Journal the terminal event directly; tracker.end emits
the canonical SSE"); the start path was the oversight. The surviving event must
be the run-scoped one, because ``run_id`` is what lets the UI attach the step to
a run.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.core.workflow_tracker import tracker
from app.models.base import Base
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


async def test_start_broadcasts_pipeline_start_exactly_once(session: AsyncSession):
    queue = await tracker.subscribe()
    try:
        run = await RunCoordinator().start(
            session, kind="db_index", project_id="p-once", connection_id="c1"
        )
    finally:
        await tracker.unsubscribe(queue)

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    starts = [e for e in events if e.step == "pipeline_start"]
    assert len(starts) == 1, f"pipeline_start broadcast {len(starts)} times: {starts}"
    # The one that survives is the run-scoped event the UI needs.
    assert starts[0].run_id == run.id
    assert starts[0].workflow_id == run.workflow_id


async def test_start_journals_pipeline_start_exactly_once(session: AsyncSession):
    """The durable projection keeps one row, as it always did."""
    run = await RunCoordinator().start(
        session, kind="db_index", project_id="p-journal", connection_id="c1"
    )
    rows = (
        (
            await session.execute(
                select(IndexingRunEvent).where(
                    IndexingRunEvent.run_id == run.id,
                    IndexingRunEvent.step == "pipeline_start",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
