"""Unit tests for InviteService."""

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
from app.services.invite_service import InviteService
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


inv_svc = InviteService()
mem_svc = MembershipService()


class TestCreateInvite:
    @pytest.mark.asyncio
    async def test_creates_pending_invite(self, db):
        owner = await _make_user(db)
        proj = await _make_project(db)
        invite = await inv_svc.create_invite(db, proj.id, "invited@test.com", "editor", owner.id)
        assert invite.status == "pending"
        assert invite.email == "invited@test.com"
        assert invite.role == "editor"

    @pytest.mark.asyncio
    async def test_rejects_duplicate_pending_invite(self, db):
        owner = await _make_user(db)
        proj = await _make_project(db)
        await inv_svc.create_invite(db, proj.id, "dup@test.com", "editor", owner.id)
        with pytest.raises(HTTPException) as exc_info:
            await inv_svc.create_invite(db, proj.id, "dup@test.com", "viewer", owner.id)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_rejects_existing_member(self, db):
        owner = await _make_user(db)
        member = await _make_user(db, email="member@test.com")
        proj = await _make_project(db)
        await mem_svc.add_member(db, proj.id, member.id, "viewer")
        with pytest.raises(HTTPException) as exc_info:
            await inv_svc.create_invite(db, proj.id, "member@test.com", "editor", owner.id)
        assert exc_info.value.status_code == 409


class TestListInvites:
    @pytest.mark.asyncio
    async def test_returns_project_invites(self, db):
        owner = await _make_user(db)
        proj = await _make_project(db)
        await inv_svc.create_invite(db, proj.id, "a@t.com", "editor", owner.id)
        await inv_svc.create_invite(db, proj.id, "b@t.com", "viewer", owner.id)
        invites = await inv_svc.list_invites(db, proj.id)
        assert len(invites) == 2


class TestRevokeInvite:
    @pytest.mark.asyncio
    async def test_marks_invite_as_revoked(self, db):
        owner = await _make_user(db)
        proj = await _make_project(db)
        invite = await inv_svc.create_invite(db, proj.id, "rev@t.com", "editor", owner.id)
        result = await inv_svc.revoke_invite(db, invite.id, owner.id)
        assert result is True
        await db.refresh(invite)
        assert invite.status == "revoked"

    @pytest.mark.asyncio
    async def test_fails_on_non_pending_invite(self, db):
        owner = await _make_user(db)
        proj = await _make_project(db)
        invite = await inv_svc.create_invite(db, proj.id, "rev2@t.com", "editor", owner.id)
        await inv_svc.revoke_invite(db, invite.id, owner.id)
        with pytest.raises(HTTPException) as exc_info:
            await inv_svc.revoke_invite(db, invite.id, owner.id)
        assert exc_info.value.status_code == 400


class TestAcceptInvite:
    @pytest.mark.asyncio
    async def test_creates_membership_and_marks_accepted(self, db):
        owner = await _make_user(db)
        user = await _make_user(db)
        proj = await _make_project(db)
        invite = await inv_svc.create_invite(db, proj.id, user.email, "editor", owner.id)
        member, returned_invite = await inv_svc.accept_invite(db, invite.id, user.id)
        assert member.role == "editor"
        assert member.project_id == proj.id
        assert returned_invite.id == invite.id
        await db.refresh(returned_invite)
        assert returned_invite.status == "accepted"
        assert returned_invite.accepted_at is not None

    @pytest.mark.asyncio
    async def test_returns_invite_with_relationships(self, db):
        owner = await _make_user(db)
        user = await _make_user(db)
        proj = await _make_project(db)
        invite = await inv_svc.create_invite(db, proj.id, user.email, "editor", owner.id)
        _member, returned_invite = await inv_svc.accept_invite(db, invite.id, user.id)
        assert returned_invite.inviter is not None
        assert returned_invite.inviter.id == owner.id
        assert returned_invite.project is not None
        assert returned_invite.project.id == proj.id

    @pytest.mark.asyncio
    async def test_does_not_duplicate_if_already_member(self, db):
        owner = await _make_user(db)
        user_email = f"dup-{uuid.uuid4().hex[:6]}@t.com"
        user = await _make_user(db, email=user_email)
        proj = await _make_project(db)
        await mem_svc.add_member(db, proj.id, user.id, "viewer")

        proj2 = await _make_project(db)
        invite = await inv_svc.create_invite(db, proj2.id, user_email, "editor", owner.id)
        await mem_svc.add_member(db, proj2.id, user.id, "viewer")
        member, _inv = await inv_svc.accept_invite(db, invite.id, user.id)
        assert member.role == "viewer"

    @pytest.mark.asyncio
    async def test_fails_on_non_pending_invite(self, db):
        owner = await _make_user(db)
        user = await _make_user(db)
        proj = await _make_project(db)
        invite = await inv_svc.create_invite(db, proj.id, user.email, "editor", owner.id)
        await inv_svc.revoke_invite(db, invite.id, owner.id)
        with pytest.raises(HTTPException) as exc_info:
            await inv_svc.accept_invite(db, invite.id, user.id)
        assert exc_info.value.status_code == 400


