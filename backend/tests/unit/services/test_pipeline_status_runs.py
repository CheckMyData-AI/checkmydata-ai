from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.base import Base
from app.services.pipeline_status_service import PipelineStatusService
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


async def test_status_reflects_active_run(session: AsyncSession):
    await RunCoordinator().start(session, kind="db_index", project_id="p", connection_id="c")
    status = await PipelineStatusService().get_status(session, "p")
    assert status["any_running"] is True
    conn = next(c for c in status["connections"] if c["connection_id"] == "c")
    assert conn["db_index"]["is_indexing"] is True
    assert conn["db_index"]["run_id"]
    assert "progress_pct" in conn["db_index"]


async def test_synthetic_active_tasks_from_runs(session: AsyncSession):
    run = await RunCoordinator().start(
        session, kind="code_db_sync", project_id="p2", connection_id="c2"
    )
    tasks = await PipelineStatusService().list_synthetic_active_tasks(
        session, accessible_project_ids={"p2"}
    )
    assert len(tasks) == 1
    assert tasks[0]["run_id"] == run.id
    assert tasks[0]["pipeline"] == "code_db_sync"
    assert tasks[0]["extra"]["connection_id"] == "c2"


async def test_idle_project_has_no_running(session: AsyncSession):
    status = await PipelineStatusService().get_status(session, "empty")
    assert status["any_running"] is False
    assert status["repo"]["is_indexing"] is False
