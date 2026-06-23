"""MCP resource providers — read-only data exposed to MCP clients.

Resources give clients structured access to project metadata without
going through the full agent pipeline. Every resource requires an
authenticated principal with membership access to the project — the same
tenancy rule the MCP tools enforce (F-SEC-1).
"""

from __future__ import annotations

import json
import logging

from mcp.server.fastmcp.exceptions import ToolError

from app.mcp_server.runtime import Principal
from app.models.base import async_session_factory
from app.services.connection_service import ConnectionService
from app.services.db_index_service import DbIndexService
from app.services.membership_service import MembershipService
from app.services.rule_service import RuleService

logger = logging.getLogger(__name__)

# Cap the number of tables returned by the project_schema resource. A very
# large schema (hundreds of tables × many connections) could produce a
# response that exceeds MCP transport limits or overloads client context
# windows. We surface the full count so callers know truncation occurred.
MAX_RESOURCE_TABLES = 500

_connection_svc = ConnectionService()
_db_index_svc = DbIndexService()
_membership_svc = MembershipService()
_rule_svc = RuleService()


class ResourceAccessDeniedError(Exception):
    """Raised when a principal may not read a project's resources."""


def _principal_user_id(principal: Principal) -> str:
    return (principal or {}).get("user_id") or ""


async def _require_project_access(session, project_id: str, user_id: str) -> None:
    if not user_id or not await _membership_svc.can_access(session, project_id, user_id):
        raise ResourceAccessDeniedError(f"Access denied to project '{project_id}'")


def _denied(exc: Exception) -> None:
    raise ToolError(str(exc))


async def get_project_schema(principal: Principal, project_id: str) -> str:
    """Return aggregated database schema for all connections in a project."""
    user_id = _principal_user_id(principal)
    async with async_session_factory() as session:
        try:
            await _require_project_access(session, project_id, user_id)
        except ResourceAccessDeniedError as exc:
            _denied(exc)
        connections = await _connection_svc.list_by_project(session, project_id)

        all_tables: list[dict] = []
        for conn in connections:
            entries = await _db_index_svc.get_index(session, conn.id)
            for entry in entries:
                columns: list[dict] = []
                columns_raw = getattr(entry, "column_notes_json", None) or "{}"
                if columns_raw and columns_raw != "{}":
                    try:
                        notes = json.loads(columns_raw)
                        if isinstance(notes, dict):
                            # Always a list — a dict here would give the "columns"
                            # key an inconsistent JSON type across tables.
                            columns = [{"name": c, "note": n} for c, n in notes.items()]
                    except (json.JSONDecodeError, TypeError):
                        pass
                all_tables.append(
                    {
                        "connection_id": conn.id,
                        "connection_name": conn.name,
                        "table_name": entry.table_name,
                        "table_schema": entry.table_schema or "public",
                        "columns": columns,
                        "row_count": entry.row_count,
                    }
                )

    total_tables = len(all_tables)
    truncated = total_tables > MAX_RESOURCE_TABLES
    tables = all_tables[:MAX_RESOURCE_TABLES]
    return json.dumps(
        {
            "tables": tables,
            "total_tables": total_tables,
            "truncated": truncated,
        },
        default=str,
    )


async def get_project_rules(principal: Principal, project_id: str) -> str:
    """Return custom rules defined for a project."""
    user_id = _principal_user_id(principal)
    async with async_session_factory() as session:
        try:
            await _require_project_access(session, project_id, user_id)
        except ResourceAccessDeniedError as exc:
            _denied(exc)
        rules = await _rule_svc.list_all(session, project_id=project_id)

    return json.dumps(
        {
            "rules": [
                {
                    "id": r.id,
                    "name": r.name,
                    "content": r.content,
                    "format": r.format,
                }
                for r in rules
            ],
        },
        default=str,
    )


async def get_project_knowledge(principal: Principal, project_id: str) -> str:
    """Return a summary of the project's knowledge base."""
    user_id = _principal_user_id(principal)
    async with async_session_factory() as session:
        try:
            await _require_project_access(session, project_id, user_id)
        except ResourceAccessDeniedError as exc:
            _denied(exc)
    try:
        from app.knowledge.vector_store import VectorStore

        vs = VectorStore()
        collection = vs.get_or_create_collection(project_id)
        count = collection.count()
        return json.dumps(
            {
                "project_id": project_id,
                "document_count": count,
                "status": "indexed" if count > 0 else "empty",
            }
        )
    except Exception as e:
        logger.debug("Failed to read knowledge base for %s: %s", project_id, e)
        return json.dumps(
            {
                "project_id": project_id,
                "document_count": 0,
                "status": "unavailable",
                "error": str(e),
            }
        )
