from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.base import Base
from app.models.indexing_run import IndexingRun
from app.services.stale_run_reaper import StaleRunReaper


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


async def test_reaper_flips_stuck_run(session: AsyncSession):
    old = datetime.now(UTC) - timedelta(seconds=10_000)
    run = IndexingRun(
        workflow_id="wf",
        project_id="p",
        connection_id=None,
        kind="index_repo",
        trigger="manual",
        status="running",
        heartbeat_at=old,
    )
    session.add(run)
    await session.commit()

    out = await StaleRunReaper().reap_once(session, timeout_seconds=300)
    await session.commit()
    await session.refresh(run)
    assert run.status == "failed"
    assert out["runs"] >= 1


async def test_reaper_ignores_fresh_run(session: AsyncSession):
    run = IndexingRun(
        workflow_id="wf2",
        project_id="p",
        connection_id=None,
        kind="db_index",
        trigger="manual",
        status="running",
        heartbeat_at=datetime.now(UTC),
    )
    session.add(run)
    await session.commit()

    out = await StaleRunReaper().reap_once(session, timeout_seconds=300)
    await session.commit()
    await session.refresh(run)
    assert run.status == "running"
    assert out["runs"] == 0
