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

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import BaseModel

from app.config import settings
from app.core.agent_limiter import agent_limiter
from app.mcp_server import auth, runtime, tools
from app.mcp_server import resources as res

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Structured output models — Pydantic annotations drive FastMCP's outputSchema
# generation and structuredContent population on the success path.
# Only tools whose success path is always JSON use these; tools with a
# response_format switch (list_projects, list_connections, get_schema) continue
# to return str so the markdown path is not broken.
# ---------------------------------------------------------------------------


class _PrincipalInfo(BaseModel):
    user_id: str


class PingOutput(BaseModel):
    ok: bool
    principal: _PrincipalInfo
    version: int


class _QueryResultOutput(BaseModel):
    columns: list[str]
    rows: list[Any]
    returned_rows: int
    row_count: int | None
    truncated: bool
    execution_time_ms: float | None
    error: str | None = None


class _KnowledgeSource(BaseModel):
    source_path: str
    doc_type: str


class AgentResponseOutput(BaseModel):
    answer: str
    response_type: str | None = None
    query: str | None = None
    query_explanation: str | None = None
    results: _QueryResultOutput | None = None
    viz_type: str | None = None
    viz_config: Any | None = None
    sources: list[_KnowledgeSource] | None = None
    error: str | None = None


class RawQueryOutput(BaseModel):
    columns: list[str]
    rows: list[Any]
    returned_rows: int
    row_count: int | None
    truncated: bool
    execution_time_ms: float | None
    error: str | None = None


async def _with_principal(
    run: Callable[..., Awaitable[Any]],
    *,
    tool_name: str | None = None,
    limited: bool = False,
) -> Any:
    """Resolve the caller's identity, then run a tool bound to that principal.

    Identity comes from the request-scoped ContextVar set by the HTTP auth
    middleware; absent that (stdio), we fall back to env-based ``authenticate``.
    When ``limited`` is set the call is gated by the per-user agent limiter
    (shared with chat) for concurrency + hourly caps.
    """
    name = tool_name or getattr(run, "__name__", "anonymous-tool")
    principal = runtime.current_principal.get()
    if principal is None:
        try:
            principal = await auth.authenticate()
        except auth.MCPAuthError as exc:
            logger.warning("MCP tool %s rejected: auth failed (%s)", name, exc)
            raise ToolError(str(exc))

    user_id = principal.get("user_id") or ""
    if limited:
        rejection = await agent_limiter.acquire(user_id)
        if rejection:
            logger.info("MCP tool %s rate-limited (user=%s)", name, user_id)
            raise ToolError(rejection)

    logger.info("MCP tool %s starting (user=%s)", name, user_id)
    try:
        result = await run(principal)
    except ToolError:
        raise
    except Exception:
        logger.exception("MCP tool %s crashed", name)
        raise ToolError("Internal tool error")
    finally:
        if limited:
            await agent_limiter.release(user_id)
    logger.info("MCP tool %s ok (user=%s)", name, user_id)
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
    # DNS-rebinding protection: enabled only when mcp_allowed_hosts is non-empty
    # so the default (empty list) is fully permissive and cannot lock out the
    # endpoint on existing deployments.
    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=bool(settings.mcp_allowed_hosts),
        allowed_hosts=settings.mcp_allowed_hosts,
        allowed_origins=settings.cors_origins,
    )
    mcp = FastMCP(
        "checkmydata-mcp",
        instructions=(
            "CheckMyData.ai MCP server — query relational databases in natural "
            "language, search indexed codebases, and inspect database schemas. "
            "Every call is authorized against project membership; raw SQL is "
            "only accepted on connections explicitly marked read-only."
        ),
        stateless_http=True,
        json_response=True,
        transport_security=transport_security,
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
        structured_output=True,
    )
    async def checkmydata_ping() -> PingOutput:
        raw: dict = await _with_principal(tools.ping, tool_name="checkmydata_ping")
        return PingOutput(**raw)

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
        structured_output=True,
    )
    async def checkmydata_query_database(
        project_id: str,
        question: str,
        connection_id: str | None = None,
    ) -> AgentResponseOutput:
        raw: dict = await _with_principal(
            lambda p: tools.query_database(p, project_id, question, connection_id),
            tool_name="checkmydata_query_database",
            limited=True,
        )
        return AgentResponseOutput(**raw)

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
        structured_output=True,
    )
    async def checkmydata_search_codebase(project_id: str, question: str) -> AgentResponseOutput:
        raw: dict = await _with_principal(
            lambda p: tools.search_codebase(p, project_id, question),
            tool_name="checkmydata_search_codebase",
            limited=True,
        )
        return AgentResponseOutput(**raw)

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
        structured_output=True,
    )
    async def checkmydata_execute_raw_query(connection_id: str, query: str) -> RawQueryOutput:
        raw: dict = await _with_principal(
            lambda p: tools.execute_raw_query(p, connection_id, query),
            tool_name="checkmydata_execute_raw_query",
            limited=True,
        )
        return RawQueryOutput(**raw)

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
