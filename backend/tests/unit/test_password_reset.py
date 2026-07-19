"""Unit tests for AuthService password-reset flow (SCN-013)."""

import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.user import User
from app.services.auth_service import AuthService, _hash_token

svc = AuthService()


@pytest_asyncio.fixture()
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture()
async def db(engine):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


async def _seed_user(db: AsyncSession, **kwargs) -> User:
    defaults = {
        "email": f"user-{uuid.uuid4().hex[:8]}@example.com",
        "password_hash": None,
        "display_name": "Test",
        "auth_provider": "email",
    }
    defaults.update(kwargs)
    user = User(**defaults)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


# ------------------------------------------------------------------ #
# issue_password_reset
# ------------------------------------------------------------------ #


class TestIssuePasswordReset:
    @pytest.mark.asyncio
    async def test_password_user_gets_token_and_stored_hash(self, db):
        user = await svc.register(db, "reset@test.com", "oldpass12")

        token = await svc.issue_password_reset(db, "reset@test.com")

        assert token, "a raw token should be returned for the email"
        await db.refresh(user)
        # The plaintext is never stored — only its SHA-256 hash.
        assert user.password_reset_token == _hash_token(token)
        assert user.password_reset_token != token
        assert user.password_reset_expires_at is not None

    @pytest.mark.asyncio
    async def test_normalizes_email(self, db):
        await svc.register(db, "norm@test.com", "oldpass12")
        token = await svc.issue_password_reset(db, "  NORM@TEST.COM  ")
        assert token is not None

    @pytest.mark.asyncio
    async def test_unknown_email_returns_none(self, db):
        assert await svc.issue_password_reset(db, "ghost@test.com") is None

    @pytest.mark.asyncio
    async def test_google_only_account_returns_none(self, db):
        # Passwordless (Google) account — no password to reset.
        await _seed_user(
            db,
            email="google@test.com",
            password_hash=None,
            auth_provider="google",
            google_id="g-1",
        )
        assert await svc.issue_password_reset(db, "google@test.com") is None


# ------------------------------------------------------------------ #
# reset_password
# ------------------------------------------------------------------ #


class TestResetPassword:
    @pytest.mark.asyncio
    async def test_valid_token_sets_new_password(self, db):
        user = await svc.register(db, "rp@test.com", "oldpass12")
        old_version = user.token_version
        token = await svc.issue_password_reset(db, "rp@test.com")

        assert await svc.reset_password(db, token, "brandnew123") is True

        await db.refresh(user)
        assert bcrypt.checkpw(b"brandnew123", user.password_hash.encode())
        assert not bcrypt.checkpw(b"oldpass12", user.password_hash.encode())
        # Token cleared (single-use) + all sessions revoked.
        assert user.password_reset_token is None
        assert user.password_reset_expires_at is None
        assert user.token_version == old_version + 1

    @pytest.mark.asyncio
    async def test_authenticate_works_with_new_password(self, db):
        await svc.register(db, "flow@test.com", "oldpass12")
        token = await svc.issue_password_reset(db, "flow@test.com")
        await svc.reset_password(db, token, "newsecret9")

        assert await svc.authenticate(db, "flow@test.com", "newsecret9") is not None
        assert await svc.authenticate(db, "flow@test.com", "oldpass12") is None

    @pytest.mark.asyncio
    async def test_token_is_single_use(self, db):
        await svc.register(db, "single@test.com", "oldpass12")
        token = await svc.issue_password_reset(db, "single@test.com")
        assert await svc.reset_password(db, token, "firstnew12") is True

        # Second use of the same token must fail.
        with pytest.raises(ValueError, match="Invalid or expired"):
            await svc.reset_password(db, token, "secondnew12")

    @pytest.mark.asyncio
    async def test_expired_token_fails(self, db):
        user = await svc.register(db, "exp@test.com", "oldpass12")
        token = await svc.issue_password_reset(db, "exp@test.com")
        # Force the expiry into the past.
        await db.refresh(user)
        user.password_reset_expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()

        with pytest.raises(ValueError, match="Invalid or expired"):
            await svc.reset_password(db, token, "brandnew123")

    @pytest.mark.asyncio
    async def test_wrong_token_fails(self, db):
        await svc.register(db, "wrong@test.com", "oldpass12")
        await svc.issue_password_reset(db, "wrong@test.com")
        with pytest.raises(ValueError, match="Invalid or expired"):
            await svc.reset_password(db, "totally-wrong-token", "brandnew123")

    @pytest.mark.asyncio
    async def test_empty_token_fails(self, db):
        with pytest.raises(ValueError, match="Invalid or expired"):
            await svc.reset_password(db, "", "brandnew123")
