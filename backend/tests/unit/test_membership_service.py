"""Unit tests for MembershipService."""

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import app.models.chat_session  # noqa: F401
import app.models.commit_index  # noqa: F401
import app.models.connection  # noqa: F401
import app.models.custom_rule  # noqa: F401
import app.models.knowledge_doc  # noqa: F401
import app.models.project  # noqa: F401
import app.models.project_invite  # noqa: F401
import app.models.project_member  # noqa: F401
import app.models.ssh_key  # noqa: F401
import app.models.user  # noqa: F401
from app.models.base import Base
from app.models.project import Project
from app.models.user import User
from app.services.membership_service import MembershipService


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()


async def _make_user(db: AsyncSession, email: str | None = None) -> User:
    u = User(
        email=email or f"u-{uuid.uuid4().hex[:8]}@test.com", password_hash="x", display_name="T"
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _make_project(db: AsyncSession) -> Project:
    p = Project(name=f"proj-{uuid.uuid4().hex[:6]}")
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


svc = MembershipService()


class TestAddMember:
    @pytest.mark.asyncio
    async def test_creates_new_membership(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)
        member = await svc.add_member(db, proj.id, user.id, "editor")
        assert member.role == "editor"
        assert member.project_id == proj.id
        assert member.user_id == user.id

    @pytest.mark.asyncio
    async def test_updates_existing_role(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)
        await svc.add_member(db, proj.id, user.id, "viewer")
        member = await svc.add_member(db, proj.id, user.id, "editor")
        assert member.role == "editor"


class TestGetRole:
    @pytest.mark.asyncio
    async def test_returns_correct_role(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)
        await svc.add_member(db, proj.id, user.id, "owner")
        role = await svc.get_role(db, proj.id, user.id)
        assert role == "owner"

    @pytest.mark.asyncio
    async def test_returns_none_for_non_member(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)
        role = await svc.get_role(db, proj.id, user.id)
        assert role is None


class TestRequireRole:
    @pytest.mark.asyncio
    async def test_passes_for_sufficient_role(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)
        await svc.add_member(db, proj.id, user.id, "owner")
        result = await svc.require_role(db, proj.id, user.id, "editor")
        assert result == "owner"

    @pytest.mark.asyncio
    async def test_raises_403_for_insufficient_role(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)
        await svc.add_member(db, proj.id, user.id, "viewer")
        with pytest.raises(HTTPException) as exc_info:
            await svc.require_role(db, proj.id, user.id, "owner")
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_raises_403_for_non_member(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)
        with pytest.raises(HTTPException) as exc_info:
            await svc.require_role(db, proj.id, user.id, "viewer")
        assert exc_info.value.status_code == 403


class TestRemoveMember:
    @pytest.mark.asyncio
    async def test_removes_member(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)
        await svc.add_member(db, proj.id, user.id, "editor")
        removed = await svc.remove_member(db, proj.id, user.id)
        assert removed is True
        assert await svc.get_role(db, proj.id, user.id) is None

    @pytest.mark.asyncio
    async def test_raises_400_for_owner(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)
        await svc.add_member(db, proj.id, user.id, "owner")
        with pytest.raises(HTTPException) as exc_info:
            await svc.remove_member(db, proj.id, user.id)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_returns_false_for_non_member(self, db):
        user = await _make_user(db)
        proj = await _make_project(db)
        removed = await svc.remove_member(db, proj.id, user.id)
        assert removed is False


class TestListMembers:
    @pytest.mark.asyncio
    async def test_returns_all_members_with_user_data(self, db):
        u1 = await _make_user(db)
        u2 = await _make_user(db)
        proj = await _make_project(db)
        await svc.add_member(db, proj.id, u1.id, "owner")
        await svc.add_member(db, proj.id, u2.id, "viewer")
        members = await svc.list_members(db, proj.id)
        assert len(members) == 2
        emails = {m.user.email for m in members}
        assert u1.email in emails
        assert u2.email in emails


class TestGetAccessibleProjects:
    @pytest.mark.asyncio
    async def test_returns_correct_projects(self, db):
        user = await _make_user(db)
        p1 = await _make_project(db)
        p2 = await _make_project(db)
        p3 = await _make_project(db)
        await svc.add_member(db, p1.id, user.id, "owner")
        await svc.add_member(db, p2.id, user.id, "viewer")
        projects = await svc.get_accessible_projects(db, user.id)
        pids = {p.id for p in projects}
        assert p1.id in pids
        assert p2.id in pids
        assert p3.id not in pids


class TestGetRolesBulk:
    @pytest.mark.asyncio
    async def test_returns_roles_for_projects(self, db):
        user = await _make_user(db)
        p1 = await _make_project(db)
        p2 = await _make_project(db)
        p3 = await _make_project(db)
        await svc.add_member(db, p1.id, user.id, "owner")
        await svc.add_member(db, p2.id, user.id, "viewer")
        roles = await svc.get_roles_bulk(db, [p1.id, p2.id, p3.id], user.id)
        assert roles[p1.id] == "owner"
        assert roles[p2.id] == "viewer"
        assert p3.id not in roles  # not a member

    @pytest.mark.asyncio
    async def test_empty_list_returns_empty(self, db):
        user = await _make_user(db)
        assert await svc.get_roles_bulk(db, [], user.id) == {}
