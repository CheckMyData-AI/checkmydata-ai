"""F1 regression: per-request principal isolation over the HTTP mount.

Drives McpAuthMiddleware with two different tokens and asserts each request
sees its own principal — something the env-var-based auth tests cannot prove.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.mcp_server import auth as auth_mod
from app.mcp_server import runtime
from app.mcp_server.asgi import McpAuthMiddleware


async def _echo_principal_app(scope, receive, send):
    principal = runtime.current_principal.get()
    body = (principal or {}).get("user_id", "none").encode()
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"text/plain")],
        }
    )
    await send({"type": "http.response.body", "body": body})


def _fake_authenticate(*, api_key=None, token=None):
    # Map token suffix -> user id, mimicking per-user cmd_mcp_ resolution.
    mapping = {"cmd_mcp_AAA": "user-a", "cmd_mcp_BBB": "user-b"}
    cred = api_key or token
    if cred in mapping:
        return {"user_id": mapping[cred], "email": ""}
    from app.mcp_server.auth import MCPAuthError

    raise MCPAuthError("MCP token is invalid, revoked, or expired")


async def test_two_tokens_resolve_to_two_principals():
    app = McpAuthMiddleware(_echo_principal_app)
    transport = httpx.ASGITransport(app=app)
    patch_target = "app.mcp_server.asgi.auth.authenticate"
    with patch(patch_target, new=AsyncMock(side_effect=_fake_authenticate)):
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            ra = await client.post("/mcp", headers={"Authorization": "Bearer cmd_mcp_AAA"})
            rb = await client.post("/mcp", headers={"Authorization": "Bearer cmd_mcp_BBB"})
    assert ra.text == "user-a"
    assert rb.text == "user-b"


async def test_invalid_token_is_401_and_leaves_no_principal():
    app = McpAuthMiddleware(_echo_principal_app)
    transport = httpx.ASGITransport(app=app)
    patch_target = "app.mcp_server.asgi.auth.authenticate"
    with patch(patch_target, new=AsyncMock(side_effect=_fake_authenticate)):
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.post("/mcp", headers={"Authorization": "Bearer cmd_mcp_NOPE"})
    assert r.status_code == 401
    # ContextVar must be clean after the request (no leakage across requests).
    assert runtime.current_principal.get() is None


class TestExplicitJwtPreferredOverEnvCandidate:
    """C6 / F-MCP-03: when both an explicit JWT and an env-derived
    ``cmd_mcp_…`` candidate exist, the explicit per-call JWT must win.

    The previous order tried the env candidate first, so a misconfigured
    operator ``CHECKMYDATA_API_KEY`` that happened to start with
    ``cmd_mcp_`` shadowed legitimate JWT calls.
    """

    @pytest.mark.asyncio
    async def test_explicit_jwt_preferred_over_env_personal_token(self, monkeypatch):
        # Env has a personal-token-shaped value — under the old order this
        # would be tried first and shadow the JWT.
        monkeypatch.setenv("CHECKMYDATA_API_KEY", "cmd_mcp_env_misconfig")

        jwt_mock = AsyncMock(return_value={"user_id": "jwt-user", "email": "j@x"})
        personal_mock = AsyncMock(return_value={"user_id": "env-user", "email": "e@x"})

        with (
            patch.object(auth_mod, "resolve_user_from_jwt", new=jwt_mock),
            patch.object(auth_mod, "resolve_user_from_personal_token", new=personal_mock),
        ):
            principal = await auth_mod.authenticate(api_key=None, token="some.valid.jwt")

        assert principal["user_id"] == "jwt-user"
        jwt_mock.assert_awaited_once_with("some.valid.jwt")
        personal_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_explicit_jwt_failure_does_not_fall_through_to_env(self, monkeypatch):
        # If JWT decode fails, we MUST raise — never silently demote to the
        # env candidate; the caller explicitly handed us a JWT.
        monkeypatch.setenv("CHECKMYDATA_API_KEY", "cmd_mcp_env_misconfig")

        jwt_mock = AsyncMock(side_effect=auth_mod.MCPAuthError("Invalid or expired JWT token"))
        personal_mock = AsyncMock(return_value={"user_id": "env-user", "email": "e@x"})
        server_mock = AsyncMock(return_value={"user_id": "server-user", "email": ""})

        with (
            patch.object(auth_mod, "resolve_user_from_jwt", new=jwt_mock),
            patch.object(auth_mod, "resolve_user_from_personal_token", new=personal_mock),
            patch.object(auth_mod, "resolve_user_from_server_key", new=server_mock),
        ):
            with pytest.raises(auth_mod.MCPAuthError, match="Invalid or expired JWT"):
                await auth_mod.authenticate(api_key=None, token="bad.jwt.token")

        jwt_mock.assert_awaited_once_with("bad.jwt.token")
        personal_mock.assert_not_awaited()
        server_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_explicit_api_key_still_takes_precedence(self, monkeypatch):
        # Explicit caller-supplied ``api_key`` (NOT env-derived) is the most
        # authoritative credential and must beat an explicit JWT too.
        monkeypatch.delenv("CHECKMYDATA_API_KEY", raising=False)
        monkeypatch.delenv("MCP_API_KEY", raising=False)

        jwt_mock = AsyncMock(return_value={"user_id": "jwt-user", "email": ""})
        personal_mock = AsyncMock(return_value={"user_id": "explicit-user", "email": ""})

        with (
            patch.object(auth_mod, "resolve_user_from_jwt", new=jwt_mock),
            patch.object(auth_mod, "resolve_user_from_personal_token", new=personal_mock),
        ):
            principal = await auth_mod.authenticate(api_key="cmd_mcp_explicit", token="ignored.jwt")

        assert principal["user_id"] == "explicit-user"
        personal_mock.assert_awaited_once_with("cmd_mcp_explicit")
        jwt_mock.assert_not_awaited()


async def test_concurrent_requests_keep_isolated_principals():
    """Prove that concurrent requests do not cross-contaminate principals.

    Guards against a class of bug where the principal ContextVar is set on the
    wrong asyncio Task — the exact failure mode pure-ASGI middleware was chosen
    to avoid. This test runs two requests concurrently with different tokens
    and asserts each sees its own principal without interference.
    """
    app = McpAuthMiddleware(_echo_principal_app)
    transport = httpx.ASGITransport(app=app)
    patch_target = "app.mcp_server.asgi.auth.authenticate"
    with patch(patch_target, new=AsyncMock(side_effect=_fake_authenticate)):
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            ra, rb = await asyncio.gather(
                client.post("/mcp", headers={"Authorization": "Bearer cmd_mcp_AAA"}),
                client.post("/mcp", headers={"Authorization": "Bearer cmd_mcp_BBB"}),
            )
    assert ra.text == "user-a"
    assert rb.text == "user-b"
    # ContextVar must be clean after both requests complete.
    assert runtime.current_principal.get() is None
