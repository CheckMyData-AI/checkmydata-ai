"""F-PROJ-04: a pending invite must not be accepted forever.

`ProjectInvite` has no expiry column — id, project_id, email, invited_by, role,
status, created_at, accepted_at — so an invite stays `pending` indefinitely and
`auto_accept_for_user` accepts it whenever that address eventually registers. Invite
alice@oldcorp.example, she never signs up, and two years later whoever registers that
address is added to the project with the role she was offered.

F-PROJ-01's closure does not cover this: auto-accept now requires a verified email, and
a re-registered address or domain verifies perfectly well. Verification proves control
of the mailbox today, not that the invitation was meant for whoever controls it now.

Rows created before the column existed matter as much as new ones — they are exactly
the stale invites this is about. A NULL `expires_at` is therefore read as
``created_at + invite_expiry_days`` rather than as "never": the policy applies to real
creation time, no backfill is needed, and old invites correctly fall out while recent
ones keep working.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.models.base import Base
from app.models.project import Project
from app.models.project_invite import ProjectInvite
from app.models.user import User
from app.services.invite_service import InviteService, invite_expires_at, invite_is_expired


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as s:
        yield s
    await engine.dispose()


async def _seed(session: AsyncSession, *, created_days_ago: int = 0, expires_at=None):
    owner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4().hex[:8]}@example.com")
    session.add(owner)
    p = Project(id=str(uuid.uuid4()), name="P", owner_id=owner.id)
    session.add(p)
    inv = ProjectInvite(
        id=str(uuid.uuid4()),
        project_id=p.id,
        email="invitee@example.com",
        invited_by=owner.id,
        role="editor",
        status="pending",
        created_at=datetime.now(UTC) - timedelta(days=created_days_ago),
        expires_at=expires_at,
    )
    session.add(inv)
    await session.commit()
    return p, inv


class TestExpiryComputation:
    async def test_an_explicit_expiry_is_used(self, session: AsyncSession):
        when = datetime.now(UTC) + timedelta(days=3)
        _p, inv = await _seed(session, expires_at=when)
        assert invite_expires_at(inv) == when

    async def test_a_null_expiry_falls_back_to_creation_plus_the_window(self, session):
        """The rows that predate the column are the stale ones this is about."""
        _p, inv = await _seed(session, created_days_ago=0, expires_at=None)
        expected = invite_expires_at(inv)
        delta = expected - datetime.now(UTC)
        assert (
            timedelta(days=settings.invite_expiry_days - 1)
            < delta
            <= timedelta(days=settings.invite_expiry_days)
        )

    async def test_an_old_row_with_no_expiry_reads_as_expired(self, session: AsyncSession):
        _p, inv = await _seed(session, created_days_ago=settings.invite_expiry_days + 5)
        assert invite_is_expired(inv) is True

    async def test_a_recent_row_with_no_expiry_is_still_live(self, session: AsyncSession):
        _p, inv = await _seed(session, created_days_ago=1)
        assert invite_is_expired(inv) is False


class TestAcceptance:
    async def test_accepting_an_expired_invite_is_refused(self, session: AsyncSession):
        from fastapi import HTTPException

        _p, inv = await _seed(session, created_days_ago=settings.invite_expiry_days + 5)
        user = User(id=str(uuid.uuid4()), email="invitee@example.com")
        session.add(user)
        await session.commit()

        with pytest.raises(HTTPException) as exc:
            await InviteService().accept_invite(session, inv.id, user.id)
        assert exc.value.status_code in (400, 410)
        assert "expire" in str(exc.value.detail).lower()

    async def test_a_live_invite_is_still_accepted(self, session: AsyncSession):
        _p, inv = await _seed(session, created_days_ago=1)
        user = User(id=str(uuid.uuid4()), email="invitee@example.com")
        session.add(user)
        await session.commit()
        member, _ = await InviteService().accept_invite(session, inv.id, user.id)
        assert member.role == "editor"


class TestAutoAccept:
    async def test_auto_accept_skips_an_expired_invite(self, session: AsyncSession):
        """The path that makes this dangerous: nobody clicks anything."""
        _p, inv = await _seed(session, created_days_ago=settings.invite_expiry_days + 40)
        user = User(id=str(uuid.uuid4()), email="invitee@example.com")
        session.add(user)
        await session.commit()

        members = await InviteService().auto_accept_for_user(
            session, user.id, "invitee@example.com"
        )
        assert members == [], "a years-old invite auto-accepted on registration"

    async def test_auto_accept_still_takes_a_live_invite(self, session: AsyncSession):
        _p, inv = await _seed(session, created_days_ago=2)
        user = User(id=str(uuid.uuid4()), email="invitee@example.com")
        session.add(user)
        await session.commit()
        members = await InviteService().auto_accept_for_user(
            session, user.id, "invitee@example.com"
        )
        assert len(members) == 1
