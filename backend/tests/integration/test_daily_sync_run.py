"""P2: daily sync runs under a first-class daily_sync IndexingRun."""

from __future__ import annotations

import os
import tempfile

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.base import Base
from app.models.indexing_run import IndexingRun
from app.models.project import Project
from app.services.daily_knowledge_sync_service import DailyKnowledgeSyncService


@pytest.fixture
async def file_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield sm
    finally:
        await engine.dispose()
        os.unlink(path)


async def test_daily_sync_creates_daily_run_record(monkeypatch, file_db):
    sm = file_db
    async with sm() as s:
        s.add(Project(id="p", name="x"))  # no repo_url -> orchestration skips early
        await s.commit()

    monkeypatch.setattr("app.services.daily_knowledge_sync_service.async_session_factory", sm)

    result = await DailyKnowledgeSyncService().run_for_project("p")
    assert result.status == "skipped"

    async with sm() as s:
        runs = (
            (await s.execute(select(IndexingRun).where(IndexingRun.kind == "daily_sync")))
            .scalars()
            .all()
        )
    assert len(runs) == 1
    assert runs[0].status == "completed"  # skipped maps to a completed run
    assert runs[0].finished_at is not None