class TestListPendingForEmail:
    @pytest.mark.asyncio
    async def test_returns_only_pending_invites(self, db):
        owner = await _make_user(db)
        proj = await _make_project(db)
        email = f"pending-{uuid.uuid4().hex[:6]}@test.com"
        await inv_svc.create_invite(db, proj.id, email, "editor", owner.id)
        inv2 = await inv_svc.create_invite(
            db,
            await _make_project(db).then(lambda p: p.id) if False else (await _make_project(db)).id,
            email,
            "viewer",
            owner.id,
        )  # noqa: E501
        await inv_svc.revoke_invite(db, inv2.id, owner.id)
        pending = await inv_svc.list_pending_for_email(db, email)
        assert len(pending) == 1
        assert pending[0].role == "editor"


class TestGetPendingInvite:
    @pytest.mark.asyncio
    async def test_returns_pending_invite_with_relationships(self, db):
        owner = await _make_user(db)
        proj = await _make_project(db)
        invite = await inv_svc.create_invite(db, proj.id, "get@t.com", "editor", owner.id)
        result = await inv_svc.get_pending_invite(db, invite.id, proj.id)
        assert result is not None
        assert result.id == invite.id
        assert result.status == "pending"

    @pytest.mark.asyncio
    async def test_returns_none_for_non_pending(self, db):
        owner = await _make_user(db)
        proj = await _make_project(db)
        invite = await inv_svc.create_invite(db, proj.id, "rev3@t.com", "editor", owner.id)
        await inv_svc.revoke_invite(db, invite.id, owner.id)
        result = await inv_svc.get_pending_invite(db, invite.id, proj.id)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_wrong_project(self, db):
        owner = await _make_user(db)
        proj = await _make_project(db)
        proj2 = await _make_project(db)
        invite = await inv_svc.create_invite(db, proj.id, "wrong@t.com", "editor", owner.id)
        result = await inv_svc.get_pending_invite(db, invite.id, proj2.id)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_nonexistent_id(self, db):
        proj = await _make_project(db)
        result = await inv_svc.get_pending_invite(db, "nonexistent-id", proj.id)
        assert result is None


class TestAutoAcceptForUser:
    @pytest.mark.asyncio
    async def test_accepts_all_pending_invites(self, db):
        owner = await _make_user(db)
        email = f"newuser-{uuid.uuid4().hex[:6]}@test.com"
        p1 = await _make_project(db)
        p2 = await _make_project(db)
        await inv_svc.create_invite(db, p1.id, email, "editor", owner.id)
        await inv_svc.create_invite(db, p2.id, email, "viewer", owner.id)
        user = await _make_user(db, email=email)
        members = await inv_svc.auto_accept_for_user(db, user.id, email)
        assert len(members) == 2
        roles = {m.role for m in members}
        assert "editor" in roles
        assert "viewer" in roles
