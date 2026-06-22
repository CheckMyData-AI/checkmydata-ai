from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.api.routes import runs as runs_route
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


def test_runs_router_exposes_routes():
    paths = {r.path for r in runs_route.router.routes}
    assert "/{run_id}/cancel" in paths
    assert "/{run_id}/retry" in paths
    assert "/{run_id}" in paths
    assert "/{run_id}/events" in paths


async def test_run_to_dict_shape(session: AsyncSession):
    run = await RunCoordinator().start(session, kind="db_index", project_id="p", connection_id="c")
    d = runs_route._run_to_dict(run)
    assert d["id"] == run.id
    assert d["kind"] == "db_index"
    assert d["progress_pct"] == 0
    assert d["workflow_id"] == run.workflow_id


async def test_cancel_then_retry_primitives(session: AsyncSession):
    coord = RunCoordinator()
    run = await coord.start(session, kind="db_index", project_id="p2", connection_id="c1")
    assert await coord.request_cancel(session, run.id) is True
    await coord.finish(session, run, "cancelled")
    new = await coord.retry(session, run.id, force_full=False)
    assert new.id != run.id
    assert new.status == "running"
