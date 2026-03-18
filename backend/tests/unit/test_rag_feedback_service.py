"""Unit tests for RAGFeedbackService."""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import app.models.chat_session  # noqa: F401
import app.models.commit_index  # noqa: F401
import app.models.connection  # noqa: F401
import app.models.custom_rule  # noqa: F401
import app.models.indexing_checkpoint  # noqa: F401
import app.models.knowledge_doc  # noqa: F401
import app.models.project  # noqa: F401
import app.models.project_cache  # noqa: F401
import app.models.project_invite  # noqa: F401
import app.models.project_member  # noqa: F401
import app.models.rag_feedback  # noqa: F401
import app.models.ssh_key  # noqa: F401
import app.models.user  # noqa: F401
from app.models.base import Base
from app.models.project import Project
from app.services.rag_feedback_service import RAGFeedbackService

svc = RAGFeedbackService()


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()


async def _make_project(db: AsyncSession) -> Project:
    p = Project(name=f"proj-{uuid.uuid4().hex[:6]}")
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


class TestRecord:
    @pytest.mark.asyncio
    async def test_record_single_source(self, db):
        proj = await _make_project(db)
        await svc.record(
            db,
            project_id=proj.id,
            rag_sources=[
                {
                    "chunk_id": "c1",
                    "source_path": "models/user.py",
                    "doc_type": "orm_model",
                    "distance": 0.12,
                }
            ],
            query_succeeded=True,
            question_snippet="show users",
        )

        stats = await svc.get_stats(db, proj.id)
        assert len(stats) == 1
        assert stats[0]["source_path"] == "models/user.py"
        assert stats[0]["total"] == 1
        assert stats[0]["successes"] == 1

    @pytest.mark.asyncio
    async def test_record_multiple_sources(self, db):
        proj = await _make_project(db)
        await svc.record(
            db,
            project_id=proj.id,
            rag_sources=[
                {"chunk_id": "c1", "source_path": "a.py", "doc_type": "orm"},
                {"chunk_id": "c2", "source_path": "b.py", "doc_type": "migration"},
            ],
            query_succeeded=True,
        )

        stats = await svc.get_stats(db, proj.id)
        assert len(stats) == 2

    @pytest.mark.asyncio
    async def test_record_empty_sources_skips_commit(self, db):
        proj = await _make_project(db)
        await svc.record(
            db,
            project_id=proj.id,
            rag_sources=[],
            query_succeeded=True,
        )
        stats = await svc.get_stats(db, proj.id)
        assert len(stats) == 0

    @pytest.mark.asyncio
    async def test_record_truncates_long_snippet(self, db):
        proj = await _make_project(db)
        long_snippet = "x" * 500
        await svc.record(
            db,
            project_id=proj.id,
            rag_sources=[
                {"chunk_id": "c1", "source_path": "f.py", "doc_type": "t"},
            ],
            query_succeeded=False,
            question_snippet=long_snippet,
        )
        stats = await svc.get_stats(db, proj.id)
        assert stats[0]["successes"] == 0


class TestGetStats:
    @pytest.mark.asyncio
    async def test_empty_stats_for_new_project(self, db):
        proj = await _make_project(db)
        stats = await svc.get_stats(db, proj.id)
        assert stats == []

    @pytest.mark.asyncio
    async def test_aggregates_by_source_path(self, db):
        proj = await _make_project(db)
        await svc.record(
            db,
            project_id=proj.id,
            rag_sources=[{"chunk_id": "c1", "source_path": "a.py"}],
            query_succeeded=True,
        )
        await svc.record(
            db,
            project_id=proj.id,
            rag_sources=[{"chunk_id": "c2", "source_path": "a.py"}],
            query_succeeded=False,
        )
        await svc.record(
            db,
            project_id=proj.id,
            rag_sources=[{"chunk_id": "c3", "source_path": "a.py"}],
            query_succeeded=True,
        )

        stats = await svc.get_stats(db, proj.id)
        assert len(stats) == 1
        assert stats[0]["source_path"] == "a.py"
        assert stats[0]["total"] == 3
        assert stats[0]["successes"] == 2

    @pytest.mark.asyncio
    async def test_stats_scoped_to_project(self, db):
        p1 = await _make_project(db)
        p2 = await _make_project(db)
        await svc.record(
            db,
            project_id=p1.id,
            rag_sources=[{"chunk_id": "c1", "source_path": "a.py"}],
            query_succeeded=True,
        )
        await svc.record(
            db,
            project_id=p2.id,
            rag_sources=[{"chunk_id": "c2", "source_path": "b.py"}],
            query_succeeded=True,
        )

        stats_p1 = await svc.get_stats(db, p1.id)
        assert len(stats_p1) == 1
        assert stats_p1[0]["source_path"] == "a.py"
