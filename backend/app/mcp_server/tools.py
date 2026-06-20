"""MCP tool handlers that delegate to the OrchestratorAgent and services.

Each function here is registered as an MCP tool and bridges the external
MCP protocol into the existing agent infrastructure.

Response contract
-----------------
All tools return a JSON-encoded string. Errors are JSON objects with an
``error`` field; this is by design so a tool failure surfaces inside the
tool result rather than as a protocol error. List tools support
pagination (``offset`` / ``limit``) and a ``response_format`` switch
between ``"json"`` (default) and ``"markdown"`` for human-readable output.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.base import AgentContext
from app.agents.orchestrator import AgentResponse, OrchestratorAgent
from app.connectors.base import QueryResult
from app.core.workflow_tracker import tracker as _singleton_tracker
from app.llm.router import LLMRouter
from app.models.base import async_session_factory
from app.services.connection_service import ConnectionService
from app.services.db_index_service import DbIndexService
from app.services.membership_service import MembershipService
from app.services.project_service import ProjectService

logger = logging.getLogger(__name__)

_project_svc = ProjectService()
_connection_svc = ConnectionService()
_db_index_svc = DbIndexService()
_membership_svc = MembershipService()


# Pagination defaults align with MCP best-practices (20–50 items typical).
DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 200


def _principal_user_id(principal: dict) -> str:
    """Extract the authenticated user id from a resolved MCP principal.

    Defends against a tool being called without a real identity: an empty /
    missing ``user_id`` can never own a project, so access checks below will
    deny it rather than silently acting as a privileged user.
    """
    return (principal or {}).get("user_id") or ""


class _AccessDeniedError(Exception):
    """Raised internally when a principal may not touch a project/connection."""


async def _require_project_access(session, project_id: str, user_id: str) -> None:
    if not user_id or not await _membership_svc.can_access(session, project_id, user_id):
        raise _AccessDeniedError(f"Access denied to project '{project_id}'")


async def _require_connection_access(session, connection_id: str, user_id: str):
    """Return the connection only if the principal can access its project."""
    conn = await _connection_svc.get(session, connection_id)
    if not conn:
        raise _AccessDeniedError(f"Connection '{connection_id}' not found")
    await _require_project_access(session, conn.project_id, user_id)
    return conn


def _get_trace_svc():
    """Best-effort retrieval of the global TracePersistenceService."""
    try:
        import app.main as _main_mod

        _app = getattr(_main_mod, "app", None)
        if _app:
            return getattr(_app.state, "trace_persistence_service", None)
    except Exception:
        pass
    return None


def _make_orchestrator() -> OrchestratorAgent:
    return OrchestratorAgent(llm_router=LLMRouter())


def _clamp_pagination(offset: int | None, limit: int | None) -> tuple[int, int]:
    off = max(int(offset or 0), 0)
    lim = int(limit or DEFAULT_PAGE_LIMIT)
    lim = max(1, min(lim, MAX_PAGE_LIMIT))
    return off, lim


def _paginate(items: list, offset: int, limit: int) -> dict[str, Any]:
    total = len(items)
    page = items[offset : offset + limit]
    next_offset = offset + limit if offset + limit < total else None
    return {
        "total": total,
        "count": len(page),
        "offset": offset,
        "items": page,
        "has_more": next_offset is not None,
        "next_offset": next_offset,
    }


def _format_query_result(qr: QueryResult) -> dict[str, Any]:
    return {
        "columns": qr.columns,
        "rows": qr.rows[:100],
        "row_count": qr.row_count,
        "execution_time_ms": qr.execution_time_ms,
        "error": qr.error,
    }


def _agent_response_to_dict(resp: AgentResponse) -> dict[str, Any]:
    result: dict[str, Any] = {
        "answer": resp.answer,
        "response_type": resp.response_type,
    }
    if resp.query:
        result["query"] = resp.query
    if resp.query_explanation:
        result["query_explanation"] = resp.query_explanation
    if resp.results:
        result["results"] = _format_query_result(resp.results)
    if resp.viz_type != "text":
        result["viz_type"] = resp.viz_type
        result["viz_config"] = resp.viz_config
    if resp.knowledge_sources:
        result["sources"] = [
            {"source_path": s.source_path, "doc_type": s.doc_type} for s in resp.knowledge_sources
        ]
    if resp.error:
        result["error"] = resp.error
    return result


# ---------------------------------------------------------------------------
# Markdown renderers
# ---------------------------------------------------------------------------


def _md_projects(payload: dict[str, Any]) -> str:
    items = payload.get("items", [])
    if not items:
        return "_No accessible projects._"
    lines = [f"### Projects ({payload['count']}/{payload['total']})", ""]
    for p in items:
        desc = (p.get("description") or "").strip()
        lines.append(f"- **{p['name']}** (`{p['id']}`)" + (f" — {desc}" if desc else ""))
    if payload.get("has_more"):
        lines.append(f"\n_more available — next_offset={payload['next_offset']}_")
    return "\n".join(lines)


def _md_connections(payload: dict[str, Any]) -> str:
    items = payload.get("items", [])
    if not items:
        return "_No connections configured for this project._"
    lines = [f"### Connections ({payload['count']}/{payload['total']})", ""]
    for c in items:
        active = "active" if c.get("is_active") else "inactive"
        lines.append(
            f"- **{c['name']}** (`{c['id']}`) — {c['db_type']} / {c['source_type']} — {active}"
        )
    if payload.get("has_more"):
        lines.append(f"\n_more available — next_offset={payload['next_offset']}_")
    return "\n".join(lines)


def _md_schema(payload: dict[str, Any]) -> str:
    tables = payload.get("items", [])
    if not tables:
        return "_No tables indexed for this connection._"
    lines = [f"### Schema ({payload['count']}/{payload['total']} tables)", ""]
    for t in tables:
        head = f"#### `{t.get('schema', 'public')}.{t['name']}`"
        if t.get("row_count") is not None:
            head += f"  ·  rows ≈ {t['row_count']}"
        lines.append(head)
        desc = (t.get("description") or "").strip()
        if desc:
            lines.append(f"> {desc}")
        cols = t.get("columns") or {}
        if isinstance(cols, dict) and cols:
            for col_name, col_info in cols.items():
                if isinstance(col_info, dict):
                    typ = col_info.get("type", "")
                    note = col_info.get("note") or col_info.get("description") or ""
                    suffix = f" — {note}" if note else ""
                    lines.append(f"  - `{col_name}` {typ}".rstrip() + suffix)
                else:
                    lines.append(f"  - `{col_name}` — {col_info}")
        lines.append("")
    if payload.get("has_more"):
        lines.append(f"_more available — next_offset={payload['next_offset']}_")
    return "\n".join(lines).rstrip()


def _emit(payload: dict[str, Any], response_format: str, md_render) -> str:
    """Return either JSON or Markdown for a payload."""
    if (response_format or "json").lower() == "markdown":
        return md_render(payload)
    return json.dumps(payload, default=str)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


async def ping(principal: dict) -> str:
    """Minimal health-check tool. Returns the resolved principal so clients
    can verify the server, auth, and user binding all work end-to-end."""
    return json.dumps(
        {
            "ok": True,
            "principal": {"user_id": _principal_user_id(principal)},
            "version": 1,
        }
    )


async def query_database(
    principal: dict,
    project_id: str,
    question: str,
    connection_id: str | None = None,
) -> str:
    """Ask a natural-language question about data in a project's database.

    Returns the answer, SQL query, results, and visualization config.
    """
    user_id = _principal_user_id(principal)
    async with async_session_factory() as session:
        project = await _project_svc.get(session, project_id)
        if not project:
            return json.dumps({"error": f"Project '{project_id}' not found"})

        try:
            await _require_project_access(session, project_id, user_id)
        except _AccessDeniedError as exc:
            return json.dumps({"error": str(exc)})

        connections = await _connection_svc.list_by_project(session, project_id)
        if not connections:
            return json.dumps({"error": "No connections configured for this project"})

        conn = None
        if connection_id:
            conn = await _connection_svc.get(session, connection_id)
            # A connection_id must both exist and belong to the named project,
            # otherwise a caller could read across projects by id.
            if not conn or conn.project_id != project_id:
                return json.dumps({"error": f"Connection '{connection_id}' not found"})
        else:
            conn = connections[0]

        config = await _connection_svc.to_config(session, conn)
        config.connection_id = conn.id

    wf_id = await _singleton_tracker.begin(
        "mcp_query_database",
        context={"project_id": project_id, "user_id": user_id},
    )

    ctx = AgentContext(
        project_id=project_id,
        connection_config=config,
        user_question=question,
        chat_history=[],
        llm_router=LLMRouter(),
        tracker=_singleton_tracker,
        workflow_id=wf_id,
        user_id=user_id,
        project_name=project.name if project else None,
    )

    orchestrator = _make_orchestrator()
    resp: AgentResponse = await orchestrator.run(ctx)

    try:
        trace_svc = _get_trace_svc()
        if trace_svc is not None:
            await trace_svc.finalize_trace(
                wf_id,
                project_id=project_id,
                user_id=user_id,
                question=question,
                response_type=resp.response_type or "text",
                status="failed" if resp.error else "completed",
                error_message=resp.error,
            )
    except Exception:
        logger.warning("MCP: failed to finalize trace", exc_info=True)

    return json.dumps(_agent_response_to_dict(resp), default=str)


async def search_codebase(principal: dict, project_id: str, question: str) -> str:
    """Search the indexed project codebase for information."""
    user_id = _principal_user_id(principal)
    async with async_session_factory() as session:
        project = await _project_svc.get(session, project_id)
        if not project:
            return json.dumps({"error": f"Project '{project_id}' not found"})
        try:
            await _require_project_access(session, project_id, user_id)
        except _AccessDeniedError as exc:
            return json.dumps({"error": str(exc)})

    wf_id = await _singleton_tracker.begin(
        "mcp_search_codebase",
        context={"project_id": project_id, "user_id": user_id},
    )

    ctx = AgentContext(
        project_id=project_id,
        connection_config=None,
        user_question=question,
        chat_history=[],
        llm_router=LLMRouter(),
        tracker=_singleton_tracker,
        workflow_id=wf_id,
        user_id=user_id,
        project_name=project.name if project else None,
    )

    orchestrator = _make_orchestrator()
    resp: AgentResponse = await orchestrator.run(ctx)

    try:
        trace_svc = _get_trace_svc()
        if trace_svc is not None:
            await trace_svc.finalize_trace(
                wf_id,
                project_id=project_id,
                user_id=user_id,
                question=question,
                response_type=resp.response_type or "text",
                status="failed" if resp.error else "completed",
                error_message=resp.error,
            )
    except Exception:
        logger.warning("MCP: failed to finalize trace", exc_info=True)

    return json.dumps(_agent_response_to_dict(resp), default=str)


async def list_projects(
    principal: dict,
    offset: int = 0,
    limit: int = DEFAULT_PAGE_LIMIT,
    response_format: str = "json",
) -> str:
    """List only the projects the authenticated principal can access (paginated)."""
    user_id = _principal_user_id(principal)
    if not user_id:
        empty = _paginate([], 0, DEFAULT_PAGE_LIMIT)
        # Preserve historical contract for unauthenticated callers.
        empty["projects"] = empty["items"]
        return _emit(empty, response_format, _md_projects)
    async with async_session_factory() as session:
        projects = await _membership_svc.list_accessible(session, user_id)

    rows = [
        {"id": p.id, "name": p.name, "description": getattr(p, "description", "") or ""}
        for p in projects
    ]
    off, lim = _clamp_pagination(offset, limit)
    payload = _paginate(rows, off, lim)
    # Back-compat field for older clients.
    payload["projects"] = payload["items"]
    return _emit(payload, response_format, _md_projects)


async def list_connections(
    principal: dict,
    project_id: str,
    offset: int = 0,
    limit: int = DEFAULT_PAGE_LIMIT,
    response_format: str = "json",
) -> str:
    """List connections for a project the principal can access (paginated)."""
    user_id = _principal_user_id(principal)
    async with async_session_factory() as session:
        try:
            await _require_project_access(session, project_id, user_id)
        except _AccessDeniedError as exc:
            return json.dumps({"error": str(exc)})
        connections = await _connection_svc.list_by_project(session, project_id)

    rows = [
        {
            "id": c.id,
            "name": c.name,
            "db_type": c.db_type,
            "source_type": c.source_type,
            "is_active": c.is_active,
        }
        for c in connections
    ]
    off, lim = _clamp_pagination(offset, limit)
    payload = _paginate(rows, off, lim)
    payload["connections"] = payload["items"]
    return _emit(payload, response_format, _md_connections)


async def get_schema(
    principal: dict,
    connection_id: str,
    offset: int = 0,
    limit: int = 50,
    response_format: str = "json",
) -> str:
    """Get the indexed database schema for a connection the principal can access.

    Returns a paginated list of tables with columns, row counts, and any
    business descriptions captured during indexing.
    """
    user_id = _principal_user_id(principal)
    async with async_session_factory() as session:
        try:
            await _require_connection_access(session, connection_id, user_id)
        except _AccessDeniedError as exc:
            return json.dumps({"error": str(exc)})
        entries = await _db_index_svc.get_index(session, connection_id)

    if not entries:
        return json.dumps({"error": "No schema index found for this connection"})

    tables = []
    for entry in entries:
        columns: Any = {}
        columns_raw = entry.column_notes_json or "{}"
        if columns_raw != "{}":
            try:
                columns = json.loads(columns_raw)
            except (json.JSONDecodeError, TypeError):
                columns = {}

        tables.append(
            {
                "name": entry.table_name,
                "schema": entry.table_schema or "public",
                "columns": columns,
                "row_count": entry.row_count,
                "description": entry.business_description,
            }
        )

    off, lim = _clamp_pagination(offset, limit)
    payload = _paginate(tables, off, lim)
    payload["tables"] = payload["items"]
    return _emit(payload, response_format, _md_schema)


async def execute_raw_query(principal: dict, connection_id: str, query: str) -> str:
    """Execute a raw SQL query against a connection the principal can access.

    Requires the connection to be in read-only mode for safety.
    """
    from app.core.safety import SafetyGuard, SafetyLevel

    user_id = _principal_user_id(principal)
    async with async_session_factory() as session:
        try:
            conn = await _require_connection_access(session, connection_id, user_id)
        except _AccessDeniedError as exc:
            return json.dumps({"error": str(exc)})

        if not conn.is_read_only:
            return json.dumps(
                {"error": "Raw query execution is only allowed on read-only connections"}
            )

        guard = SafetyGuard(SafetyLevel.READ_ONLY)
        safety_result = guard.validate(query, conn.db_type)
        if not safety_result.is_safe:
            return json.dumps({"error": f"Query blocked: {safety_result.reason}"})

        config = await _connection_svc.to_config(session, conn)

    from app.connectors.registry import get_connector

    connector = get_connector(conn.db_type, ssh_exec_mode=config.ssh_exec_mode)
    try:
        await connector.connect(config)
        try:
            result = await connector.execute_query(query)
        finally:
            await connector.disconnect()
    except Exception as e:
        logger.exception("Raw query execution failed")
        return json.dumps({"error": str(e)})

    return json.dumps(_format_query_result(result), default=str)
