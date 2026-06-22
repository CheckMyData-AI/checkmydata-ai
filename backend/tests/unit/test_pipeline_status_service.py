"""Unit tests for PipelineStatusService (sourced from active IndexingRun rows)."""

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


async def test_get_status_any_running_when_repo_run_active(session: AsyncSession):
    run = await RunCoordinator().start(
        session, kind="index_repo", project_id="proj-1", connection_id=None
    )
    result = await PipelineStatusService().get_status(session, "proj-1")
    assert result["any_running"] is True
    assert result["repo"]["is_indexing"] is True
    assert result["repo"]["workflow_id"] == run.workflow_id


async def test_list_synthetic_active_tasks_empty_when_no_active_runs(session: AsyncSession):
    result = await PipelineStatusService().list_synthetic_active_tasks(
        session, accessible_project_ids={"proj-1"}
    )
    assert result == []


async def test_list_synthetic_active_tasks_returns_active_runs(session: AsyncSession):
    run = await RunCoordinator().start(
        session, kind="db_index", project_id="proj-1", connection_id="c1"
    )
    result = await PipelineStatusService().list_synthetic_active_tasks(
        session, accessible_project_ids={"proj-1"}
    )
    assert len(result) == 1
    assert result[0]["run_id"] == run.id
    assert result[0]["pipeline"] == "db_index"
