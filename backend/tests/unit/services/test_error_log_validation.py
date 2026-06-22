from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.base import Base
from app.models.error_log import ErrorLog
from app.services.error_log_service import ErrorLogService


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


async def test_validation_failure_cataloged(session: AsyncSession):
    await ErrorLogService().upsert_validation_failure(
        session,
        project_id="p",
        kind="data_gate",
        message="percentage 142% exceeds 100",
        sample_ref="wf-1",
    )
    rows = (
        (await session.execute(select(ErrorLog).where(ErrorLog.project_id == "p"))).scalars().all()
    )
    assert len(rows) == 1
    assert rows[0].source == "span"
    assert rows[0].kind == "data_gate"
    assert rows[0].failure_kind == "data_missing"
