"""MCP resource providers — read-only data exposed to MCP clients.

Resources give clients structured access to project metadata without
going through the full agent pipeline.
"""

from __future__ import annotations

import json
import logging

from app.models.base import async_session_factory
from app.services.connection_service import ConnectionService
from app.services.db_index_service import DbIndexService
from app.services.rule_service import RuleService

logger = logging.getLogger(__name__)

_connection_svc = ConnectionService()
_db_index_svc = DbIndexService()
_rule_svc = RuleService()


async def get_project_schema(project_id: str) -> str:
    """Return aggregated database schema for all connections in a project."""
    async with async_session_factory() as session:
        connections = await _connection_svc.list_by_project(session, project_id)

        all_tables: list[dict] = []
        for conn in connections:
            entries = await _db_index_svc.get_index(session, conn.id)
            for entry in entries:
                columns = []
                if entry.columns_json:
                    try:
                        columns = json.loads(entry.columns_json)
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

    return json.dumps({"tables": all_tables}, default=str)


async def get_project_rules(project_id: str) -> str:
    """Return custom rules defined for a project."""
    async with async_session_factory() as session:
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


async def get_project_knowledge(project_id: str) -> str:
    """Return a summary of the project's knowledge base."""
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
