"""F1 regression: per-request principal isolation over the HTTP mount.

Drives McpAuthMiddleware with two different tokens and asserts each request
sees its own principal — something the env-var-based auth tests cannot prove.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import httpx

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
