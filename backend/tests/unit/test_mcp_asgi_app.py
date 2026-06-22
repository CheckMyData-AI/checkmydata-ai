from unittest.mock import AsyncMock, patch

import httpx

from app.mcp_server.asgi import McpAuthMiddleware, get_mcp_instance


def test_get_mcp_instance_is_singleton():
    assert get_mcp_instance() is get_mcp_instance()


async def _ok_app(scope, receive, send):
    # Minimal ASGI echo of the resolved principal user_id.
    from app.mcp_server import runtime

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


async def test_missing_bearer_is_401():
    app = McpAuthMiddleware(_ok_app)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        r = await client.post("/mcp")
    assert r.status_code == 401
    assert r.headers.get("www-authenticate") == "Bearer"


async def test_valid_bearer_sets_principal():
    app = McpAuthMiddleware(_ok_app)
    transport = httpx.ASGITransport(app=app)
    with patch(
        "app.mcp_server.asgi._resolve_principal",
        new=AsyncMock(return_value={"user_id": "tok-user", "email": ""}),
    ):
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.post("/mcp", headers={"Authorization": "Bearer cmd_mcp_abc"})
    assert r.status_code == 200
    assert r.text == "tok-user"
