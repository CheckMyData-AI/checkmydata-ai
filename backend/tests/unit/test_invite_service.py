"""Unit tests for InviteService."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
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
from app.models.project_invite import ProjectInvite
from app.models.project_member import ProjectMember
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


class TestDeclineInvite:
    @pytest.mark.asyncio
    async def test_removes_pending_invite_for_invitee(self, db):
        owner = await _make_user(db)
        email = f"decline-{uuid.uuid4().hex[:6]}@test.com"
        user = await _make_user(db, email=email)
        proj = await _make_project(db)
        invite = await inv_svc.create_invite(db, proj.id, email, "editor", owner.id)

        result = await inv_svc.decline_invite(
            db, invite.id, {"email": user.email, "user_id": user.id}
        )

        assert result == {"ok": True}
        # Row is deleted (not status-flipped) so re-invite stays constraint-safe.
        remaining = await db.execute(select(ProjectInvite).where(ProjectInvite.id == invite.id))
        assert remaining.scalar_one_or_none() is None
        assert await inv_svc.list_pending_for_email(db, email) == []

    @pytest.mark.asyncio
    async def test_case_insensitive_email_match(self, db):
        owner = await _make_user(db)
        email = f"mixed-{uuid.uuid4().hex[:6]}@test.com"
        proj = await _make_project(db)
        invite = await inv_svc.create_invite(db, proj.id, email, "editor", owner.id)

        result = await inv_svc.decline_invite(
            db, invite.id, {"email": email.upper(), "user_id": "u"}
        )

        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_forbidden_for_wrong_user(self, db):
        owner = await _make_user(db)
        proj = await _make_project(db)
        invite = await inv_svc.create_invite(db, proj.id, "target@test.com", "editor", owner.id)

        with pytest.raises(HTTPException) as exc_info:
            await inv_svc.decline_invite(
                db, invite.id, {"email": "intruder@test.com", "user_id": "x"}
            )
        assert exc_info.value.status_code == 403
        # The invite is left untouched for its rightful owner.
        assert await inv_svc.get_pending_invite(db, invite.id, proj.id) is not None

    @pytest.mark.asyncio
    async def test_rejects_non_pending_invite(self, db):
        owner = await _make_user(db)
        email = f"nonp-{uuid.uuid4().hex[:6]}@test.com"
        proj = await _make_project(db)
        invite = await inv_svc.create_invite(db, proj.id, email, "editor", owner.id)
        await inv_svc.revoke_invite(db, invite.id, owner.id)

        with pytest.raises(HTTPException) as exc_info:
            await inv_svc.decline_invite(db, invite.id, {"email": email, "user_id": "x"})
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_not_found_for_unknown_invite(self, db):
        with pytest.raises(HTTPException) as exc_info:
            await inv_svc.decline_invite(
                db, "nonexistent-id", {"email": "a@test.com", "user_id": "x"}
            )
        assert exc_info.value.status_code == 404


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


class TestAcceptIsOneTransaction:
    """F-PROJ-03, with the board's symptom corrected.

    The row read "commits inside `begin_nested()` → 500 on idempotent re-accept."
    Measured on SQLAlchemy 2.0.51 + aiosqlite, it does not 500: a `commit()` inside an
    open SAVEPOINT deactivates the savepoint transaction, which exits quietly. A direct
    reproduction outside this codebase behaved the same, and the bookkeeping lives in
    `SessionTransaction`, shared across dialects, so Postgres does not differ.

    What was real is that the savepoint bought nothing — the early return committed
    inside it and the normal path committed after it, so no rollback path existed for it
    to provide — and that committing inside an open one works by accident of this library
    version. These tests pin the behaviour the block is supposed to have, so the
    restructuring cannot quietly change it.
    """

    async def test_no_savepoint_is_opened(self):
        """A savepoint that never rolls back reads as a guarantee and is decoration.

        Checked on the AST rather than the text: the first version searched the source
        for `"begin_nested"` and failed against the comment explaining why the savepoint
        was removed. A string search over source cannot tell code from prose, and the
        prose here is specifically about the thing being searched for.
        """
        import ast
        import inspect
        import textwrap

        tree = ast.parse(textwrap.dedent(inspect.getsource(inv_svc.accept_invite)))
        calls = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "begin_nested"
        ]

        assert not calls, "accept_invite opens a savepoint again"

    async def test_accepting_twice_settles_the_same_way(self, db):
        """The idempotence the finding was named after, now asserted rather than assumed:
        two clicks on one link leave one membership and an accepted invite."""
        owner = await _make_user(db)
        email = f"twice-{uuid.uuid4().hex[:6]}@t.com"
        user = await _make_user(db, email=email)
        proj = await _make_project(db)
        invite = await inv_svc.create_invite(db, proj.id, email, "editor", owner.id)

        first, _ = await inv_svc.accept_invite(db, invite.id, user.id)

        with pytest.raises(HTTPException) as exc:
            await inv_svc.accept_invite(db, invite.id, user.id)
        assert exc.value.status_code == 400, "a spent invite is no longer pending"

        members = (
            (
                await db.execute(
                    select(ProjectMember).where(
                        ProjectMember.project_id == proj.id,
                        ProjectMember.user_id == user.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(members) == 1
        assert members[0].id == first.id

    async def test_an_existing_member_still_marks_the_invite_accepted(self, db):
        """The early-return branch. It committed inside the savepoint before; it commits
        once now, and the invite must not be left pending either way — a pending invite
        for someone already in the project is a row that never resolves.

        The membership is added **after** the invite, and that ordering is the branch's
        whole reason to exist: `create_invite` answers 409 for someone who is already a
        member, so this state is only reachable when they join between the invite being
        sent and it being clicked. Setting it up the other way round makes the test fail
        at setup and proves nothing about accept.
        """
        owner = await _make_user(db)
        email = f"member-{uuid.uuid4().hex[:6]}@t.com"
        user = await _make_user(db, email=email)
        proj = await _make_project(db)
        invite = await inv_svc.create_invite(db, proj.id, email, "editor", owner.id)
        await mem_svc.add_member(db, proj.id, user.id, "viewer")

        member, returned = await inv_svc.accept_invite(db, invite.id, user.id)

        assert member.role == "viewer", "an existing membership is not silently upgraded"
        assert returned.status == "accepted"
        assert returned.accepted_at is not None

    async def test_an_expired_invite_leaves_no_membership_behind(self, db):
        """The 410 used to be raised inside the savepoint, so the rollback was doing
        visible work there. Without it, the raise must still happen before anything is
        written — this is the test that says the removal was safe."""
        owner = await _make_user(db)
        email = f"expired-{uuid.uuid4().hex[:6]}@t.com"
        user = await _make_user(db, email=email)
        proj = await _make_project(db)
        invite = await inv_svc.create_invite(db, proj.id, email, "editor", owner.id)
        invite.expires_at = datetime.now(UTC) - timedelta(days=1)
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await inv_svc.accept_invite(db, invite.id, user.id)
        assert exc.value.status_code == 410

        members = (
            (await db.execute(select(ProjectMember).where(ProjectMember.project_id == proj.id)))
            .scalars()
            .all()
        )
        assert members == []
        await db.refresh(invite)
        assert invite.status == "pending", "a refused invite must not be marked accepted"
