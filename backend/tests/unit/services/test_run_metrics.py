from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.core.metrics import get_metrics_collector
from app.models.base import Base
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


async def test_finish_emits_run_counter(session: AsyncSession):
    coord = RunCoordinator()
    run = await coord.start(session, kind="db_index", project_id="p", connection_id="c")
    await coord.finish(session, run, "completed")
    counters = get_metrics_collector().snapshot_counters(prefix="indexing_runs_total")
    assert any(v >= 1 for v in counters.values())


async def test_step_emits_ttfp(session: AsyncSession):
    coord = RunCoordinator()
    run = await coord.start(session, kind="db_index", project_id="p2", connection_id="c")
    async with coord.step(session, run, "introspect_schema"):
        pass
    counters = get_metrics_collector().snapshot_counters(
        prefix="indexing_run_time_to_first_progress_seconds"
    )
    # the _count companion counter is incremented by .add()
    assert any(v >= 1 for v in counters.values())
