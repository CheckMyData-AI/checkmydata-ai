"""F-PROJ-02 and F-PROJ-14: the owner is an owner, whichever reader you ask.

`_accessible_filter` already calls itself the "single source of truth for the access
rule" and encodes it as *owns OR is a member of*. `can_access` uses it. `get_role` and
`get_roles_bulk` do not — they read `ProjectMember` alone. So the same person can be
allowed by one reader and refused by another, which is what F-PROJ-14 means by "the
`GET /api/projects` member-only query diverges from `can_access`".

Why this matters in practice, since every mutation guard *does* hold: project creation
writes the project and the owner's member row in separate commits
(`projects.py:186-189`, and `add_member` commits on its own), so a failure between them
leaves `owner_id` pointing at someone with no membership. `require_role` then refuses
them access to a project they own, and F-PROJ-10 means there is no transfer path to
recover with. The lockout is permanent.

Fixed by making the readers agree with the rule the code already declares, rather than
by adding a fourth guard. Where a stale member row disagrees with `owner_id`, the owner
wins: the mutation guards make a non-owner role for the owner unreachable by design
(`remove_member` and `update_member_role` both refuse), so such a row is corruption, and
the safe resolution of corruption is that the person named on the project can still
reach it.
"""

from __future__ import annotations

import uuid

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.user import User
from app.services.membership_service import MembershipService


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as s:
        yield s
    await engine.dispose()


async def _user(session: AsyncSession) -> User:
    u = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4().hex[:8]}@example.com")
    session.add(u)
    await session.commit()
    return u


async def _project(session: AsyncSession, owner: User, *, with_member_row: bool) -> Project:
    p = Project(id=str(uuid.uuid4()), name="P", owner_id=owner.id)
    session.add(p)
    if with_member_row:
        session.add(ProjectMember(project_id=p.id, user_id=owner.id, role="owner"))
    await session.commit()
    return p


class TestOwnerWithoutAMemberRow:
    """The partial-creation state: `owner_id` set, membership missing."""

    async def test_get_role_returns_owner(self, session: AsyncSession):
        owner = await _user(session)
        p = await _project(session, owner, with_member_row=False)
        assert await MembershipService().get_role(session, p.id, owner.id) == "owner"

    async def test_require_role_admits_them(self, session: AsyncSession):
        owner = await _user(session)
        p = await _project(session, owner, with_member_row=False)
        # Would raise 403 before this change — a permanent lockout, since there is no
        # ownership-transfer path (F-PROJ-10) to recover with.
        assert await MembershipService().require_role(session, p.id, owner.id, "owner") == "owner"

    async def test_bulk_agrees_with_the_single_reader(self, session: AsyncSession):
        owner = await _user(session)
        p = await _project(session, owner, with_member_row=False)
        svc = MembershipService()
        bulk = await svc.get_roles_bulk(session, [p.id], owner.id)
        # Assert the VALUE, not just that the two readers agree: agreement alone is
        # satisfied by both being wrong, which is exactly the state before this change.
        assert bulk.get(p.id) == "owner"
        assert bulk.get(p.id) == await svc.get_role(session, p.id, owner.id)

    async def test_can_access_already_agreed(self, session: AsyncSession):
        """The reader that was right all along — this pins the rule it encodes."""
        owner = await _user(session)
        p = await _project(session, owner, with_member_row=False)
        assert await MembershipService().can_access(session, p.id, owner.id) is True


class TestNormalOwner:
    async def test_role_is_owner_with_a_member_row(self, session: AsyncSession):
        owner = await _user(session)
        p = await _project(session, owner, with_member_row=True)
        assert await MembershipService().get_role(session, p.id, owner.id) == "owner"


class TestDriftedMemberRow:
    async def test_a_stale_non_owner_row_does_not_demote_the_owner(self, session: AsyncSession):
        """Unreachable by design — both mutation guards refuse — so it is corruption."""
        owner = await _user(session)
        p = Project(id=str(uuid.uuid4()), name="P", owner_id=owner.id)
        session.add(p)
        session.add(ProjectMember(project_id=p.id, user_id=owner.id, role="viewer"))
        await session.commit()
        assert await MembershipService().get_role(session, p.id, owner.id) == "owner"


class TestNonOwners:
    async def test_a_stranger_gets_nothing(self, session: AsyncSession):
        owner = await _user(session)
        stranger = await _user(session)
        p = await _project(session, owner, with_member_row=True)
        svc = MembershipService()
        assert await svc.get_role(session, p.id, stranger.id) is None
        assert await svc.get_roles_bulk(session, [p.id], stranger.id) == {}

    async def test_a_member_keeps_their_own_role(self, session: AsyncSession):
        owner = await _user(session)
        editor = await _user(session)
        p = await _project(session, owner, with_member_row=True)
        session.add(ProjectMember(project_id=p.id, user_id=editor.id, role="editor"))
        await session.commit()
        assert await MembershipService().get_role(session, p.id, editor.id) == "editor"

    async def test_an_unknown_project_is_not_owned_by_anyone(self, session: AsyncSession):
        owner = await _user(session)
        assert await MembershipService().get_role(session, str(uuid.uuid4()), owner.id) is None
