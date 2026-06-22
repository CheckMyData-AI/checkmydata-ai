from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.base import Base
from app.models.indexing_run import IndexingRun, IndexingRunEvent
from app.services.telemetry_retention import TelemetryRetention


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


async def test_sweep_deletes_old_events(session: AsyncSession):
    run = IndexingRun(
        workflow_id="w",
        project_id="p",
        connection_id=None,
        kind="db_index",
        trigger="manual",
        status="completed",
    )
    session.add(run)
    await session.commit()
    old = datetime.now(UTC) - timedelta(days=100)
    session.add(IndexingRunEvent(run_id=run.id, step="x", status="completed", ts=old))
    await session.commit()

    out = await TelemetryRetention().sweep(session, ttl_days=30, max_per_run=500, error_ttl_days=90)
    await session.commit()
    remaining = (
        (await session.execute(select(IndexingRunEvent).where(IndexingRunEvent.run_id == run.id)))
        .scalars()
        .all()
    )
    assert remaining == []
    assert out["events_deleted"] >= 1


async def test_sweep_caps_events_per_run(session: AsyncSession):
    run = IndexingRun(
        workflow_id="w2",
        project_id="p",
        connection_id=None,
        kind="db_index",
        trigger="manual",
        status="completed",
    )
    session.add(run)
    await session.commit()
    now = datetime.now(UTC)
    for i in range(10):
        session.add(
            IndexingRunEvent(
                run_id=run.id,
                step=f"s{i}",
                status="completed",
                ts=now - timedelta(seconds=10 - i),
            )
        )
    await session.commit()

    out = await TelemetryRetention().sweep(session, ttl_days=30, max_per_run=3, error_ttl_days=90)
    await session.commit()
    remaining = (
        (await session.execute(select(IndexingRunEvent).where(IndexingRunEvent.run_id == run.id)))
        .scalars()
        .all()
    )
    assert len(remaining) == 3
    assert out["events_deleted"] >= 7
