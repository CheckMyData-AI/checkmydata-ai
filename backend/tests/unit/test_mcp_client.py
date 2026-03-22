"""Tests for MCPClientAdapter."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.connectors.base import ConnectionConfig
from app.connectors.mcp_client import MCPClientAdapter


@pytest.fixture
def adapter():
    return MCPClientAdapter()


@pytest.fixture
def cfg():
    return ConnectionConfig(
        db_type="mcp",
        db_host="",
        db_port=0,
        db_name="",
        db_user="",
        db_password="",
        extra={
            "mcp_transport_type": "stdio",
            "mcp_server_command": "npx",
            "mcp_server_args": ["-y", "server"],
        },
    )


class TestSourceType:
    def test_source_type(self, adapter):
        assert adapter.source_type == "mcp"


class TestConnect:
    async def test_missing_command_raises(self, adapter):
        cfg_bad = ConnectionConfig(
            db_type="mcp",
            db_host="",
            db_port=0,
            db_name="",
            db_user="",
            db_password="",
            extra={
                "mcp_transport_type": "stdio",
                "mcp_server_command": "",
            },
        )
        with pytest.raises(ValueError, match="mcp_server_command"):
            await adapter.connect(cfg_bad)

    async def test_sse_missing_url_raises(self, adapter):
        cfg_sse = ConnectionConfig(
            db_type="mcp",
            db_host="",
            db_port=0,
            db_name="",
            db_user="",
            db_password="",
            extra={
                "mcp_transport_type": "sse",
                "mcp_server_url": "",
            },
        )
        with pytest.raises(ValueError, match="mcp_server_url"):
            await adapter.connect(cfg_sse)

    async def test_unknown_transport_raises(self, adapter):
        cfg_bad = ConnectionConfig(
            db_type="mcp",
            db_host="",
            db_port=0,
            db_name="",
            db_user="",
            db_password="",
            extra={"mcp_transport_type": "websocket"},
        )
        with pytest.raises(ValueError, match="Unsupported"):
            await adapter.connect(cfg_bad)


class TestDisconnect:
    async def test_disconnect_clears_state(self, adapter):
        adapter._exit_stack = AsyncMock()
        adapter._session = MagicMock()
        adapter._tools = [{"name": "x"}]

        await adapter.disconnect()
        assert adapter._session is None
        assert adapter._tools == []

    async def test_disconnect_noop_when_no_stack(self, adapter):
        await adapter.disconnect()
        assert adapter._session is None


class TestTestConnection:
    async def test_no_session_returns_false(self, adapter):
        assert await adapter.test_connection() is False

    async def test_success(self, adapter):
        adapter._session = AsyncMock()
        adapter._session.list_tools = AsyncMock()
        assert await adapter.test_connection() is True

    async def test_failure(self, adapter):
        adapter._session = AsyncMock()
        adapter._session.list_tools = AsyncMock(side_effect=RuntimeError("fail"))
        assert await adapter.test_connection() is False


class TestListEntities:
    async def test_returns_tool_names(self, adapter):
        adapter._tools = [
            {"name": "a", "description": ""},
            {"name": "b", "description": ""},
        ]
        names = await adapter.list_entities()
        assert names == ["a", "b"]


class TestQuery:
    async def test_no_session(self, adapter):
        result = await adapter.query("tool_name")
        assert result.error == "MCP session not connected"

    async def test_json_list_result(self, adapter):
        from mcp.types import TextContent

        adapter._session = AsyncMock()
        mock_result = MagicMock()
        mock_result.content = [
            TextContent(
                type="text",
                text='[{"id": 1, "name": "alice"}]',
            )
        ]
        adapter._session.call_tool = AsyncMock(return_value=mock_result)

        result = await adapter.query("get_users")
        assert result.columns == ["id", "name"]
        assert result.rows == [[1, "alice"]]
        assert result.row_count == 1

    async def test_json_dict_result(self, adapter):
        from mcp.types import TextContent

        adapter._session = AsyncMock()
        mock_result = MagicMock()
        mock_result.content = [TextContent(type="text", text='{"count": 42}')]
        adapter._session.call_tool = AsyncMock(return_value=mock_result)

        result = await adapter.query("count_items")
        assert result.columns == ["count"]
        assert result.rows == [[42]]

    async def test_plain_text_result(self, adapter):
        from mcp.types import TextContent

        adapter._session = AsyncMock()
        mock_result = MagicMock()
        mock_result.content = [TextContent(type="text", text="Hello world")]
        adapter._session.call_tool = AsyncMock(return_value=mock_result)

        result = await adapter.query("greet")
        assert result.columns == ["result"]
        assert result.rows == [["Hello world"]]

    async def test_tool_call_error(self, adapter):
        adapter._session = AsyncMock()
        adapter._session.call_tool = AsyncMock(side_effect=RuntimeError("network fail"))

        result = await adapter.query("failing_tool")
        assert "MCP tool call failed" in result.error


class TestCallTool:
    async def test_no_session(self, adapter):
        result = await adapter.call_tool("x")
        parsed = json.loads(result)
        assert "error" in parsed

    async def test_success(self, adapter):
        from mcp.types import TextContent

        adapter._session = AsyncMock()
        mock_result = MagicMock()
        mock_result.content = [TextContent(type="text", text="done")]
        adapter._session.call_tool = AsyncMock(return_value=mock_result)

        result = await adapter.call_tool("do_it", {"x": 1})
        assert result == "done"

    async def test_empty_result(self, adapter):
        adapter._session = AsyncMock()
        mock_result = MagicMock()
        mock_result.content = []
        adapter._session.call_tool = AsyncMock(return_value=mock_result)

        result = await adapter.call_tool("empty_tool")
        assert result == "(empty result)"

    async def test_error(self, adapter):
        adapter._session = AsyncMock()
        adapter._session.call_tool = AsyncMock(side_effect=RuntimeError("oops"))

        result = await adapter.call_tool("broken")
        parsed = json.loads(result)
        assert "oops" in parsed["error"]
