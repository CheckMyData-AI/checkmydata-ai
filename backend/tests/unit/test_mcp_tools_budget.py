"""Budget gate tests for MCP agent tools.

Verifies that query_database and search_codebase block the orchestrator
and return an error JSON when the token budget is exhausted.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

from app.mcp_server import tools


async def test_query_database_blocks_when_budget_exhausted():
    principal = {"user_id": "u1", "email": ""}
    project = MagicMock(id="p1", name="Proj")

    with (
        patch.object(tools._project_svc, "get", new=AsyncMock(return_value=project)),
        patch.object(tools, "_require_project_access", new=AsyncMock(return_value=None)),
        patch.object(
            tools._connection_svc,
            "list_by_project",
            new=AsyncMock(return_value=[MagicMock(id="c1")]),
        ),
        patch.object(
            tools._usage_svc,
            "check_token_budget",
            new=AsyncMock(
                return_value=(
                    "Daily token budget exceeded — upgrade your plan at /pricing to continue."
                )
            ),
        ),
        patch.object(tools, "_make_orchestrator") as make_orch,
    ):
        out = await tools.query_database(principal, "p1", "how many users?")

    payload = json.loads(out)
    assert "/pricing" in payload["error"]
    make_orch.assert_not_called()


async def test_search_codebase_blocks_when_budget_exhausted():
    principal = {"user_id": "u1", "email": ""}
    project = MagicMock(id="p1", name="Proj")

    with (
        patch.object(tools._project_svc, "get", new=AsyncMock(return_value=project)),
        patch.object(tools, "_require_project_access", new=AsyncMock(return_value=None)),
        patch.object(
            tools._usage_svc,
            "check_token_budget",
            new=AsyncMock(
                return_value=(
                    "Daily token budget exceeded — upgrade your plan at /pricing to continue."
                )
            ),
        ),
        patch.object(tools, "_make_orchestrator") as make_orch,
    ):
        out = await tools.search_codebase(principal, "p1", "where is auth handled?")

    payload = json.loads(out)
    assert "/pricing" in payload["error"]
    make_orch.assert_not_called()


async def test_query_database_proceeds_when_budget_ok():
    """When budget is fine (returns None), the orchestrator runs normally."""
    principal = {"user_id": "u1", "email": ""}
    project = MagicMock(id="p1", name="Proj")

    mock_conn = MagicMock(id="c1", project_id="p1")
    mock_config = MagicMock()
    mock_resp = MagicMock(
        answer="42",
        response_type="text",
        query=None,
        query_explanation=None,
        results=None,
        viz_type="text",
        knowledge_sources=None,
        error=None,
    )
    mock_orch = MagicMock()
    mock_orch.run = AsyncMock(return_value=mock_resp)

    with (
        patch.object(tools._project_svc, "get", new=AsyncMock(return_value=project)),
        patch.object(tools, "_require_project_access", new=AsyncMock(return_value=None)),
        patch.object(
            tools._connection_svc, "list_by_project", new=AsyncMock(return_value=[mock_conn])
        ),
        patch.object(tools._connection_svc, "to_config", new=AsyncMock(return_value=mock_config)),
        patch.object(
            tools._usage_svc,
            "check_token_budget",
            new=AsyncMock(return_value=None),  # budget OK
        ),
        patch.object(tools, "_make_orchestrator", return_value=mock_orch),
        patch.object(tools._singleton_tracker, "begin", new=AsyncMock(return_value="wf-1")),
        patch.object(tools, "_get_trace_svc", return_value=None),
    ):
        out = await tools.query_database(principal, "p1", "how many users?")

    payload = json.loads(out)
    assert payload.get("error") is None
    mock_orch.run.assert_awaited_once()


async def test_search_codebase_proceeds_when_budget_ok():
    """When budget is fine (returns None), the orchestrator runs normally."""
    principal = {"user_id": "u1", "email": ""}
    project = MagicMock(id="p1", name="Proj")

    mock_resp = MagicMock(
        answer="Auth is in middleware",
        response_type="text",
        query=None,
        query_explanation=None,
        results=None,
        viz_type="text",
        knowledge_sources=None,
        error=None,
    )
    mock_orch = MagicMock()
    mock_orch.run = AsyncMock(return_value=mock_resp)

    with (
        patch.object(tools._project_svc, "get", new=AsyncMock(return_value=project)),
        patch.object(tools, "_require_project_access", new=AsyncMock(return_value=None)),
        patch.object(
            tools._usage_svc,
            "check_token_budget",
            new=AsyncMock(return_value=None),  # budget OK
        ),
        patch.object(tools, "_make_orchestrator", return_value=mock_orch),
        patch.object(tools._singleton_tracker, "begin", new=AsyncMock(return_value="wf-1")),
        patch.object(tools, "_get_trace_svc", return_value=None),
    ):
        out = await tools.search_codebase(principal, "p1", "where is auth handled?")

    payload = json.loads(out)
    assert payload.get("error") is None
    mock_orch.run.assert_awaited_once()
