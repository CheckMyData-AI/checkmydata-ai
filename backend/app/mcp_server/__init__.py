"""MCP Server — exposes the agent system's capabilities as MCP tools.

External clients (Claude Desktop, Cursor, custom scripts) can connect
via stdio or streamable HTTP and query databases, search knowledge,
inspect schema, and manage projects.

Public surface:
- :func:`create_mcp_server` — build a configured ``FastMCP`` instance.
"""

from app.mcp_server.server import create_mcp_server

__all__ = ["create_mcp_server"]
