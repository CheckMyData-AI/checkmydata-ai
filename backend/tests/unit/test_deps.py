"""Unit tests for API dependency helpers (get_db, get_current_user)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.deps import get_current_user, get_db

# ── get_current_user ───────────────────────────────────────────────────


def _fake_user(*, user_id="u1", email="a@b.com", is_active=True):
    return SimpleNamespace(id=user_id, email=email, is_active=is_active)


class TestGetCurrentUser:
    @pytest.mark.asyncio
    async def test_missing_header_raises_401(self):
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(authorization=None, db=AsyncMock())
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_non_bearer_header_raises_401(self):
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(authorization="Basic abc", db=AsyncMock())
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_token_raises_401(self):
        with patch("app.services.auth_service.AuthService") as mock_auth_cls:
            mock_auth_cls.return_value.decode_token.return_value = None
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(authorization="Bearer bad", db=AsyncMock())
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_expired_token_raises_401(self):
        with patch("app.services.auth_service.AuthService") as mock_auth_cls:
            mock_auth_cls.return_value.decode_token.return_value = None
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(authorization="Bearer expired", db=AsyncMock())
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_token_missing_sub_raises_401(self):
        with patch("app.services.auth_service.AuthService") as mock_auth_cls:
            mock_auth_cls.return_value.decode_token.return_value = {"email": "a@b.com"}
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(authorization="Bearer tok", db=AsyncMock())
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_user_not_found_raises_401(self):
        with patch("app.services.auth_service.AuthService") as mock_auth_cls:
            instance = mock_auth_cls.return_value
            instance.decode_token.return_value = {"sub": "u1"}
            instance.get_by_id = AsyncMock(return_value=None)
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(authorization="Bearer tok", db=AsyncMock())
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_inactive_user_raises_401(self):
        with patch("app.services.auth_service.AuthService") as mock_auth_cls:
            instance = mock_auth_cls.return_value
            instance.decode_token.return_value = {"sub": "u1"}
            instance.get_by_id = AsyncMock(return_value=_fake_user(is_active=False))
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(authorization="Bearer tok", db=AsyncMock())
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_valid_token_returns_dict(self):
        with patch("app.services.auth_service.AuthService") as mock_auth_cls:
            instance = mock_auth_cls.return_value
            instance.decode_token.return_value = {"sub": "u1"}
            instance.get_by_id = AsyncMock(return_value=_fake_user(user_id="u1", email="a@b.com"))
            result = await get_current_user(authorization="Bearer tok", db=AsyncMock())
            assert result == {"user_id": "u1", "email": "a@b.com"}


# ── get_db ─────────────────────────────────────────────────────────────


class TestGetDb:
    @pytest.mark.asyncio
    async def test_yields_session(self):
        mock_session = AsyncMock()
        mock_factory = MagicMock()
        ctx = AsyncMock()
        ctx.__aenter__.return_value = mock_session
        ctx.__aexit__.return_value = False
        mock_factory.return_value = ctx

        with patch("app.api.deps.async_session_factory", mock_factory):
            gen = get_db()
            session = await gen.__anext__()
            assert session is mock_session
            with pytest.raises(StopAsyncIteration):
                await gen.__anext__()
