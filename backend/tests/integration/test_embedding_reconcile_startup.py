from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.ops.embedding_reconcile as recon
import app.services.embedding_reindex as reindex_mod
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


class _DummyVectorStore:
    """Lightweight stand-in — avoids loading the real embedding model / Chroma client."""

    def delete_collection(self, project_id: str) -> None:
        pass


async def test_reconcile_drives_real_reindex_path(session_factory, monkeypatch):
    # Real queue_embedding_reindex runs; only its external deps are stubbed.
    enqueue_spy = AsyncMock(return_value="job-1")
    monkeypatch.setattr(reindex_mod, "enqueue", enqueue_spy)
    monkeypatch.setattr(reindex_mod, "VectorStore", _DummyVectorStore)
    async with session_factory() as s:
        s.add(DeployState(key="embedding_fingerprint", value="all-MiniLM-L6-v2|256"))
        s.add(Project(name="p0"))
        await s.commit()

    res = await recon.reconcile_embeddings(session_factory)

    assert res.status == "reindexed"
    assert res.reindexed == 1
    assert enqueue_spy.call_count == 1
    assert enqueue_spy.call_args.args[0] == "run_repo_index"
    assert enqueue_spy.call_args.kwargs.get("force_full") is True


class _FakePgSession:
    """Async-context session whose dialect is postgresql and advisory lock is held."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def get_bind(self):
        return type("_B", (), {"dialect": type("_D", (), {"name": "postgresql"})()})()

    async def scalar(self, *a, **k):
        return False  # pg_try_advisory_xact_lock -> not acquired


async def test_skipped_locked_when_lock_unavailable():
    res = await recon.reconcile_embeddings(_FakePgSession)
    assert res.status == "skipped_locked"
