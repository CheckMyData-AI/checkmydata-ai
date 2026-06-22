from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.base import Base
from app.models.error_log import ErrorLog


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


async def test_error_log_defaults(session: AsyncSession):
    e = ErrorLog(
        project_id="p",
        signature="sig-1",
        source="run",
        kind="index_repo",
        message="boom",
    )
    session.add(e)
    await session.commit()
    await session.refresh(e)
    assert e.id
    assert e.occurrences == 1
    assert e.status == "open"
    assert e.first_seen_at is not None
    assert e.last_seen_at is not None
