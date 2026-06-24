"""Tests for the per-user MCP API key service and auth integration."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.mcp_key_service import (
    DISPLAY_PREFIX_LEN,
    TOKEN_PREFIX,
    McpKeyService,
    _hash_token,
)


def _row(**kwargs):
    """Build a MagicMock matching :class:`McpApiKey`'s attribute shape."""
    row = MagicMock()
    row.id = kwargs.get("id", "key-1")
    row.user_id = kwargs.get("user_id", "u1")
    row.name = kwargs.get("name", "test")
    row.token_hash = kwargs.get("token_hash", "h")
    row.token_prefix = kwargs.get("token_prefix", "cmd_mcp_ABCD")
    row.created_at = kwargs.get("created_at", datetime.now(UTC))
    row.last_used_at = kwargs.get("last_used_at")
    row.expires_at = kwargs.get("expires_at")
    row.revoked_at = kwargs.get("revoked_at")
    return row


def _scalar_one_or_none_session(record):
    """An AsyncSession-shaped mock whose ``execute`` returns one record."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = record
    session.execute = AsyncMock(return_value=result)
    return session


class TestTokenIssuance:
    @pytest.mark.asyncio
    async def test_issue_returns_plaintext_once_and_persists_hash(self):
        svc = McpKeyService()
        session = AsyncMock()
        session.add = MagicMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()

        issued = await svc.issue(session, user_id="u1", name="laptop")
        # Plaintext follows the documented prefix so clients can recognize it.
        assert issued.plaintext.startswith(TOKEN_PREFIX)
        # The persisted hash is SHA-256 of the plaintext — never the plaintext.
        assert issued.record.token_hash == _hash_token(issued.plaintext)
        assert issued.record.token_hash != issued.plaintext
        # Display prefix shows only the first N chars, never the full secret.
        assert issued.record.token_prefix == issued.plaintext[:DISPLAY_PREFIX_LEN]
        assert len(issued.record.token_prefix) == DISPLAY_PREFIX_LEN
        session.add.assert_called_once()
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_issue_requires_user_id(self):
        svc = McpKeyService()
        with pytest.raises(ValueError, match="user_id"):
            await svc.issue(AsyncMock(), user_id="", name="x")

    @pytest.mark.asyncio
    async def test_issue_requires_name(self):
        svc = McpKeyService()
        with pytest.raises(ValueError, match="name"):
            await svc.issue(AsyncMock(), user_id="u1", name="   ")

    @pytest.mark.asyncio
    async def test_issue_sets_expiry(self):
        svc = McpKeyService()
        session = AsyncMock()
        session.add = MagicMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        issued = await svc.issue(session, user_id="u1", name="laptop", expires_in_days=30)
        assert issued.record.expires_at is not None
        # ~30 days into the future, within a reasonable tolerance.
        delta = issued.record.expires_at - datetime.now(UTC)
        assert timedelta(days=29) < delta <= timedelta(days=30, hours=1)

    @pytest.mark.asyncio
    async def test_issue_rejects_negative_expiry(self):
        svc = McpKeyService()
        with pytest.raises(ValueError, match="positive"):
            await svc.issue(AsyncMock(), user_id="u1", name="x", expires_in_days=0)

    @pytest.mark.asyncio
    async def test_issue_applies_default_expiry_when_unspecified(self):
        # F-AUTH-12: an omitted expiry falls back to the configured default (90d)
        # rather than minting a never-expiring bearer credential.
        svc = McpKeyService()
        session = AsyncMock()
        session.add = MagicMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        issued = await svc.issue(session, user_id="u1", name="laptop")
        assert issued.record.expires_at is not None
        delta = issued.record.expires_at - datetime.now(UTC)
        assert timedelta(days=89) < delta <= timedelta(days=90, hours=1)


class TestLookupByToken:
    @pytest.mark.asyncio
    async def test_lookup_unknown_returns_none(self):
        svc = McpKeyService()
        session = _scalar_one_or_none_session(None)
        result = await svc.lookup_by_token(session, "cmd_mcp_unknown")
        assert result is None

    @pytest.mark.asyncio
    async def test_lookup_wrong_prefix_returns_none(self):
        svc = McpKeyService()
        # No DB hit should happen — return early on prefix mismatch.
        session = AsyncMock()
        result = await svc.lookup_by_token(session, "some-other-secret")
        assert result is None
        session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_lookup_revoked_returns_none(self):
        svc = McpKeyService()
        record = _row(revoked_at=datetime.now(UTC))
        session = _scalar_one_or_none_session(record)
        result = await svc.lookup_by_token(session, "cmd_mcp_anything")
        # Revoked tokens fail closed indistinguishably from unknown ones.
        assert result is None

    @pytest.mark.asyncio
    async def test_lookup_expired_returns_none(self):
        svc = McpKeyService()
        past = datetime.now(UTC) - timedelta(days=1)
        record = _row(expires_at=past)
        session = _scalar_one_or_none_session(record)
        result = await svc.lookup_by_token(session, "cmd_mcp_anything")
        assert result is None

    @pytest.mark.asyncio
    async def test_lookup_live_returns_record_and_touches_last_used(self):
        svc = McpKeyService()
        record = _row()
        session = _scalar_one_or_none_session(record)
        result = await svc.lookup_by_token(session, "cmd_mcp_anything")
        assert result is record
        # last_used_at must be populated so the user can see when a key was active.
        assert record.last_used_at is not None


class TestRevoke:
    @pytest.mark.asyncio
    async def test_revoke_owned_key_marks_revoked_at(self):
        svc = McpKeyService()
        record = _row()
        session = _scalar_one_or_none_session(record)
        ok = await svc.revoke(session, "key-1", "u1")
        assert ok is True
        assert record.revoked_at is not None

    @pytest.mark.asyncio
    async def test_revoke_unknown_returns_false(self):
        svc = McpKeyService()
        session = _scalar_one_or_none_session(None)
        ok = await svc.revoke(session, "missing", "u1")
        assert ok is False

    @pytest.mark.asyncio
    async def test_revoke_already_revoked_returns_false(self):
        svc = McpKeyService()
        record = _row(revoked_at=datetime.now(UTC) - timedelta(days=1))
        session = _scalar_one_or_none_session(record)
        ok = await svc.revoke(session, "key-1", "u1")
        # Idempotent: re-revoking is a no-op, not an error.
        assert ok is False


# ---------------------------------------------------------------------------
# MCP auth integration
# ---------------------------------------------------------------------------


class TestMcpAuthPersonalToken:
    @pytest.mark.asyncio
    async def test_personal_token_resolves_to_owning_user(self):
        from app.mcp_server import auth as auth_mod

        mock_user = MagicMock()
        mock_user.id = "owner-99"
        mock_user.email = "owner@test.local"
        mock_user.is_active = True

        record = _row(user_id="owner-99")

        with (
            patch("app.mcp_server.auth._mcp_key_svc") as mock_svc,
            patch("app.mcp_server.auth._auth_svc") as mock_auth_svc,
            patch("app.mcp_server.auth.async_session_factory") as mock_sf,
        ):
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_svc.lookup_by_token = AsyncMock(return_value=record)
            mock_auth_svc.get_by_id = AsyncMock(return_value=mock_user)

            resolved = await auth_mod.authenticate(api_key="cmd_mcp_validtoken")

        assert resolved == {"user_id": "owner-99", "email": "owner@test.local"}

    @pytest.mark.asyncio
    async def test_personal_token_unknown_raises_invalid(self):
        """An unknown `cmd_mcp_` token must NOT silently fall back to the
        server key — that would let any rejected user reach the operator's
        bound account."""
        from app.mcp_server import auth as auth_mod

        with (
            patch("app.mcp_server.auth._mcp_key_svc") as mock_svc,
            patch("app.mcp_server.auth.async_session_factory") as mock_sf,
        ):
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_svc.lookup_by_token = AsyncMock(return_value=None)
            with pytest.raises(auth_mod.MCPAuthError, match="invalid|revoked|expired"):
                await auth_mod.authenticate(api_key="cmd_mcp_garbage")

    @pytest.mark.asyncio
    async def test_personal_token_for_inactive_user_is_rejected(self):
        from app.mcp_server import auth as auth_mod

        mock_user = MagicMock()
        mock_user.is_active = False
        record = _row(user_id="owner-99")

        with (
            patch("app.mcp_server.auth._mcp_key_svc") as mock_svc,
            patch("app.mcp_server.auth._auth_svc") as mock_auth_svc,
            patch("app.mcp_server.auth.async_session_factory") as mock_sf,
        ):
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_svc.lookup_by_token = AsyncMock(return_value=record)
            mock_auth_svc.get_by_id = AsyncMock(return_value=mock_user)

            with pytest.raises(auth_mod.MCPAuthError):
                await auth_mod.authenticate(api_key="cmd_mcp_anytoken")
