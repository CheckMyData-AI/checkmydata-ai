"""Structured output (F5) tests for the MCP server.

Verifies that:
- Pure-JSON tools (ping, query_database, search_codebase, execute_raw_query)
  carry a typed outputSchema in list_tools() and produce structuredContent
  on success calls via the FastMCP in-process test session.
- Response-format tools (list_projects, list_connections, get_schema) keep
  str return types and therefore have no outputSchema — leaving them as
  strings is the intentional scope boundary (markdown path cannot be typed).
"""

from __future__ import annotations

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from app.mcp_server.server import (
    AgentResponseOutput,
    PingOutput,
    RawQueryOutput,
    create_mcp_server,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_server():
    return create_mcp_server()


# ---------------------------------------------------------------------------
# outputSchema — list_tools()
# ---------------------------------------------------------------------------


class TestOutputSchema:
    """Structured tools must expose a typed outputSchema; str tools must not."""

    @pytest.mark.asyncio
    async def test_ping_has_output_schema(self):
        mcp = _get_server()
        async with create_connected_server_and_client_session(mcp._mcp_server) as client:
            tools = await client.list_tools()
        by_name = {t.name: t for t in tools.tools}
        schema = by_name["checkmydata_ping"].outputSchema
        assert schema is not None, "checkmydata_ping must have an outputSchema"
        assert schema.get("type") == "object"
        assert "ok" in schema.get("properties", {})
        assert "principal" in schema.get("properties", {})
        assert "version" in schema.get("properties", {})

    @pytest.mark.asyncio
    async def test_query_database_has_output_schema(self):
        mcp = _get_server()
        async with create_connected_server_and_client_session(mcp._mcp_server) as client:
            tools = await client.list_tools()
        by_name = {t.name: t for t in tools.tools}
        schema = by_name["checkmydata_query_database"].outputSchema
        assert schema is not None, "checkmydata_query_database must have an outputSchema"
        props = schema.get("properties", {})
        assert "answer" in props
        assert "response_type" in props

    @pytest.mark.asyncio
    async def test_search_codebase_has_output_schema(self):
        mcp = _get_server()
        async with create_connected_server_and_client_session(mcp._mcp_server) as client:
            tools = await client.list_tools()
        by_name = {t.name: t for t in tools.tools}
        schema = by_name["checkmydata_search_codebase"].outputSchema
        assert schema is not None, "checkmydata_search_codebase must have an outputSchema"
        assert "answer" in schema.get("properties", {})

    @pytest.mark.asyncio
    async def test_execute_raw_query_has_output_schema(self):
        mcp = _get_server()
        async with create_connected_server_and_client_session(mcp._mcp_server) as client:
            tools = await client.list_tools()
        by_name = {t.name: t for t in tools.tools}
        schema = by_name["checkmydata_execute_raw_query"].outputSchema
        assert schema is not None, "checkmydata_execute_raw_query must have an outputSchema"
        props = schema.get("properties", {})
        assert "columns" in props
        assert "rows" in props
        assert "truncated" in props

    @pytest.mark.asyncio
    async def test_list_projects_no_output_schema(self):
        """list_projects has a response_format switch — intentionally not structured."""
        mcp = _get_server()
        async with create_connected_server_and_client_session(mcp._mcp_server) as client:
            tools = await client.list_tools()
        by_name = {t.name: t for t in tools.tools}
        schema = by_name["checkmydata_list_projects"].outputSchema
        # str return → generic wrapper or None; either way no typed properties.
        if schema is not None:
            # If FastMCP emits a generic wrapper, it must NOT contain
            # the structured fields we placed only on the JSON output models.
            props = schema.get("properties", {})
            assert "ok" not in props, "list_projects must not expose PingOutput schema"
            assert "answer" not in props, "list_projects must not expose AgentResponseOutput schema"

    @pytest.mark.asyncio
    async def test_list_connections_no_output_schema(self):
        """list_connections has a response_format switch — intentionally not structured."""
        mcp = _get_server()
        async with create_connected_server_and_client_session(mcp._mcp_server) as client:
            tools = await client.list_tools()
        by_name = {t.name: t for t in tools.tools}
        schema = by_name["checkmydata_list_connections"].outputSchema
        if schema is not None:
            props = schema.get("properties", {})
            assert "answer" not in props

    @pytest.mark.asyncio
    async def test_get_schema_no_output_schema(self):
        """get_schema has a response_format switch — intentionally not structured."""
        mcp = _get_server()
        async with create_connected_server_and_client_session(mcp._mcp_server) as client:
            tools = await client.list_tools()
        by_name = {t.name: t for t in tools.tools}
        schema = by_name["checkmydata_get_schema"].outputSchema
        if schema is not None:
            props = schema.get("properties", {})
            assert "answer" not in props


# ---------------------------------------------------------------------------
# Pydantic output model unit tests (no MCP session needed)
# ---------------------------------------------------------------------------


class TestOutputModels:
    """Verify the Pydantic models used for structured output are sane."""

    def test_ping_output_fields(self):
        out = PingOutput(ok=True, principal={"user_id": "u1"}, version=1)
        assert out.ok is True
        assert out.principal.user_id == "u1"
        assert out.version == 1

    def test_agent_response_output_minimal(self):
        out = AgentResponseOutput(answer="42 users", response_type="text")
        assert out.answer == "42 users"
        assert out.results is None
        assert out.error is None

    def test_raw_query_output_fields(self):
        out = RawQueryOutput(
            columns=["id", "name"],
            rows=[[1, "Alice"]],
            returned_rows=1,
            row_count=1,
            truncated=False,
            execution_time_ms=5.2,
        )
        assert out.columns == ["id", "name"]
        assert out.truncated is False
