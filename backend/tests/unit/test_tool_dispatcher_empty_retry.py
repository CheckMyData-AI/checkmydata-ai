"""I2/I3: a clean zero-row SQL result must not be double-retried by the
dispatcher — the orchestrator result-gate is the single owner of the
empty-result re-query decision."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.base import AgentContext
from app.agents.sql_agent import SQLAgentResult
from app.agents.tool_dispatcher import ToolDispatcher
from app.agents.validation import AgentResultValidator
from app.connectors.base import QueryResult
from app.core.workflow_tracker import WorkflowTracker
from app.llm.base import ToolCall


@pytest.fixture
def mock_tracker():
    t = MagicMock(spec=WorkflowTracker)
    t.emit = AsyncMock()

    @asynccontextmanager
    async def fake_step(wf_id, step, detail="", **kwargs):
        yield

    t.step = MagicMock(side_effect=fake_step)
    return t


@pytest.fixture
def context():
    return AgentContext(
        project_id="proj-1",
        connection_config=None,
        user_question="how many widgets?",
        chat_history=[],
        llm_router=MagicMock(),
        tracker=MagicMock(),
        workflow_id="wf-1",
    )


@pytest.mark.asyncio
async def test_clean_empty_result_not_retried_by_dispatcher(mock_tracker, context):
    empty = SQLAgentResult(
        status="success",
        query="SELECT count(*) FROM widgets",
        results=QueryResult(columns=["c"], rows=[], row_count=0),
    )
    mock_sql = MagicMock()
    mock_sql.run = AsyncMock(return_value=empty)

    d = ToolDispatcher(
        sql_agent=mock_sql,
        knowledge_agent=MagicMock(),
        mcp_source_agent=MagicMock(),
        validator=AgentResultValidator(),
        tracker=mock_tracker,
        wf_sql_results={},
        wf_enriched={},
    )
    tc = ToolCall(id="t1", name="query_database", arguments={"question": "how many widgets?"})

    with patch("app.agents.tool_dispatcher.settings.query_empty_result_retry", True):
        text, sub = await d._handle_query_database(tc, context, "wf-1", {})

    # Single owner of the empty-result re-query is the result gate, not the
    # dispatcher — a clean zero-row result is returned after exactly one call.
    assert mock_sql.run.await_count == 1
    assert sub is empty
