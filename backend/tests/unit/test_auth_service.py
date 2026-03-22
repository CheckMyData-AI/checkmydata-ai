"""Comprehensive unit tests for AuthService."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import bcrypt
import pytest
import pytest_asyncio
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.user import User
from app.services.auth_service import AuthService

svc = AuthService()

JWT_SECRET = "test-secret-key"
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = 60


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


def _settings_mock(**overrides):
    defaults = {
        "jwt_secret": JWT_SECRET,
        "jwt_algorithm": JWT_ALGORITHM,
        "jwt_expire_minutes": JWT_EXPIRE_MINUTES,
        "google_client_id": "",
    }
    defaults.update(overrides)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


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
# Password hashing
# ------------------------------------------------------------------ #


class TestHashPassword:
    def test_produces_bcrypt_hash(self):
        hashed = svc._hash_password("mysecret")
        assert hashed.startswith("$2b$") or hashed.startswith("$2a$")
        assert bcrypt.checkpw(b"mysecret", hashed.encode())

    def test_verify_correct_password(self):
        hashed = svc._hash_password("correct")
        assert svc._verify_password("correct", hashed) is True

    def test_verify_wrong_password(self):
        hashed = svc._hash_password("correct")
        assert svc._verify_password("wrong", hashed) is False


# ------------------------------------------------------------------ #
# JWT tokens
# ------------------------------------------------------------------ #


class TestCreateToken:
    @patch("app.services.auth_service.settings", _settings_mock())
    def test_produces_valid_jwt(self):
        token = svc.create_token("uid-123", "a@b.com")
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        assert payload["sub"] == "uid-123"
        assert payload["email"] == "a@b.com"
        assert "exp" in payload
        assert "iat" in payload


class TestDecodeToken:
    @patch("app.services.auth_service.settings", _settings_mock())
    def test_valid_token(self):
        token = svc.create_token("uid-1", "x@y.com")
        result = svc.decode_token(token)
        assert result is not None
        assert result["sub"] == "uid-1"
        assert result["email"] == "x@y.com"

    @patch("app.services.auth_service.settings", _settings_mock())
    def test_invalid_token_returns_none(self):
        assert svc.decode_token("not.a.valid.jwt") is None

    @patch("app.services.auth_service.settings", _settings_mock())
    def test_expired_token_returns_none(self):
        past = datetime.now(UTC) - timedelta(hours=2)
        payload = {
            "sub": "uid-x",
            "email": "e@e.com",
            "iat": past,
            "exp": past + timedelta(seconds=1),
        }
        expired_token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
        assert svc.decode_token(expired_token) is None

    @patch("app.services.auth_service.settings", _settings_mock(jwt_secret="other-secret"))
    def test_wrong_secret_returns_none(self):
        token = jwt.encode(
            {"sub": "u", "email": "e@e.com", "exp": datetime.now(UTC) + timedelta(hours=1)},
            "different-secret",
            algorithm=JWT_ALGORITHM,
        )
        assert svc.decode_token(token) is None


# ------------------------------------------------------------------ #
# register
# ------------------------------------------------------------------ #


class TestRegister:
    @pytest.mark.asyncio
    async def test_creates_user_normalized_email(self, db):
        user = await svc.register(db, "  Alice@Example.COM  ", "pass123")
        assert user.email == "alice@example.com"
        assert user.auth_provider == "email"
        assert user.password_hash is not None
        assert bcrypt.checkpw(b"pass123", user.password_hash.encode())

    @pytest.mark.asyncio
    async def test_raises_on_duplicate_email(self, db):
        await svc.register(db, "dup@test.com", "pass1")
        with pytest.raises(ValueError, match="Email already registered"):
            await svc.register(db, "dup@test.com", "pass2")

    @pytest.mark.asyncio
    async def test_uses_email_prefix_as_display_name(self, db):
        user = await svc.register(db, "hello.world@test.io", "pw")
        assert user.display_name == "hello.world"

    @pytest.mark.asyncio
    async def test_uses_provided_display_name(self, db):
        user = await svc.register(db, "x@t.com", "pw", display_name="Custom Name")
        assert user.display_name == "Custom Name"

    @pytest.mark.asyncio
    async def test_user_has_uuid_id(self, db):
        user = await svc.register(db, "uuid@test.com", "pw")
        uuid.UUID(user.id)  # raises if not valid UUID


# ------------------------------------------------------------------ #
# authenticate
# ------------------------------------------------------------------ #


class TestAuthenticate:
    @pytest.mark.asyncio
    async def test_correct_credentials(self, db):
        await svc.register(db, "auth@test.com", "secret")
        user = await svc.authenticate(db, "auth@test.com", "secret")
        assert user is not None
        assert user.email == "auth@test.com"

    @pytest.mark.asyncio
    async def test_wrong_password_returns_none(self, db):
        await svc.register(db, "wp@test.com", "right")
        assert await svc.authenticate(db, "wp@test.com", "wrong") is None

    @pytest.mark.asyncio
    async def test_nonexistent_email_returns_none(self, db):
        assert await svc.authenticate(db, "ghost@test.com", "any") is None

    @pytest.mark.asyncio
    async def test_google_user_no_password_returns_none(self, db):
        await _seed_user(
            db,
            email="guser@test.com",
            password_hash=None,
            auth_provider="google",
            google_id="g-123",
        )
        assert await svc.authenticate(db, "guser@test.com", "anything") is None

    @pytest.mark.asyncio
    async def test_normalizes_email_on_authenticate(self, db):
        await svc.register(db, "norm@test.com", "pw")
        user = await svc.authenticate(db, "  NORM@TEST.COM  ", "pw")
        assert user is not None
        assert user.email == "norm@test.com"


# ------------------------------------------------------------------ #
# get_by_id
# ------------------------------------------------------------------ #


class TestGetById:
    @pytest.mark.asyncio
    async def test_finds_existing_user(self, db):
        created = await svc.register(db, "find@test.com", "pw")
        found = await svc.get_by_id(db, created.id)
        assert found is not None
        assert found.id == created.id
        assert found.email == "find@test.com"

    @pytest.mark.asyncio
    async def test_returns_none_for_missing_id(self, db):
        assert await svc.get_by_id(db, "nonexistent-id") is None


# ------------------------------------------------------------------ #
# verify_google_token
# ------------------------------------------------------------------ #


class TestVerifyGoogleToken:
    @patch("app.services.auth_service.settings", _settings_mock(google_client_id=""))
    def test_raises_when_google_client_id_not_set(self):
        with pytest.raises(ValueError, match="Google OAuth is not configured"):
            svc.verify_google_token("some-credential")

    @patch("app.services.auth_service.settings", _settings_mock(google_client_id="my-client-id"))
    def test_calls_google_verify(self):
        fake_payload = {"sub": "g1", "email": "g@g.com", "email_verified": True}
        with patch("google.oauth2.id_token.verify_oauth2_token", return_value=fake_payload):
            result = svc.verify_google_token("cred")
        assert result["sub"] == "g1"
        assert result["email"] == "g@g.com"

    @patch("app.services.auth_service.settings", _settings_mock(google_client_id="my-client-id"))
    def test_raises_on_unverified_email(self):
        fake_payload = {"sub": "g1", "email": "g@g.com", "email_verified": False}
        with patch("google.oauth2.id_token.verify_oauth2_token", return_value=fake_payload):
            with pytest.raises(ValueError, match="email is not verified"):
                svc.verify_google_token("cred")


# ------------------------------------------------------------------ #
# find_or_create_google_user
# ------------------------------------------------------------------ #


class TestFindOrCreateGoogleUser:
    def _payload(self, **overrides):
        base = {
            "sub": f"google-{uuid.uuid4().hex[:8]}",
            "email": f"g-{uuid.uuid4().hex[:6]}@gmail.com",
            "name": "Google User",
            "picture": "https://img.example.com/photo.jpg",
        }
        base.update(overrides)
        return base

    @pytest.mark.asyncio
    async def test_creates_new_user(self, db):
        payload = self._payload(email="new@gmail.com", sub="google-new")
        user = await svc.find_or_create_google_user(db, payload)

        assert user.email == "new@gmail.com"
        assert user.google_id == "google-new"
        assert user.auth_provider == "google"
        assert user.display_name == "Google User"
        assert user.picture_url == "https://img.example.com/photo.jpg"
        assert user.password_hash is None

    @pytest.mark.asyncio
    async def test_links_existing_email_user(self, db):
        existing = await svc.register(db, "link@test.com", "pw123")
        assert existing.google_id is None

        payload = self._payload(email="link@test.com", sub="google-link")
        user = await svc.find_or_create_google_user(db, payload)

        assert user.id == existing.id
        assert user.google_id == "google-link"
        assert user.auth_provider == "google"

    @pytest.mark.asyncio
    async def test_finds_by_google_id(self, db):
        payload = self._payload(email="gid@test.com", sub="google-find")
        created = await svc.find_or_create_google_user(db, payload)

        payload2 = self._payload(email="gid@test.com", sub="google-find")
        found = await svc.find_or_create_google_user(db, payload2)

        assert found.id == created.id

    @pytest.mark.asyncio
    async def test_updates_picture_on_google_id_match(self, db):
        payload = self._payload(email="pic@test.com", sub="google-pic", picture="https://old.jpg")
        user = await svc.find_or_create_google_user(db, payload)
        assert user.picture_url == "https://old.jpg"

        payload2 = self._payload(email="pic@test.com", sub="google-pic", picture="https://new.jpg")
        updated = await svc.find_or_create_google_user(db, payload2)
        assert updated.id == user.id
        assert updated.picture_url == "https://new.jpg"

    @pytest.mark.asyncio
    async def test_uses_email_prefix_when_name_missing(self, db):
        payload = self._payload(email="noname@gmail.com", sub="google-noname")
        payload.pop("name", None)
        user = await svc.find_or_create_google_user(db, payload)
        assert user.display_name == "noname"
