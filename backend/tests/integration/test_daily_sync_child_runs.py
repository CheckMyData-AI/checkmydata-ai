"""P2: daily-sync sub-operations create child IndexingRuns."""

from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

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


async def test_child_db_index_run_created(monkeypatch, file_db):
    sm = file_db
    async with sm() as s:
        s.add(Project(id="p", name="x"))
        await s.commit()
    monkeypatch.setattr("app.services.daily_knowledge_sync_service.async_session_factory", sm)

    svc = DailyKnowledgeSyncService()
    monkeypatch.setattr(svc._conn_svc, "get", AsyncMock(return_value=SimpleNamespace(id="c1")))
    monkeypatch.setattr(svc._conn_svc, "to_config", AsyncMock(return_value=object()))

    from app.services.db_index_service import DbIndexService

    monkeypatch.setattr(DbIndexService, "get_indexing_status", AsyncMock(return_value="idle"))
    monkeypatch.setattr(DbIndexService, "set_indexing_status", AsyncMock())

    async def fake_run(self, *, connection_id, connection_config, project_id, wf_id=None):
        return {"status": "ok", "tables": 1}

    monkeypatch.setattr("app.knowledge.db_index_pipeline.DbIndexPipeline.run", fake_run)
    monkeypatch.setattr("app.api.routes.connections._regenerate_overview", AsyncMock())
    monkeypatch.setattr("app.api.routes.connections._run_data_probes", AsyncMock())

    status, _err = await svc._run_db_index("c1", "p")
    assert status == "completed"

    async with sm() as s:
        runs = (
            (
                await s.execute(
                    select(IndexingRun).where(
                        IndexingRun.kind == "db_index", IndexingRun.connection_id == "c1"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(runs) == 1
