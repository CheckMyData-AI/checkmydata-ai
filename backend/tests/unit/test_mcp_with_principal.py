# backend/tests/unit/test_mcp_with_principal.py
import json
from unittest.mock import AsyncMock, patch

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
    runtime.current_principal.set(None)
    with patch(
        "app.mcp_server.auth.authenticate",
        new=AsyncMock(return_value={"user_id": "env-user", "email": ""}),
    ):
        out = await server._with_principal(AsyncMock(return_value="ran"), tool_name="t")
    assert out == "ran"


async def test_limited_rejected_when_limiter_blocks():
    runtime.current_principal.set({"user_id": "u1", "email": ""})
    with patch(
        "app.core.agent_limiter.agent_limiter.acquire",
        new=AsyncMock(return_value="Too many concurrent requests"),
    ):
        out = await server._with_principal(AsyncMock(return_value="x"), tool_name="t", limited=True)
    assert json.loads(out)["error"].startswith("Too many concurrent")
