# backend/tests/unit/test_mcp_with_principal.py
from unittest.mock import AsyncMock, patch

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from app.mcp_server import runtime, server


async def test_with_principal_prefers_contextvar():
    token = runtime.current_principal.set({"user_id": "ctx-user", "email": ""})
    try:
        captured = {}

        async def run(p):
            captured["uid"] = p["user_id"]
            return "ok"

        # authenticate() must NOT be consulted when a ContextVar principal exists.
        with patch("app.mcp_server.auth.authenticate", new=AsyncMock(side_effect=AssertionError)):
            out = await server._with_principal(run, tool_name="t")
        assert out == "ok"
        assert captured["uid"] == "ctx-user"
    finally:
        runtime.current_principal.reset(token)


async def test_with_principal_falls_back_to_env_auth():
    token = runtime.current_principal.set(None)
    try:
        captured = {}

        async def run(p):
            captured["uid"] = p["user_id"]
            return "ran"

        with patch(
            "app.mcp_server.auth.authenticate",
            new=AsyncMock(return_value={"user_id": "env-user", "email": ""}),
        ):
            out = await server._with_principal(run, tool_name="t")
        assert out == "ran"
        assert captured["uid"] == "env-user"
    finally:
        runtime.current_principal.reset(token)


async def test_auth_failure_raises_tool_error():
    """When authenticate() fails, _with_principal must raise ToolError."""
    token = runtime.current_principal.set(None)
    try:
        from app.mcp_server.auth import MCPAuthError

        with patch(
            "app.mcp_server.auth.authenticate",
            new=AsyncMock(side_effect=MCPAuthError("no valid credential")),
        ):
            with pytest.raises(ToolError, match="no valid credential"):
                await server._with_principal(AsyncMock(return_value="x"), tool_name="t")
    finally:
        runtime.current_principal.reset(token)


async def test_limited_rejected_when_limiter_blocks():
    token = runtime.current_principal.set({"user_id": "u1", "email": ""})
    try:
        with patch(
            "app.core.agent_limiter.agent_limiter.acquire",
            new=AsyncMock(return_value="Too many concurrent requests"),
        ):
            with pytest.raises(ToolError, match="Too many concurrent"):
                await server._with_principal(
                    AsyncMock(return_value="x"), tool_name="t", limited=True
                )
    finally:
        runtime.current_principal.reset(token)


async def test_limited_success_acquires_and_releases_once():
    token = runtime.current_principal.set({"user_id": "u1", "email": ""})
    try:
        acquire = AsyncMock(return_value=None)
        release = AsyncMock()
        with (
            patch("app.core.agent_limiter.agent_limiter.acquire", new=acquire),
            patch("app.core.agent_limiter.agent_limiter.release", new=release),
        ):
            out = await server._with_principal(
                AsyncMock(return_value="ran"), tool_name="t", limited=True
            )
        assert out == "ran"
        acquire.assert_awaited_once_with("u1")
        release.assert_awaited_once_with("u1")
    finally:
        runtime.current_principal.reset(token)


async def test_limited_releases_on_tool_exception():
    token = runtime.current_principal.set({"user_id": "u1", "email": ""})
    try:
        release = AsyncMock()

        async def boom(_p):
            raise RuntimeError("kaboom")

        with (
            patch("app.core.agent_limiter.agent_limiter.acquire", new=AsyncMock(return_value=None)),
            patch("app.core.agent_limiter.agent_limiter.release", new=release),
        ):
            with pytest.raises(ToolError, match="Internal tool error"):
                await server._with_principal(boom, tool_name="t", limited=True)
        release.assert_awaited_once_with("u1")
    finally:
        runtime.current_principal.reset(token)
