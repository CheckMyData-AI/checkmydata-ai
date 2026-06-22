"""ASGI mount + per-request auth for the MCP server (remote multi-tenant).

The FastMCP streamable-http app is a Starlette app; we wrap it with a pure
ASGI middleware (NOT BaseHTTPMiddleware — that runs the inner app in a
separate anyio task and would drop the ContextVar) that resolves the bearer
token to a principal and stores it in ``runtime.current_principal`` for the
duration of the request.
"""

from __future__ import annotations

import json
import logging

from starlette.applications import Starlette
from starlette.datastructures import Headers

from app.mcp_server import auth, runtime
from app.mcp_server.server import create_mcp_server
from app.services.mcp_key_service import TOKEN_PREFIX

logger = logging.getLogger(__name__)

_mcp_instance = None


def get_mcp_instance():
    """Return the process-wide FastMCP instance (same one used for the mount
    and the lifespan session manager)."""
    global _mcp_instance  # noqa: PLW0603
    if _mcp_instance is None:
        _mcp_instance = create_mcp_server()
    return _mcp_instance


async def _resolve_principal(token: str | None) -> dict:
    """Resolve a bearer token to a principal, raising MCPAuthError on failure."""
    if not token:
        raise auth.MCPAuthError("MCP authentication required: missing bearer token")
    if token.startswith(TOKEN_PREFIX):
        return await auth.authenticate(api_key=token)
    return await auth.authenticate(token=token)


def _extract_token(headers: Headers) -> str | None:
    authz = headers.get("authorization")
    if authz and authz.lower().startswith("bearer "):
        return authz[7:].strip()
    return headers.get("x-api-key")


class McpAuthMiddleware:
    """Pure ASGI middleware: bearer token -> current_principal, or 401."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        try:
            principal = await _resolve_principal(_extract_token(headers))
        except auth.MCPAuthError as exc:
            await self._unauthorized(send, str(exc))
            return
        token = runtime.current_principal.set(principal)
        try:
            await self.app(scope, receive, send)
        finally:
            runtime.current_principal.reset(token)

    @staticmethod
    async def _unauthorized(send, message: str) -> None:
        body = json.dumps({"error": message}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", b"Bearer"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def build_mounted_mcp_app() -> Starlette:
    """Return the streamable-http Starlette app wrapped with auth middleware."""
    mcp = get_mcp_instance()
    app = mcp.streamable_http_app()
    app.add_middleware(McpAuthMiddleware)
    return app
