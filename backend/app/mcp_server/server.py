"""FastMCP server definition — registers all tools and resources.

All tools are prefixed with ``checkmydata_`` so they don't collide with
other MCP servers a client may have loaded in parallel. Every tool
carries explicit ``ToolAnnotations`` (read-only / destructive /
open-world / idempotent) so MCP clients can render appropriate UI and
confirmation prompts.

Usage::

    # stdio transport (for Claude Desktop / Cursor)
    python -m app.mcp_server

    # streamable-http transport (preferred for remote / multi-client)
    python -m app.mcp_server --transport streamable-http --port 8100
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from app.mcp_server import auth, tools
from app.mcp_server import resources as res

logger = logging.getLogger(__name__)


async def _with_principal(
    run: Callable[[dict], Awaitable[str]],
    *,
    tool_name: str | None = None,
) -> str:
    """Resolve the caller's identity, then run a tool bound to that principal.

    Every tool goes through here so no tool can execute without an
    authenticated, authorized principal. Auth failures are returned as a JSON
    error rather than raised, matching the tools' error contract. Callers
    pass ``tool_name`` so log lines carry the real tool identity instead of
    ``<lambda>`` from the wrapping closure.
    """
    name = tool_name or getattr(run, "__name__", "anonymous-tool")
    try:
        principal = await auth.authenticate()
    except auth.MCPAuthError as exc:
        logger.warning("MCP tool %s rejected: auth failed (%s)", name, exc)
        return json.dumps({"error": str(exc)})
    logger.info("MCP tool %s starting (user=%s)", name, principal.get("user_id"))
    try:
        result = await run(principal)
    except Exception:
        logger.exception("MCP tool %s crashed", name)
        return json.dumps({"error": "Internal tool error"})
    logger.info("MCP tool %s ok (user=%s)", name, principal.get("user_id"))
    return result


# ---------------------------------------------------------------------------
# Tool annotations — these are HINTS, not security guarantees. Tenancy and
# read-only enforcement live in tools.py / connector layer. Annotations help
# MCP clients render confirmation prompts and decide auto-approval policies.
# ---------------------------------------------------------------------------

_READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)

# query_database & search_codebase invoke the orchestrator which only reads
# data — but downstream LLM behavior is non-deterministic, so not idempotent.
_READ_ONLY_NONIDEMPOTENT = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=True,
)

_PING = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)


def create_mcp_server() -> FastMCP:
    """Build and return the configured MCP server instance."""
    mcp = FastMCP(
        "checkmydata-mcp",
        instructions=(
            "CheckMyData.ai MCP server — query relational databases in natural "
            "language, search indexed codebases, and inspect database schemas. "
            "Every call is authorized against project membership; raw SQL is "
            "only accepted on connections explicitly marked read-only."
        ),
    )

    # ------------------------------------------------------------------
    # Tools (prefixed `checkmydata_*` to avoid collisions with other MCPs)
    # ------------------------------------------------------------------

    @mcp.tool(
        name="checkmydata_ping",
        title="Ping CheckMyData MCP",
        description=(
            "Health-check tool: verifies the server is up, auth works, and "
            "returns the resolved principal. Use this first when wiring a "
            "new client."
        ),
        annotations=_PING,
    )
    async def checkmydata_ping() -> str:
        return await _with_principal(tools.ping, tool_name="checkmydata_ping")

    @mcp.tool(
        name="checkmydata_query_database",
        title="Query database (natural language)",
        description=(
            "Ask a natural-language question about data in a project's "
            "database. The orchestrator picks the right tables, drafts SQL, "
            "validates it, and returns the answer plus the SQL, results "
            "(first 100 rows), and a visualization config when applicable.\n\n"
            "Args:\n"
            "  project_id: project the question is scoped to.\n"
            "  question: free-form natural-language question.\n"
            "  connection_id: optional — defaults to the project's first "
            "connection.\n\n"
            "Returns JSON with: answer, response_type, query, "
            "query_explanation, results{columns,rows,row_count,...}, "
            "viz_type, viz_config, sources[]."
        ),
        annotations=_READ_ONLY_NONIDEMPOTENT,
    )
    async def checkmydata_query_database(
        project_id: str,
        question: str,
        connection_id: str | None = None,
    ) -> str:
        return await _with_principal(
            lambda p: tools.query_database(p, project_id, question, connection_id),
            tool_name="checkmydata_query_database",
        )

    @mcp.tool(
        name="checkmydata_search_codebase",
        title="Search project codebase",
        description=(
            "Search the indexed project codebase / docs for information "
            "about code structure, ORM models, architecture, and "
            "documentation. Returns the orchestrator answer plus knowledge "
            "sources used."
        ),
        annotations=_READ_ONLY_NONIDEMPOTENT,
    )
    async def checkmydata_search_codebase(project_id: str, question: str) -> str:
        return await _with_principal(
            lambda p: tools.search_codebase(p, project_id, question),
            tool_name="checkmydata_search_codebase",
        )

    @mcp.tool(
        name="checkmydata_list_projects",
        title="List accessible projects",
        description=(
            "List projects the authenticated caller can access. Paginated.\n\n"
            "Args:\n"
            "  offset: zero-based start index (default 0).\n"
            "  limit: page size, 1–200 (default 20).\n"
            "  response_format: 'json' (default) or 'markdown'."
        ),
        annotations=_READ_ONLY,
    )
    async def checkmydata_list_projects(
        offset: int = 0,
        limit: int = 20,
        response_format: str = "json",
    ) -> str:
        return await _with_principal(
            lambda p: tools.list_projects(p, offset, limit, response_format),
            tool_name="checkmydata_list_projects",
        )

    @mcp.tool(
        name="checkmydata_list_connections",
        title="List project database connections",
        description=(
            "List database connections configured for a project. Paginated.\n\n"
            "Args:\n"
            "  project_id: project to list connections for.\n"
            "  offset: zero-based start index (default 0).\n"
            "  limit: page size, 1–200 (default 20).\n"
            "  response_format: 'json' (default) or 'markdown'."
        ),
        annotations=_READ_ONLY,
    )
    async def checkmydata_list_connections(
        project_id: str,
        offset: int = 0,
        limit: int = 20,
        response_format: str = "json",
    ) -> str:
        return await _with_principal(
            lambda p: tools.list_connections(p, project_id, offset, limit, response_format),
            tool_name="checkmydata_list_connections",
        )

    @mcp.tool(
        name="checkmydata_get_schema",
        title="Get indexed database schema",
        description=(
            "Get the indexed database schema (tables, columns, row counts, "
            "business descriptions) for a connection. Paginated by table.\n\n"
            "Args:\n"
            "  connection_id: connection whose schema to read.\n"
            "  offset: zero-based table index (default 0).\n"
            "  limit: tables per page, 1–200 (default 50).\n"
            "  response_format: 'json' (default) or 'markdown'."
        ),
        annotations=_READ_ONLY,
    )
    async def checkmydata_get_schema(
        connection_id: str,
        offset: int = 0,
        limit: int = 50,
        response_format: str = "json",
    ) -> str:
        return await _with_principal(
            lambda p: tools.get_schema(p, connection_id, offset, limit, response_format),
            tool_name="checkmydata_get_schema",
        )

    @mcp.tool(
        name="checkmydata_execute_raw_query",
        title="Execute raw SQL (read-only connections only)",
        description=(
            "Execute a raw SQL query against a connection. The connection "
            "MUST be marked is_read_only=True, and the query is passed "
            "through SafetyGuard(READ_ONLY) before execution. Returns "
            "columns, rows (first 100), row_count, execution_time_ms.\n\n"
            "Use this only when natural-language query_database is "
            "insufficient (e.g. exact reproducible SQL needed)."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
    )
    async def checkmydata_execute_raw_query(connection_id: str, query: str) -> str:
        return await _with_principal(
            lambda p: tools.execute_raw_query(p, connection_id, query),
            tool_name="checkmydata_execute_raw_query",
        )

    # ------------------------------------------------------------------
    # Resources — same auth + tenancy gate as tools (F-SEC-1)
    # ------------------------------------------------------------------

    @mcp.resource(
        "project://{project_id}/schema",
        name="project_schema",
        title="Project database schema",
        description="Aggregated database schema across every connection in a project.",
        mime_type="application/json",
    )
    async def project_schema(project_id: str) -> str:
        return await _with_principal(
            lambda p: res.get_project_schema(p, project_id),
            tool_name="resource:project_schema",
        )

    @mcp.resource(
        "project://{project_id}/rules",
        name="project_rules",
        title="Project custom rules",
        description="Custom rules (business logic, glossary, conventions) defined for a project.",
        mime_type="application/json",
    )
    async def project_rules(project_id: str) -> str:
        return await _with_principal(
            lambda p: res.get_project_rules(p, project_id),
            tool_name="resource:project_rules",
        )

    @mcp.resource(
        "project://{project_id}/knowledge",
        name="project_knowledge",
        title="Project knowledge base status",
        description="Status and document count of the project's indexed knowledge base.",
        mime_type="application/json",
    )
    async def project_knowledge(project_id: str) -> str:
        return await _with_principal(
            lambda p: res.get_project_knowledge(p, project_id),
            tool_name="resource:project_knowledge",
        )

    return mcp
