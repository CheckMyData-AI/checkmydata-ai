from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.base import Base
from app.services.error_log_service import ErrorLogService
from app.services.logs_service import LogsService
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


async def test_list_and_update_errors(session: AsyncSession):
    svc = ErrorLogService()
    e = await svc.upsert(
        session,
        project_id="p",
        source="run",
        kind="db_index",
        message="boom",
        failure_kind="fatal",
    )
    logs = LogsService()
    res = await logs.list_errors(session, "p", source="run")
    assert res["total"] == 1
    assert res["items"][0]["kind"] == "db_index"

    ok = await logs.update_error_status(session, "p", e.id, "resolved")
    assert ok is True
    res2 = await logs.list_errors(session, "p", status="resolved")
    assert res2["total"] == 1

    # filter that excludes it
    res3 = await logs.list_errors(session, "p", source="query")
    assert res3["total"] == 0


async def test_update_error_rejects_bad_status(session: AsyncSession):
    e = await ErrorLogService().upsert(
        session, project_id="p", source="run", kind="db_index", message="x"
    )
    assert await LogsService().update_error_status(session, "p", e.id, "bogus") is False


async def test_list_runs(session: AsyncSession):
    coord = RunCoordinator()
    run = await coord.start(session, kind="db_index", project_id="p", connection_id="c")
    await coord.finish(session, run, "completed")
    rows = await LogsService().list_runs(session, "p", kind="db_index")
    assert len(rows) == 1
    assert rows[0]["status"] == "completed"


async def test_a_resolved_error_that_happens_again_is_open_again(session: AsyncSession):
    """F-E1 (2026-09-23): a recurrence only counted. A row marked `resolved` stayed
    `resolved` with `occurrences` climbing, so the regression the catalog exists to show
    was hidden by the act of triaging it — found while about to resolve 23 rows."""
    svc = ErrorLogService()
    logs = LogsService()
    kw = dict(project_id="p", source="run", kind="db_index", message="boom")
    first = await svc.upsert(session, **kw)
    await logs.update_error_status(session, "p", first.id, "resolved")

    again = await svc.upsert(session, **kw)

    assert again.id == first.id
    assert again.status == "open"
    assert again.occurrences == 2


async def test_an_acknowledged_error_that_happens_again_stays_acknowledged(session: AsyncSession):
    """Acknowledged means 'known and still happening' — a recurrence confirms it."""
    svc = ErrorLogService()
    logs = LogsService()
    kw = dict(project_id="p", source="run", kind="db_index", message="boom")
    first = await svc.upsert(session, **kw)
    await logs.update_error_status(session, "p", first.id, "acknowledged")

    assert (await svc.upsert(session, **kw)).status == "acknowledged"
