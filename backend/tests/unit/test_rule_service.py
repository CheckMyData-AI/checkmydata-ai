"""Unit tests for RuleService."""

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
from app.services.rule_service import RuleService

svc = RuleService()


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


class TestRuleCreate:
    @pytest.mark.asyncio
    async def test_create_basic(self, db):
        proj = await _make_project(db)
        rule = await svc.create(
            db,
            project_id=proj.id,
            name="My Rule",
            content="Always use UTC timestamps",
            format="markdown",
        )
        assert rule.id is not None
        assert rule.name == "My Rule"
        assert rule.content == "Always use UTC timestamps"
        assert rule.project_id == proj.id

    @pytest.mark.asyncio
    async def test_create_global_rule(self, db):
        rule = await svc.create(db, name="Global Rule", content="Global content", format="markdown")
        assert rule.project_id is None
        assert rule.name == "Global Rule"

    @pytest.mark.asyncio
    async def test_create_default_rule(self, db):
        proj = await _make_project(db)
        rule = await svc.create(
            db,
            project_id=proj.id,
            name="Default",
            content="Default content",
            format="markdown",
            is_default=True,
        )
        assert rule.is_default is True


class TestRuleGet:
    @pytest.mark.asyncio
    async def test_get_existing(self, db):
        proj = await _make_project(db)
        rule = await svc.create(db, project_id=proj.id, name="Get", content="c", format="markdown")
        fetched = await svc.get(db, rule.id)
        assert fetched is not None
        assert fetched.id == rule.id

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, db):
        result = await svc.get(db, "no-such-id")
        assert result is None


class TestRuleListAll:
    @pytest.mark.asyncio
    async def test_list_by_project_includes_global(self, db):
        proj = await _make_project(db)
        await svc.create(db, project_id=proj.id, name="Proj Rule", content="p", format="markdown")
        await svc.create(db, name="Global Rule", content="g", format="markdown")

        rules = await svc.list_all(db, project_id=proj.id)
        names = {r.name for r in rules}
        assert "Proj Rule" in names
        assert "Global Rule" in names

    @pytest.mark.asyncio
    async def test_list_without_project_returns_global_only(self, db):
        proj = await _make_project(db)
        await svc.create(db, project_id=proj.id, name="Proj Only", content="p", format="markdown")
        await svc.create(db, name="Global", content="g", format="markdown")

        rules = await svc.list_all(db)
        names = {r.name for r in rules}
        assert "Proj Only" not in names
        assert "Global" in names

    @pytest.mark.asyncio
    async def test_list_scoped_to_project(self, db):
        p1 = await _make_project(db)
        p2 = await _make_project(db)
        await svc.create(db, project_id=p1.id, name="P1 Rule", content="p1", format="markdown")
        await svc.create(db, project_id=p2.id, name="P2 Rule", content="p2", format="markdown")

        rules = await svc.list_all(db, project_id=p1.id)
        names = {r.name for r in rules}
        assert "P1 Rule" in names
        assert "P2 Rule" not in names


class TestRuleUpdate:
    @pytest.mark.asyncio
    async def test_update_content(self, db):
        proj = await _make_project(db)
        rule = await svc.create(
            db, project_id=proj.id, name="Old", content="old", format="markdown"
        )
        updated = await svc.update(db, rule.id, content="new content")
        assert updated is not None
        assert updated.content == "new content"
        assert updated.updated_at is not None

    @pytest.mark.asyncio
    async def test_update_name(self, db):
        proj = await _make_project(db)
        rule = await svc.create(
            db, project_id=proj.id, name="Before", content="c", format="markdown"
        )
        updated = await svc.update(db, rule.id, name="After")
        assert updated is not None
        assert updated.name == "After"

    @pytest.mark.asyncio
    async def test_update_ignores_id_and_created_at(self, db):
        proj = await _make_project(db)
        rule = await svc.create(db, project_id=proj.id, name="Safe", content="c", format="markdown")
        original_id = rule.id
        updated = await svc.update(db, rule.id, id="hacked", created_at="2000-01-01")
        assert updated is not None
        assert updated.id == original_id

    @pytest.mark.asyncio
    async def test_update_nonexistent(self, db):
        result = await svc.update(db, "bad-id", name="x")
        assert result is None


class TestRuleDelete:
    @pytest.mark.asyncio
    async def test_delete_existing(self, db):
        proj = await _make_project(db)
        rule = await svc.create(db, project_id=proj.id, name="Del", content="d", format="markdown")
        result = await svc.delete(db, rule.id)
        assert result is True
        assert await svc.get(db, rule.id) is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, db):
        result = await svc.delete(db, "no-id")
        assert result is False


class TestEnsureDefaultRule:
    @pytest.mark.asyncio
    async def test_creates_default_rule_for_project(self, db):
        proj = await _make_project(db)
        rule = await svc.ensure_default_rule(db, proj.id)
        assert rule is not None
        assert rule.is_default is True
        assert rule.project_id == proj.id
        assert rule.name == "Business Metrics & Guidelines"

    @pytest.mark.asyncio
    async def test_skips_if_already_initialized(self, db):
        proj = await _make_project(db)
        await svc.ensure_default_rule(db, proj.id)
        await db.commit()
        await db.refresh(proj)

        second = await svc.ensure_default_rule(db, proj.id)
        assert second is None

    @pytest.mark.asyncio
    async def test_returns_none_for_missing_project(self, db):
        result = await svc.ensure_default_rule(db, "nonexistent-project-id")
        assert result is None
