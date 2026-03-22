"""Unit tests for ProjectCacheService."""

import uuid
from unittest.mock import MagicMock, patch

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
from app.services.project_cache_service import ProjectCacheService

svc = ProjectCacheService()


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


class TestLoadKnowledge:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_cache(self, db):
        proj = await _make_project(db)
        result = await svc.load_knowledge(db, proj.id)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_empty_json(self, db):
        proj = await _make_project(db)
        await svc.save(db, proj.id)
        result = await svc.load_knowledge(db, proj.id)
        assert result is None

    @pytest.mark.asyncio
    @patch("app.services.project_cache_service.ProjectCacheService._get_row")
    async def test_returns_knowledge_on_valid_cache(self, mock_get_row, db):
        mock_knowledge_cls = MagicMock()
        mock_knowledge_instance = MagicMock()
        mock_knowledge_cls.from_json.return_value = mock_knowledge_instance

        mock_cache = MagicMock()
        mock_cache.knowledge_json = '{"tables": []}'
        mock_get_row.return_value = mock_cache

        with patch("app.knowledge.entity_extractor.ProjectKnowledge", mock_knowledge_cls):
            result = await svc.load_knowledge(db, "proj-id")

        assert result is mock_knowledge_instance

    @pytest.mark.asyncio
    @patch("app.services.project_cache_service.ProjectCacheService._get_row")
    async def test_returns_none_on_deserialization_error(self, mock_get_row, db):
        mock_cache = MagicMock()
        mock_cache.knowledge_json = '{"bad": data}'
        mock_get_row.return_value = mock_cache

        with patch("app.knowledge.entity_extractor.ProjectKnowledge") as mock_cls:
            mock_cls.from_json.side_effect = ValueError("bad json")
            result = await svc.load_knowledge(db, "proj-id")

        assert result is None


class TestLoadProfile:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_cache(self, db):
        proj = await _make_project(db)
        result = await svc.load_profile(db, proj.id)
        assert result is None

    @pytest.mark.asyncio
    @patch("app.services.project_cache_service.ProjectCacheService._get_row")
    async def test_returns_profile_on_valid_cache(self, mock_get_row, db):
        mock_profile_cls = MagicMock()
        mock_profile_instance = MagicMock()
        mock_profile_cls.from_json.return_value = mock_profile_instance

        mock_cache = MagicMock()
        mock_cache.profile_json = '{"description": "ecommerce"}'
        mock_get_row.return_value = mock_cache

        with patch("app.knowledge.project_profiler.ProjectProfile", mock_profile_cls):
            result = await svc.load_profile(db, "proj-id")

        assert result is mock_profile_instance

    @pytest.mark.asyncio
    @patch("app.services.project_cache_service.ProjectCacheService._get_row")
    async def test_returns_none_on_deserialization_error(self, mock_get_row, db):
        mock_cache = MagicMock()
        mock_cache.profile_json = '{"bad": data}'
        mock_get_row.return_value = mock_cache

        with patch("app.knowledge.project_profiler.ProjectProfile") as mock_cls:
            mock_cls.from_json.side_effect = ValueError("bad json")
            result = await svc.load_profile(db, "proj-id")

        assert result is None


class TestSave:
    @pytest.mark.asyncio
    async def test_save_creates_new_cache_row(self, db):
        proj = await _make_project(db)

        mock_knowledge = MagicMock()
        mock_knowledge.to_json.return_value = '{"tables": ["users"]}'

        await svc.save(db, proj.id, knowledge=mock_knowledge)

        row = await svc._get_row(db, proj.id)
        assert row is not None
        assert row.knowledge_json == '{"tables": ["users"]}'

    @pytest.mark.asyncio
    async def test_save_updates_existing_cache_row(self, db):
        proj = await _make_project(db)

        mock_k1 = MagicMock()
        mock_k1.to_json.return_value = '{"v": 1}'
        await svc.save(db, proj.id, knowledge=mock_k1)

        mock_k2 = MagicMock()
        mock_k2.to_json.return_value = '{"v": 2}'
        await svc.save(db, proj.id, knowledge=mock_k2)

        row = await svc._get_row(db, proj.id)
        assert row.knowledge_json == '{"v": 2}'

    @pytest.mark.asyncio
    async def test_save_profile_independently(self, db):
        proj = await _make_project(db)

        mock_knowledge = MagicMock()
        mock_knowledge.to_json.return_value = '{"tables": []}'
        await svc.save(db, proj.id, knowledge=mock_knowledge)

        mock_profile = MagicMock()
        mock_profile.to_json.return_value = '{"description": "ecommerce"}'
        await svc.save(db, proj.id, profile=mock_profile)

        row = await svc._get_row(db, proj.id)
        assert row.knowledge_json == '{"tables": []}'
        assert row.profile_json == '{"description": "ecommerce"}'
