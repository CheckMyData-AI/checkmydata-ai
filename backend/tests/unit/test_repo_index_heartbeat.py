"""Real-DB unit test: CheckpointService.touch_heartbeat sets heartbeat_at.

Guards the dependency wiring for Task 9 (heartbeat in _run_index_background).
The actual wrap is covered by the Task 20 integration crash test.
"""

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import app.models.indexing_checkpoint  # noqa: F401 — register model with Base
from app.models.base import Base
from app.services.checkpoint_service import CheckpointService


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session

    await engine.dispose()


async def test_checkpoint_touch_heartbeat(db_session):
    svc = CheckpointService()
    cp = await svc.create(db_session, "pj1", "wf1", head_sha="")
    await svc.touch_heartbeat(db_session, cp.id)
    await db_session.commit()
    await db_session.refresh(cp)
    assert cp.heartbeat_at is not None
