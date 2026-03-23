"""MCPClientAdapter — connects to external MCP servers as a data source.

This adapter uses the MCP Python SDK to connect to any MCP-compliant
server (e.g. Google Analytics, Stripe, Jira) via stdio or SSE transport,
discover its tools, and call them as data queries.
"""

from __future__ import annotations

import json
import logging
from contextlib import AsyncExitStack
from typing import Any

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import TextContent

from app.connectors.base import ConnectionConfig, DataSourceAdapter, QueryResult

logger = logging.getLogger(__name__)


class MCPClientAdapter(DataSourceAdapter):
    """DataSourceAdapter that connects to an external MCP server."""

    def __init__(self) -> None:
        self._session: ClientSession | None = None
        self._exit_stack: AsyncExitStack | None = None
        self._tools: list[dict[str, Any]] = []

    @property
    def source_type(self) -> str:
        return "mcp"

    async def connect(self, config: ConnectionConfig) -> None:
        """Start an MCP client session.

        Expects ``config.extra`` to contain:
        - ``mcp_transport_type``: ``"stdio"`` or ``"sse"``
        - ``mcp_server_command``: command for stdio (e.g. ``"npx"``)
        - ``mcp_server_args``: list of args for stdio
        - ``mcp_server_url``: URL for SSE transport
        - ``mcp_env``: optional dict of env vars to pass
        """
        transport_type = config.extra.get("mcp_transport_type", "stdio")
        self._exit_stack = AsyncExitStack()

        if transport_type == "stdio":
            command = config.extra.get("mcp_server_command", "")
            args = config.extra.get("mcp_server_args", [])
            env = config.extra.get("mcp_env")

            if not command:
                raise ValueError("mcp_server_command is required for stdio transport")

            params = StdioServerParameters(
                command=command,
                args=args if isinstance(args, list) else [],
                env=env if isinstance(env, dict) else None,
            )
            read, write = await self._exit_stack.enter_async_context(stdio_client(params))

        elif transport_type == "sse":
            url = config.extra.get("mcp_server_url", "")
            if not url:
                raise ValueError("mcp_server_url is required for SSE transport")
            read, write = await self._exit_stack.enter_async_context(sse_client(url))

        else:
            raise ValueError(f"Unsupported MCP transport type: {transport_type}")

        self._session = await self._exit_stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()

        tools_result = await self._session.list_tools()
        self._tools = [
            {
                "name": t.name,
                "description": t.description or "",
                "input_schema": t.inputSchema if hasattr(t, "inputSchema") else {},
            }
            for t in tools_result.tools
        ]
        logger.info(
            "MCP client connected (%s), discovered %d tools: %s",
            transport_type,
            len(self._tools),
            [t["name"] for t in self._tools],
        )

    async def disconnect(self) -> None:
        if self._exit_stack:
            try:
                await self._exit_stack.aclose()
            finally:
                self._exit_stack = None
                self._session = None
                self._tools = []

    async def test_connection(self) -> bool:
        if not self._session:
            return False
        try:
            await self._session.list_tools()
            return True
        except Exception:
            return False

    async def list_entities(self) -> list[str]:
        """Return the names of tools discovered from the MCP server."""
        return [t["name"] for t in self._tools]

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        """Return full tool metadata (name, description, input schema)."""
        return list(self._tools)

    async def query(self, query: str, params: dict[str, Any] | None = None) -> QueryResult:
        """Call an MCP tool by name.

        ``query`` is the tool name, ``params`` is the arguments dict.
        """
        if not self._session:
            return QueryResult(error="MCP session not connected")

        tool_name = query
        arguments = params or {}

        try:
            result = await self._session.call_tool(tool_name, arguments=arguments)

            texts: list[str] = []
            for block in result.content:
                if isinstance(block, TextContent):
                    texts.append(block.text)

            combined = "\n".join(texts)

            try:
                parsed = json.loads(combined)
                if isinstance(parsed, list) and parsed:
                    if isinstance(parsed[0], dict):
                        columns = list(parsed[0].keys())
                        rows = [list(item.get(c) for c in columns) for item in parsed]
                        return QueryResult(
                            columns=columns,
                            rows=rows,
                            row_count=len(rows),
                        )
                elif isinstance(parsed, dict):
                    columns = list(parsed.keys())
                    rows = [list(parsed.values())]
                    return QueryResult(columns=columns, rows=rows, row_count=1)
            except (json.JSONDecodeError, TypeError):
                pass

            return QueryResult(
                columns=["result"],
                rows=[[combined]],
                row_count=1,
            )

        except Exception as e:
            logger.exception("MCP tool call '%s' failed", tool_name)
            return QueryResult(error=f"MCP tool call failed: {e}")

    async def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> str:
        """Convenience method: call an MCP tool and return raw text result."""
        if not self._session:
            return json.dumps({"error": "MCP session not connected"})

        try:
            result = await self._session.call_tool(tool_name, arguments=arguments or {})
            texts = []
            for block in result.content:
                if isinstance(block, TextContent):
                    texts.append(block.text)
            return "\n".join(texts) if texts else "(empty result)"
        except Exception as e:
            logger.exception("MCP tool call '%s' failed", tool_name)
            return json.dumps({"error": str(e)})
