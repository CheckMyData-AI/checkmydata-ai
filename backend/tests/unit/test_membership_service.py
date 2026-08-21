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


# ---------------------------------------------------------------------------
# F-PROJ-10: the owner was permanent, so a departure stranded the workspace
# ---------------------------------------------------------------------------


class TestTransferOwnership:
    """`update_member_role` refuses to touch an owner and `RoleUpdate.role` is
    `Literal["editor", "viewer"]`, so before this there was no path — none — to make
    anyone else the owner or to stop being one. `Project.owner_id` is
    `ondelete="SET NULL"`, so deleting the account left the project with no owner at
    all and nobody who could appoint one.
    """

    @pytest.mark.asyncio
    async def test_owner_moves_and_the_old_owner_becomes_an_editor(self, db):
        old = await _make_user(db)
        new = await _make_user(db)
        proj = await _make_project(db)
        proj.owner_id = old.id
        await db.commit()
        await svc.add_member(db, proj.id, new.id, "editor")

        await svc.transfer_ownership(db, proj.id, new_owner_user_id=new.id, actor_user_id=old.id)

        assert await svc.get_role(db, proj.id, new.id) == "owner"
        # Demoted, not removed: taking someone's access away is a different decision
        # from taking their ownership away, and only one of them was asked for.
        assert await svc.get_role(db, proj.id, old.id) == "editor"

    @pytest.mark.asyncio
    async def test_both_sources_of_truth_agree_afterwards(self, db):
        """`get_role` resolves owner from a member row OR `Project.owner_id`.

        Updating only one of them leaves two owners — the new one by the column and
        the old one by the row — which is worse than having none.
        """
        old = await _make_user(db)
        new = await _make_user(db)
        proj = await _make_project(db)
        proj.owner_id = old.id
        await db.commit()
        await svc.add_member(db, proj.id, old.id, "owner")
        await svc.add_member(db, proj.id, new.id, "viewer")

        await svc.transfer_ownership(db, proj.id, new_owner_user_id=new.id, actor_user_id=old.id)

        fresh = await db.get(Project, proj.id)
        assert fresh.owner_id == new.id
        assert await svc.get_role(db, proj.id, old.id) == "editor"
        assert await svc.get_role(db, proj.id, new.id) == "owner"

    @pytest.mark.asyncio
    async def test_non_owner_cannot_transfer(self, db):
        owner = await _make_user(db)
        editor = await _make_user(db)
        other = await _make_user(db)
        proj = await _make_project(db)
        proj.owner_id = owner.id
        await db.commit()
        await svc.add_member(db, proj.id, editor.id, "editor")
        await svc.add_member(db, proj.id, other.id, "editor")

        with pytest.raises(HTTPException) as exc:
            await svc.transfer_ownership(
                db, proj.id, new_owner_user_id=other.id, actor_user_id=editor.id
            )
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_target_must_already_be_a_member(self, db):
        """Transfer must not double as a covert access grant."""
        owner = await _make_user(db)
        stranger = await _make_user(db)
        proj = await _make_project(db)
        proj.owner_id = owner.id
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await svc.transfer_ownership(
                db, proj.id, new_owner_user_id=stranger.id, actor_user_id=owner.id
            )
        assert exc.value.status_code == 400
        assert "member" in exc.value.detail.lower()

    @pytest.mark.asyncio
    async def test_transferring_to_the_current_owner_is_refused(self, db):
        owner = await _make_user(db)
        proj = await _make_project(db)
        proj.owner_id = owner.id
        await db.commit()
        await svc.add_member(db, proj.id, owner.id, "owner")

        with pytest.raises(HTTPException) as exc:
            await svc.transfer_ownership(
                db, proj.id, new_owner_user_id=owner.id, actor_user_id=owner.id
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_an_admin_can_rescue_an_orphaned_project(self, db):
        """`owner_id` is SET NULL on user delete, so nobody is owner and nobody can
        appoint one. This is the case the finding is actually about."""
        member = await _make_user(db)
        proj = await _make_project(db)
        proj.owner_id = None
        await db.commit()
        await svc.add_member(db, proj.id, member.id, "editor")

        await svc.transfer_ownership(
            db,
            proj.id,
            new_owner_user_id=member.id,
            actor_user_id="some-admin-id",
            actor_is_admin=True,
        )

        assert await svc.get_role(db, proj.id, member.id) == "owner"
        fresh = await db.get(Project, proj.id)
        assert fresh.owner_id == member.id

    @pytest.mark.asyncio
    async def test_a_non_admin_cannot_claim_an_orphaned_project(self, db):
        member = await _make_user(db)
        proj = await _make_project(db)
        proj.owner_id = None
        await db.commit()
        await svc.add_member(db, proj.id, member.id, "editor")

        with pytest.raises(HTTPException) as exc:
            await svc.transfer_ownership(
                db, proj.id, new_owner_user_id=member.id, actor_user_id=member.id
            )
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_the_new_owner_s_project_quota_is_enforced(self, db, monkeypatch):
        """Project quotas count by `owner_id` (`entitlement_service.py:216`), so a
        transfer that skips the check is a plan-limit bypass wearing a feature's name.
        """
        from app.services.entitlement_service import QuotaExceededError

        old = await _make_user(db)
        new = await _make_user(db)
        proj = await _make_project(db)
        proj.owner_id = old.id
        await db.commit()
        await svc.add_member(db, proj.id, new.id, "editor")

        called: list[str] = []

        async def _full(_self, _db, user_id):  # patched on the class: `self` arrives too
            called.append(user_id)
            raise QuotaExceededError("full", resource="projects", limit=1, current=1)

        monkeypatch.setattr(
            "app.services.entitlement_service.EntitlementService.enforce_project_quota",
            _full,
        )

        with pytest.raises(QuotaExceededError):
            await svc.transfer_ownership(
                db, proj.id, new_owner_user_id=new.id, actor_user_id=old.id
            )

        assert called == [new.id], "the quota checked must be the RECEIVING owner's"
        fresh = await db.get(Project, proj.id)
        assert fresh.owner_id == old.id, "a refused transfer must change nothing"

    @pytest.mark.asyncio
    async def test_the_members_list_shows_the_new_owner_as_owner(self, db):
        """`get_role` cannot see this, and that is the point.

        It falls back to `Project.owner_id`, so moving only the column still resolves
        the new owner correctly — a plant that skipped the member-row update left
        every role assertion green. What breaks is what a person actually looks at:
        the members list would print the project's owner as a viewer.
        """
        old = await _make_user(db)
        new = await _make_user(db)
        proj = await _make_project(db)
        proj.owner_id = old.id
        await db.commit()
        await svc.add_member(db, proj.id, old.id, "owner")
        await svc.add_member(db, proj.id, new.id, "viewer")

        await svc.transfer_ownership(db, proj.id, new_owner_user_id=new.id, actor_user_id=old.id)

        by_user = {m.user_id: m.role for m in await svc.list_members(db, proj.id)}
        assert by_user[new.id] == "owner", "the members list must not call the owner a viewer"
        assert by_user[old.id] == "editor"
