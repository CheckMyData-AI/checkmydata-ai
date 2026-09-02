"""Nobody could create a project, and no code path could ever grant the right.

``User.can_create_projects`` defaults to ``False`` (``models/user.py:26``);
``projects.py:152`` refuses creation without it with "Please request access"; and the
only thing calling itself a grant — ``POST /api/projects/access-requests`` — sends an
email and returns ``{"ok": True}``. It sets nothing. Every visitor who signed up hit a
waitlist about forty seconds in, drained by hand.

It stayed invisible because the integration ``conftest`` installs a SQLite trigger that
sets the flag on **every** insert (``tests/integration/conftest.py:75-79``), so no test
in the suite could reach the wall.

The right is now granted where the address is proven owned — the moment email
verification succeeds, and at creation for a Google login, which Google has already
verified. Granted on the **transition**, never on every login: the flag stays a
revocation switch, and a re-grant on each sign-in would quietly undo an admin's decision.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.user import User
from app.services.auth_service import AuthService


@pytest.fixture
def auth() -> AuthService:
    return AuthService()


@pytest_asyncio.fixture()
async def db_session():
    """A clean database, deliberately NOT the integration ``db_session``.

    That fixture installs a SQLite trigger setting ``can_create_projects = 1`` on every
    insert (``tests/integration/conftest.py:75-79``), which is why the missing grant path
    survived: no test in the suite could observe the column's real default. These tests
    are about that column, so they need a database that behaves like production's.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _register(auth: AuthService, db, email: str = "new@example.com") -> User:
    return await auth.register(db, email, "correct-horse-battery", "New User")


async def test_an_email_registration_starts_without_the_right(auth, db_session) -> None:
    user = await _register(auth, db_session)
    assert user.email_verified is False
    assert user.can_create_projects is False, "an unproven address must not get the right"


async def test_verifying_the_email_grants_it(auth, db_session) -> None:
    user = await _register(auth, db_session)
    token = await auth.issue_email_verification(db_session, user)
    verified = await auth.verify_email(db_session, token)
    assert verified is not None
    assert verified.email_verified is True
    assert verified.can_create_projects is True, (
        "verification is the moment the address is proven owned — and the only grant path"
    )


async def test_a_google_signup_gets_it_at_creation(auth, db_session) -> None:
    user, created = await auth.find_or_create_google_user(
        db_session,
        {"sub": "g-1", "email": "g@example.com", "name": "G", "email_verified": True},
    )
    assert created is True
    assert user.email_verified is True
    assert user.can_create_projects is True


async def test_linking_google_to_an_unverified_account_grants_it(auth, db_session) -> None:
    user = await _register(auth, db_session, "link@example.com")
    assert user.can_create_projects is False
    linked, created = await auth.find_or_create_google_user(
        db_session,
        {"sub": "g-2", "email": "link@example.com", "name": "L", "email_verified": True},
    )
    assert created is False
    assert linked.can_create_projects is True, "Google proved the address; that is the transition"


async def test_a_revoked_user_is_not_re_granted_by_signing_in_again(auth, db_session) -> None:
    """The flag is a revocation switch. A grant on every login would erase the decision."""
    user, _ = await auth.find_or_create_google_user(
        db_session,
        {"sub": "g-3", "email": "revoked@example.com", "name": "R", "email_verified": True},
    )
    user.can_create_projects = False
    await db_session.commit()

    again, created = await auth.find_or_create_google_user(
        db_session,
        {"sub": "g-3", "email": "revoked@example.com", "name": "R", "email_verified": True},
    )
    assert created is False
    assert again.can_create_projects is False, "a revoked user was re-granted by logging in"


async def test_verification_is_idempotent_and_does_not_undo_a_revocation(auth, db_session) -> None:
    user = await _register(auth, db_session, "idem@example.com")
    token = await auth.issue_email_verification(db_session, user)
    await auth.verify_email(db_session, token)

    verified = (
        await db_session.execute(select(User).where(User.email == "idem@example.com"))
    ).scalar_one()
    verified.can_create_projects = False
    await db_session.commit()

    # The token is cleared on success, so a replay finds nobody and changes nothing.
    assert await auth.verify_email(db_session, token) is None
    refreshed = (
        await db_session.execute(select(User).where(User.email == "idem@example.com"))
    ).scalar_one()
    assert refreshed.can_create_projects is False
