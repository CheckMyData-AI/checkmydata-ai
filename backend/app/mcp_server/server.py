"""FastMCP server definition — registers all tools and resources.

Usage::

    # stdio transport (for Claude Desktop / Cursor)
    python -m app.mcp_server

    # SSE transport (for HTTP clients)
    python -m app.mcp_server --transport sse --port 8100
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable

from mcp.server.fastmcp import FastMCP

from app.mcp_server import auth, tools
from app.mcp_server import resources as res

logger = logging.getLogger(__name__)


async def _with_principal(run: Callable[[dict], Awaitable[str]]) -> str:
    """Resolve the caller's identity, then run a tool bound to that principal.

    Every tool goes through here so no tool can execute without an
    authenticated, authorized principal. Auth failures are returned as a JSON
    error rather than raised, matching the tools' error contract.
    """
    try:
        principal = await auth.authenticate()
    except auth.MCPAuthError as exc:
        return json.dumps({"error": str(exc)})
    return await run(principal)


def create_mcp_server() -> FastMCP:
    """Build and return the configured MCP server instance."""
    mcp = FastMCP(
        "CheckMyData.ai",
        instructions=(
            "AI-powered database agent that can query databases, "
            "search codebases, and provide data analytics."
        ),
    )

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    @mcp.tool()
    async def query_database(
        project_id: str,
        question: str,
        connection_id: str | None = None,
    ) -> str:
        """Ask a natural-language question about data in a project's database.

        Returns the answer, SQL query, results, and visualization config.
        """
        return await _with_principal(
            lambda p: tools.query_database(p, project_id, question, connection_id)
        )

    @mcp.tool()
    async def search_codebase(project_id: str, question: str) -> str:
        """Search the indexed project codebase for information about
        code structure, ORM models, architecture, and documentation."""
        return await _with_principal(lambda p: tools.search_codebase(p, project_id, question))

    @mcp.tool()
    async def list_projects() -> str:
        """List the projects the authenticated caller can access."""
        return await _with_principal(tools.list_projects)

    @mcp.tool()
    async def list_connections(project_id: str) -> str:
        """List database connections configured for a project."""
        return await _with_principal(lambda p: tools.list_connections(p, project_id))

    @mcp.tool()
    async def get_schema(connection_id: str) -> str:
        """Get the indexed database schema (tables, columns) for a connection."""
        return await _with_principal(lambda p: tools.get_schema(p, connection_id))

    @mcp.tool()
    async def execute_raw_query(connection_id: str, query: str) -> str:
        """Execute a raw SQL query against a read-only connection.

        Only works on connections with is_read_only=True.
        """
        return await _with_principal(lambda p: tools.execute_raw_query(p, connection_id, query))

    # ------------------------------------------------------------------
    # Resources — same auth + tenancy gate as tools (F-SEC-1)
    # ------------------------------------------------------------------

    @mcp.resource("project://{project_id}/schema")
    async def project_schema(project_id: str) -> str:
        """Aggregated database schema for all connections in a project."""
        return await _with_principal(lambda p: res.get_project_schema(p, project_id))

    @mcp.resource("project://{project_id}/rules")
    async def project_rules(project_id: str) -> str:
        """Custom rules defined for a project."""
        return await _with_principal(lambda p: res.get_project_rules(p, project_id))

    @mcp.resource("project://{project_id}/knowledge")
    async def project_knowledge(project_id: str) -> str:
        """Knowledge base summary for a project."""
        return await _with_principal(lambda p: res.get_project_knowledge(p, project_id))

    return mcp
