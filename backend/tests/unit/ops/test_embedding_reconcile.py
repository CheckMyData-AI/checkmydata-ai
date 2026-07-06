from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.ops.embedding_reconcile as recon
from app.config import settings
from app.models.base import Base
from app.models.deploy_state import DeployState
from app.models.project import Project


@pytest.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(c, tables=[DeployState.__table__, Project.__table__])
        )
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def _current():
    return f"{settings.chroma_embedding_model}|{settings.embedder_max_tokens}"


async def _seed_marker(sf, value):
    async with sf() as s:
        s.add(DeployState(key="embedding_fingerprint", value=value))
        await s.commit()


async def _add_projects(sf, n):
    async with sf() as s:
        for i in range(n):
            s.add(Project(name=f"p{i}"))
        await s.commit()


def test_fingerprint_format():
    assert recon.embedding_fingerprint() == _current()


async def test_unchanged_no_reindex(session_factory, monkeypatch):
    spy = AsyncMock(return_value=[])
    monkeypatch.setattr(recon, "queue_embedding_reindex", spy)
    await _seed_marker(session_factory, _current())
    res = await recon.reconcile_embeddings(session_factory)
    assert res.status == "unchanged"
    spy.assert_not_called()


async def test_changed_triggers_reindex_and_advances_marker(session_factory, monkeypatch):
    spy = AsyncMock(return_value=["job1", "job2"])
    monkeypatch.setattr(recon, "queue_embedding_reindex", spy)
    await _seed_marker(session_factory, "all-MiniLM-L6-v2|256")
    await _add_projects(session_factory, 2)
    res = await recon.reconcile_embeddings(session_factory)
    assert res.status == "reindexed"
    assert res.reindexed == 2
    assert spy.call_count == 1
    assert len(spy.call_args.args[0]) == 2
    async with session_factory() as s:
        row = await s.get(DeployState, "embedding_fingerprint")
    assert row.value == _current()


async def test_marker_not_advanced_on_enqueue_failure(session_factory, monkeypatch):
    spy = AsyncMock(side_effect=RuntimeError("redis down"))
    monkeypatch.setattr(recon, "queue_embedding_reindex", spy)
    await _seed_marker(session_factory, "all-MiniLM-L6-v2|256")
    await _add_projects(session_factory, 1)
    res = await recon.reconcile_embeddings(session_factory)
    assert res.status == "error"
    async with session_factory() as s:
        row = await s.get(DeployState, "embedding_fingerprint")
    assert row.value == "all-MiniLM-L6-v2|256"  # unchanged -> retries next boot


async def test_missing_marker_seeds_without_reindex(session_factory, monkeypatch):
    spy = AsyncMock(return_value=[])
    monkeypatch.setattr(recon, "queue_embedding_reindex", spy)
    res = await recon.reconcile_embeddings(session_factory)
    assert res.status == "seeded"
    spy.assert_not_called()
    async with session_factory() as s:
        row = await s.get(DeployState, "embedding_fingerprint")
    assert row.value == _current()


async def test_changed_with_zero_projects_advances_marker(session_factory, monkeypatch):
    spy = AsyncMock(return_value=[])
    monkeypatch.setattr(recon, "queue_embedding_reindex", spy)
    await _seed_marker(session_factory, "all-MiniLM-L6-v2|256")
    res = await recon.reconcile_embeddings(session_factory)
    assert res.status == "reindexed"
    assert res.reindexed == 0
    assert spy.call_args.args[0] == []
    async with session_factory() as s:
        row = await s.get(DeployState, "embedding_fingerprint")
    assert row.value == _current()
