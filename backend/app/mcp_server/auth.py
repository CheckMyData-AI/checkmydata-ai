"""Authentication and project resolution for MCP server tool calls.

Supports two modes:
- API key: validated against env var ``CHECKMYDATA_API_KEY``
- JWT token: validated via the existing AuthService
"""

from __future__ import annotations

import logging
import os

from app.services.auth_service import AuthService

logger = logging.getLogger(__name__)

_auth_svc = AuthService()


class MCPAuthError(Exception):
    """Raised when MCP authentication fails."""


def _get_api_key() -> str | None:
    return os.environ.get("CHECKMYDATA_API_KEY") or os.environ.get("MCP_API_KEY")


async def resolve_user_from_api_key(api_key: str) -> dict:
    """Validate an API key and return user info.

    Currently checks against an env-var secret.  Returns a synthetic
    user dict so that the tool handlers have a ``user_id``.
    """
    expected = _get_api_key()
    if not expected:
        raise MCPAuthError("No CHECKMYDATA_API_KEY configured on the server")
    if api_key != expected:
        raise MCPAuthError("Invalid API key")
    return {"user_id": "mcp-api-key-user", "email": "mcp@local"}


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
    """Resolve user identity from whichever credential is provided."""
    if api_key:
        return await resolve_user_from_api_key(api_key)
    if token:
        return await resolve_user_from_jwt(token)
    expected = _get_api_key()
    if not expected:
        return {"user_id": "mcp-anonymous", "email": ""}
    raise MCPAuthError("Authentication required: provide api_key or token")
