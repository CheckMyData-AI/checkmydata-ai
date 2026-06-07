"""Authentication and project resolution for MCP server tool calls.

Supports two modes:
- API key: validated against env var ``CHECKMYDATA_API_KEY``
- JWT token: validated via the existing AuthService
"""

from __future__ import annotations

import hmac
import logging
import os

from app.config import settings
from app.services.auth_service import AuthService

logger = logging.getLogger(__name__)

_auth_svc = AuthService()


class MCPAuthError(Exception):
    """Raised when MCP authentication fails."""


def _get_api_key() -> str | None:
    return os.environ.get("CHECKMYDATA_API_KEY") or os.environ.get("MCP_API_KEY")


async def resolve_user_from_api_key(api_key: str) -> dict:
    """Validate an API key and return the bound platform user.

    The key is matched in constant time against the server secret, then mapped
    to a *real* user id (``MCP_API_KEY_USER_ID``). Returning a synthetic id is
    unsafe: it has no project ownership, so it would either bypass or
    universally fail tenancy checks. Requiring an explicit binding forces the
    operator to decide whose data the key may reach.
    """
    expected = _get_api_key()
    if not expected:
        raise MCPAuthError("No CHECKMYDATA_API_KEY configured on the server")
    if not hmac.compare_digest(api_key, expected):
        raise MCPAuthError("Invalid API key")
    user_id = settings.mcp_api_key_user_id
    if not user_id:
        raise MCPAuthError(
            "MCP_API_KEY_USER_ID is not configured; cannot bind the API key to a user"
        )
    return {"user_id": user_id, "email": ""}


async def resolve_user_from_jwt(token: str) -> dict:
    """Validate a JWT token and verify the user exists and is active."""
    from app.models.base import async_session_factory

    payload = _auth_svc.decode_token(token)
    if not payload:
        raise MCPAuthError("Invalid or expired JWT token")

    async with async_session_factory() as session:
        user = await _auth_svc.get_by_id(session, payload["sub"])
        if not user or not user.is_active:
            raise MCPAuthError("User not found or inactive")

    return {"user_id": payload["sub"], "email": payload.get("email", "")}


async def authenticate(
    api_key: str | None = None,
    token: str | None = None,
) -> dict:
    """Resolve user identity from whichever credential is provided.

    There is no anonymous fallback: with no per-call credential we fall back to
    the server-level API key from the environment (the stdio transport's trust
    model). If neither is present, authentication fails closed.
    """
    if api_key:
        return await resolve_user_from_api_key(api_key)
    if token:
        return await resolve_user_from_jwt(token)
    expected = _get_api_key()
    if expected:
        return await resolve_user_from_api_key(expected)
    raise MCPAuthError(
        "MCP authentication required: configure CHECKMYDATA_API_KEY or provide a token"
    )
