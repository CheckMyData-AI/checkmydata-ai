from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.base import Base
from app.models.project import Project
from app.services.sync_schedule_service import SyncScheduleService


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


async def test_effective_schedule_falls_back_to_global(session: AsyncSession):
    session.add(Project(id="p", name="x"))  # NULL overrides
    await session.commit()
    eff = await SyncScheduleService().effective(session, "p")
    assert eff["source"] == "global"
    assert "hour" in eff
    assert "enabled" in eff


async def test_project_override_wins(session: AsyncSession):
    session.add(Project(id="p2", name="x", sync_schedule_enabled=False, sync_schedule_hour=5))
    await session.commit()
    eff = await SyncScheduleService().effective(session, "p2")
    assert eff["enabled"] is False
    assert eff["hour"] == 5
    assert eff["source"] == "project"


async def test_set_override_then_effective(session: AsyncSession):
    session.add(Project(id="p3", name="x"))
    await session.commit()
    svc = SyncScheduleService()
    eff = await svc.set_override(session, "p3", enabled=True, hour=9)
    assert eff["enabled"] is True
    assert eff["hour"] == 9
    assert eff["source"] == "project"
