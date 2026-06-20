"""Authentication and project resolution for MCP server tool calls.

Three credential paths are supported, tried in priority order so the
strongest binding wins:

1. **Per-user MCP API key** — the user mints a ``cmd_mcp_…`` token through
   ``/api/auth/mcp-tokens`` and points their MCP client at it (typically by
   setting ``CHECKMYDATA_API_KEY`` in the client's MCP server config). The
   token is looked up by SHA-256 hash and resolved to the issuing user, so
   tenancy checks scope tools to *that* user's accessible projects.
2. **Per-call JWT token** — used by API clients that already have a JWT.
3. **Server-level API key** — legacy operator/service-account mode bound to
   the ``MCP_API_KEY_USER_ID`` env var. Kept for self-hosted single-tenant
   setups; ignored when path 1 succeeds.

There is no anonymous path — if every credential is missing, authentication
fails closed.
"""

from __future__ import annotations

import hmac
import logging
import os

from app.config import settings
from app.models.base import async_session_factory
from app.services.auth_service import AuthService
from app.services.mcp_key_service import TOKEN_PREFIX, McpKeyService

logger = logging.getLogger(__name__)

_auth_svc = AuthService()
_mcp_key_svc = McpKeyService()


class MCPAuthError(Exception):
    """Raised when MCP authentication fails."""


def _get_api_key() -> str | None:
    return os.environ.get("CHECKMYDATA_API_KEY") or os.environ.get("MCP_API_KEY")


def _redact_token(token: str | None) -> str:
    """Return a short, safe-to-log identifier for a token.

    Never logs more than the documented display prefix so log scraping can't
    reveal a secret.
    """
    if not token:
        return "<none>"
    # 12 chars covers ``cmd_mcp_xxxx`` — same as McpApiKey.token_prefix.
    return f"{token[:12]}…"


async def resolve_user_from_personal_token(token: str) -> dict | None:
    """Resolve a per-user ``cmd_mcp_…`` token to its owning user.

    Returns ``None`` (not raises) when the token doesn't have the per-user
    prefix or doesn't match a live record, so the caller can fall back to
    server-key / JWT paths.
    """
    if not token or not token.startswith(TOKEN_PREFIX):
        return None
    redacted = _redact_token(token)
    async with async_session_factory() as session:
        key = await _mcp_key_svc.lookup_by_token(session, token)
        if key is None:
            logger.warning(
                "MCP auth: personal token lookup failed (unknown/revoked/expired): %s",
                redacted,
            )
            return None
        user = await _auth_svc.get_by_id(session, key.user_id)
        if not user or not user.is_active:
            logger.warning(
                "MCP auth: token %s maps to missing/inactive user %s",
                redacted,
                key.user_id,
            )
            return None
        logger.info(
            "MCP auth: personal token %s resolved to user %s",
            redacted,
            user.id,
        )
        return {"user_id": user.id, "email": user.email}


async def resolve_user_from_server_key(api_key: str) -> dict:
    """Validate the legacy server-level API key and return the bound user.

    The key is matched in constant time against the server secret, then
    mapped to the operator-configured ``MCP_API_KEY_USER_ID``. This is the
    single-tenant / operator path; per-user tokens (see
    ``resolve_user_from_personal_token``) are preferred for multi-user
    deployments.
    """
    expected = _get_api_key()
    if not expected:
        logger.warning("MCP auth: server-key path attempted but CHECKMYDATA_API_KEY is unset")
        raise MCPAuthError("No CHECKMYDATA_API_KEY configured on the server")
    if not hmac.compare_digest(api_key, expected):
        logger.warning("MCP auth: server-key mismatch (%s)", _redact_token(api_key))
        raise MCPAuthError("Invalid API key")
    user_id = settings.mcp_api_key_user_id
    if not user_id:
        logger.error("MCP auth: server-key matched but MCP_API_KEY_USER_ID is unset")
        raise MCPAuthError(
            "MCP_API_KEY_USER_ID is not configured; cannot bind the API key to a user"
        )
    logger.info("MCP auth: server-key resolved to operator-bound user %s", user_id)
    return {"user_id": user_id, "email": ""}


# Backward-compatible alias — the tests and external imports use the older
# name. New code should call ``resolve_user_from_server_key``.
resolve_user_from_api_key = resolve_user_from_server_key


async def resolve_user_from_jwt(token: str) -> dict:
    """Validate a JWT token and verify the user exists and is active."""
    payload = _auth_svc.decode_token(token)
    if not payload:
        logger.warning("MCP auth: JWT decode failed")
        raise MCPAuthError("Invalid or expired JWT token")

    async with async_session_factory() as session:
        user = await _auth_svc.get_by_id(session, payload["sub"])
        if not user or not user.is_active:
            logger.warning("MCP auth: JWT subject %s not found or inactive", payload.get("sub"))
            raise MCPAuthError("User not found or inactive")

    logger.info("MCP auth: JWT resolved to user %s", payload["sub"])
    return {"user_id": payload["sub"], "email": payload.get("email", "")}


async def authenticate(
    api_key: str | None = None,
    token: str | None = None,
) -> dict:
    """Resolve user identity from whichever credential is provided.

    Resolution order:
      1. ``api_key`` (or env-var fallback) that starts with ``cmd_mcp_`` →
         per-user DB lookup.
      2. ``token`` (JWT) — explicit per-call credential.
      3. ``api_key`` (or env-var fallback) → legacy server-key path bound to
         ``MCP_API_KEY_USER_ID``.

    Fail-closed when no credential is provided.
    """
    candidate_key = api_key or _get_api_key()
    if candidate_key and candidate_key.startswith(TOKEN_PREFIX):
        resolved = await resolve_user_from_personal_token(candidate_key)
        if resolved is not None:
            return resolved
        # A `cmd_mcp_` token MUST NOT silently fall through to the server-key
        # path — if it doesn't resolve, it's invalid/revoked/expired.
        raise MCPAuthError("MCP token is invalid, revoked, or expired")

    if token:
        return await resolve_user_from_jwt(token)
    if candidate_key:
        return await resolve_user_from_server_key(candidate_key)
    logger.warning("MCP auth: no credentials presented")
    raise MCPAuthError(
        "MCP authentication required: configure CHECKMYDATA_API_KEY or provide a token"
    )
