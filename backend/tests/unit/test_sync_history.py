"""Unit tests for SyncHistoryService.list_for_project (daily_sync runs)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.base import Base
from app.services.run_coordinator import RunCoordinator
from app.services.sync_history_service import SyncHistoryService


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


async def test_lists_daily_runs_for_project_only(session: AsyncSession):
    coord = RunCoordinator()
    r1 = await coord.start(session, kind="daily_sync", project_id="p1", connection_id=None)
    await coord.finish(session, r1, "completed")
    # a daily_sync run for another project must not leak
    r2 = await coord.start(session, kind="daily_sync", project_id="other", connection_id=None)
    await coord.finish(session, r2, "failed", error="x")
    # a non-daily run for p1 must not appear
    await coord.start(session, kind="db_index", project_id="p1", connection_id="c1")

    rows = await SyncHistoryService().list_for_project(session, "p1", limit=10)
    assert len(rows) == 1
    assert rows[0]["kind"] == "daily_sync"
    assert rows[0]["status"] == "completed"
    assert rows[0]["duration_seconds"] is not None


async def test_empty_when_no_runs(session: AsyncSession):
    rows = await SyncHistoryService().list_for_project(session, "nope", limit=10)
    assert rows == []
