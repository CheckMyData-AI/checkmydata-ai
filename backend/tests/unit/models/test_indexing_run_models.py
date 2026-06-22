from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401 — register all mappers
from app.models.base import Base
from app.models.indexing_run import IndexingRun, IndexingRunEvent


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


async def test_indexing_run_defaults(session: AsyncSession):
    run = IndexingRun(
        workflow_id="wf-1",
        project_id="proj-1",
        connection_id=None,
        kind="index_repo",
        trigger="manual",
        status="queued",
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    assert run.id
    assert run.step_index == 0
    assert run.total_steps == 0
    assert run.progress_pct == 0
    assert run.cancel_requested is False
    assert run.version == 0
    assert run.created_at is not None


async def test_indexing_run_event_link(session: AsyncSession):
    run = IndexingRun(
        workflow_id="wf-2",
        project_id="p",
        connection_id=None,
        kind="db_index",
        trigger="manual",
        status="running",
    )
    session.add(run)
    await session.commit()

    ev = IndexingRunEvent(
        run_id=run.id,
        step="introspect_schema",
        status="started",
        detail="go",
    )
    session.add(ev)
    await session.commit()

    rows = (
        (await session.execute(select(IndexingRunEvent).where(IndexingRunEvent.run_id == run.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].level == "info"
