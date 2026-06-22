from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.base import Base
from app.models.error_log import ErrorLog
from app.models.request_trace import RequestTrace
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


async def test_upsert_from_failed_trace(session: AsyncSession):
    tr = RequestTrace(
        id="t1",
        project_id="p",
        user_id="u",
        workflow_id="w",
        question="q",
        status="failed",
        error_message="timeout after 30s",
        failure_kind="transient",
    )
    session.add(tr)
    await session.commit()

    await ErrorLogService().upsert_from_trace(session, tr)
    rows = (
        (await session.execute(select(ErrorLog).where(ErrorLog.project_id == "p"))).scalars().all()
    )
    assert len(rows) == 1
    assert rows[0].source == "query"
    assert rows[0].kind == "chat"
    assert rows[0].sample_ref == "t1"
    assert rows[0].failure_kind == "transient"
