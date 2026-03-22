"""MCP tool handlers that delegate to the OrchestratorAgent and services.

Each function here is registered as an MCP tool and bridges the external
MCP protocol into the existing agent infrastructure.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.base import AgentContext
from app.agents.orchestrator import AgentResponse, OrchestratorAgent
from app.connectors.base import QueryResult
from app.core.workflow_tracker import WorkflowTracker
from app.llm.router import LLMRouter
from app.models.base import async_session_factory
from app.services.connection_service import ConnectionService
from app.services.db_index_service import DbIndexService
from app.services.project_service import ProjectService

logger = logging.getLogger(__name__)

_project_svc = ProjectService()
_connection_svc = ConnectionService()
_db_index_svc = DbIndexService()


def _make_orchestrator() -> OrchestratorAgent:
    return OrchestratorAgent(llm_router=LLMRouter())


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


async def query_database(
    project_id: str,
    question: str,
    connection_id: str | None = None,
) -> str:
    """Ask a natural-language question about data in a project's database.

    Returns the answer, SQL query, results, and visualization config.
    """
    async with async_session_factory() as session:
        project = await _project_svc.get(session, project_id)
        if not project:
            return json.dumps({"error": f"Project '{project_id}' not found"})

        connections = await _connection_svc.list_by_project(session, project_id)
        if not connections:
            return json.dumps({"error": "No connections configured for this project"})

        conn = None
        if connection_id:
            conn = await _connection_svc.get(session, connection_id)
            if not conn:
                return json.dumps({"error": f"Connection '{connection_id}' not found"})
        else:
            conn = connections[0]

        config = await _connection_svc.to_config(session, conn)
        config.connection_id = conn.id

    tracker = WorkflowTracker()
    wf_id = await tracker.begin("mcp_query_database")

    ctx = AgentContext(
        project_id=project_id,
        connection_config=config,
        user_question=question,
        chat_history=[],
        llm_router=LLMRouter(),
        tracker=tracker,
        workflow_id=wf_id,
        user_id="mcp-user",
        project_name=project.name if project else None,
    )

    orchestrator = _make_orchestrator()
    resp: AgentResponse = await orchestrator.run(ctx)
    return json.dumps(_agent_response_to_dict(resp), default=str)


async def search_codebase(project_id: str, question: str) -> str:
    """Search the indexed project codebase for information."""
    async with async_session_factory() as session:
        project = await _project_svc.get(session, project_id)
        if not project:
            return json.dumps({"error": f"Project '{project_id}' not found"})

    tracker = WorkflowTracker()
    wf_id = await tracker.begin("mcp_search_codebase")

    ctx = AgentContext(
        project_id=project_id,
        connection_config=None,
        user_question=question,
        chat_history=[],
        llm_router=LLMRouter(),
        tracker=tracker,
        workflow_id=wf_id,
        user_id="mcp-user",
        project_name=project.name if project else None,
    )

    orchestrator = _make_orchestrator()
    resp: AgentResponse = await orchestrator.run(ctx)
    return json.dumps(_agent_response_to_dict(resp), default=str)


async def list_projects() -> str:
    """List all accessible projects."""
    async with async_session_factory() as session:
        projects = await _project_svc.list_all(session)
    return json.dumps(
        {
            "projects": [
                {"id": p.id, "name": p.name, "description": getattr(p, "description", "")}
                for p in projects
            ],
        }
    )


async def list_connections(project_id: str) -> str:
    """List connections for a project."""
    async with async_session_factory() as session:
        connections = await _connection_svc.list_by_project(session, project_id)
    return json.dumps(
        {
            "connections": [
                {
                    "id": c.id,
                    "name": c.name,
                    "db_type": c.db_type,
                    "source_type": c.source_type,
                    "is_active": c.is_active,
                }
                for c in connections
            ],
        }
    )


async def get_schema(connection_id: str) -> str:
    """Get the indexed database schema for a connection."""
    async with async_session_factory() as session:
        entries = await _db_index_svc.get_index(session, connection_id)

    if not entries:
        return json.dumps({"error": "No schema index found for this connection"})

    tables = []
    for entry in entries:
        columns = {}
        columns_raw = entry.column_notes_json or "{}"
        if columns_raw != "{}":
            try:
                columns = json.loads(columns_raw)
            except (json.JSONDecodeError, TypeError):
                pass

        tables.append(
            {
                "name": entry.table_name,
                "schema": entry.table_schema or "public",
                "columns": columns,
                "row_count": entry.row_count,
                "description": entry.business_description,
            }
        )

    return json.dumps({"tables": tables}, default=str)


async def execute_raw_query(connection_id: str, query: str) -> str:
    """Execute a raw SQL query against a connection.

    Requires the connection to be in read-only mode for safety.
    """
    from app.core.safety import SafetyGuard, SafetyLevel

    async with async_session_factory() as session:
        conn = await _connection_svc.get(session, connection_id)
        if not conn:
            return json.dumps({"error": f"Connection '{connection_id}' not found"})

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
