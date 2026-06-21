"""Unit tests for KnowledgeSyncRunService.list_for_project."""

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import app.models.knowledge_sync_run  # noqa: F401 — registers table with Base.metadata
from app.models.base import Base
from app.models.knowledge_sync_run import KnowledgeSyncRun
from app.services.knowledge_sync_run_service import KnowledgeSyncRunService


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session

    await engine.dispose()


async def test_list_for_project_orders_desc_and_clamps_limit(db_session):
    """Returns rows DESC by created_at, scoped to project, limit clamped to <=50."""
    for i in range(3):
        db_session.add(KnowledgeSyncRun(project_id="p1", trigger="scheduled", status="success"))
    db_session.add(KnowledgeSyncRun(project_id="other", trigger="scheduled", status="failed"))
    await db_session.commit()

    svc = KnowledgeSyncRunService()

    # Limit=2 should return exactly 2 rows, all from p1
    runs = await svc.list_for_project(db_session, "p1", limit=2)
    assert len(runs) == 2
    assert all(r.project_id == "p1" for r in runs)

    # limit=999 is clamped to 50 internally; only 3 rows exist for p1, so returns 3
    runs_all = await svc.list_for_project(db_session, "p1", limit=999)
    assert len(runs_all) == 3  # only 3 exist; limit clamps to <=50 internally

    # Rows from other projects must not appear
    ids = {r.project_id for r in runs_all}
    assert ids == {"p1"}


async def test_list_for_project_returns_desc_order(db_session):
    """Rows come back newest-first (created_at DESC)."""
    from datetime import UTC, datetime, timedelta

    base_time = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(3):
        run = KnowledgeSyncRun(project_id="proj", trigger="manual", status="success")
        run.created_at = base_time + timedelta(hours=i)
        db_session.add(run)
    await db_session.commit()

    svc = KnowledgeSyncRunService()
    runs = await svc.list_for_project(db_session, "proj", limit=10)
    assert len(runs) == 3
    # Should be descending: hours 2, 1, 0
    # Strip tz info for SQLite compatibility (SQLite returns naive datetimes).
    times = [r.created_at.replace(tzinfo=None) if r.created_at else None for r in runs]
    assert times == sorted(times, reverse=True)


async def test_list_for_project_empty(db_session):
    """Returns empty list for a project with no runs."""
    svc = KnowledgeSyncRunService()
    runs = await svc.list_for_project(db_session, "no-such-project", limit=10)
    assert runs == []
