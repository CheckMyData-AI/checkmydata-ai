"""Tests for the Git-related branches of ToolDispatcher.

Covers the analyze_git / get_release_timeline / write_code_note handlers
(including the no-git-agent fallbacks) and the params_json merge in
``build_process_data_params`` used by the cohort_window operation.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.base import AgentContext
from app.agents.git_agent import GitAgentResult
from app.agents.tool_dispatcher import ToolDispatcher
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
def mock_git_agent():
    g = MagicMock()
    g.run = AsyncMock()
    g.get_release_timeline = AsyncMock()
    g.write_code_note = AsyncMock()
    return g


def _make_dispatcher(mock_tracker, git_agent):
    return ToolDispatcher(
        sql_agent=MagicMock(),
        knowledge_agent=MagicMock(),
        mcp_source_agent=MagicMock(),
        validator=MagicMock(),
        tracker=mock_tracker,
        wf_sql_results={},
        wf_enriched={},
        git_agent=git_agent,
    )


@pytest.fixture
def context():
    return AgentContext(
        project_id="proj-1",
        connection_config=None,
        user_question="What changed?",
        chat_history=[],
        llm_router=MagicMock(),
        tracker=MagicMock(),
        workflow_id="wf-1",
    )


class TestAnalyzeGitHandler:
    @pytest.mark.asyncio
    async def test_dispatches_to_git_agent(self, mock_tracker, mock_git_agent, context):
        mock_git_agent.run.return_value = GitAgentResult(
            answer="3 commits since v1.0.0", status="success", token_usage={}
        )
        d = _make_dispatcher(mock_tracker, mock_git_agent)
        tc = ToolCall(id="t1", name="analyze_git", arguments={"question": "recent commits"})

        text, sub = await d._handle_analyze_git(tc, context, "wf-1", {})

        assert "3 commits" in text
        assert isinstance(sub, GitAgentResult)
        mock_git_agent.run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_git_agent_returns_unavailable(self, mock_tracker, context):
        d = _make_dispatcher(mock_tracker, None)
        tc = ToolCall(id="t1", name="analyze_git", arguments={"question": "x"})

        text, sub = await d._handle_analyze_git(tc, context, "wf-1", {})

        assert "not available" in text
        assert sub is None


class TestReleaseTimelineHandler:
    @pytest.mark.asyncio
    async def test_dispatches(self, mock_tracker, mock_git_agent, context):
        mock_git_agent.get_release_timeline.return_value = "| tag | ... |"
        d = _make_dispatcher(mock_tracker, mock_git_agent)
        tc = ToolCall(id="t1", name="get_release_timeline", arguments={"max_count": 10})

        out = await d._handle_get_release_timeline(tc, context, "wf-1")

        assert "tag" in out
        mock_git_agent.get_release_timeline.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_git_agent(self, mock_tracker, context):
        d = _make_dispatcher(mock_tracker, None)
        tc = ToolCall(id="t1", name="get_release_timeline", arguments={})
        out = await d._handle_get_release_timeline(tc, context, "wf-1")
        assert "not available" in out


class TestWriteCodeNoteHandler:
    @pytest.mark.asyncio
    async def test_dispatches(self, mock_tracker, mock_git_agent, context):
        mock_git_agent.write_code_note.return_value = "Saved code note about 'x'."
        d = _make_dispatcher(mock_tracker, mock_git_agent)
        tc = ToolCall(
            id="t1",
            name="write_code_note",
            arguments={"subject": "auth.py:login", "note": "bcrypt"},
        )

        out = await d._handle_write_code_note(tc, context)

        assert "Saved code note" in out
        mock_git_agent.write_code_note.assert_awaited_once_with("proj-1", "auth.py:login", "bcrypt")

    @pytest.mark.asyncio
    async def test_no_git_agent(self, mock_tracker, context):
        d = _make_dispatcher(mock_tracker, None)
        tc = ToolCall(id="t1", name="write_code_note", arguments={})
        out = await d._handle_write_code_note(tc, context)
        assert "not available" in out


class TestBuildProcessDataParams:
    def test_params_json_merged_for_cohort_window(self):
        args = {
            "operation": "cohort_window",
            "params_json": (
                '{"release_dates": [{"tag": "v1", "date": "2026-01-15"}], '
                '"event_date_column": "created_at", "value_column": "amount", '
                '"windows": [7, 14], "metric": "revenue"}'
            ),
        }
        params = ToolDispatcher.build_process_data_params(args)
        assert params["event_date_column"] == "created_at"
        assert params["windows"] == [7, 14]
        assert params["release_dates"][0]["tag"] == "v1"

    def test_params_json_accepts_dict(self):
        args = {"params_json": {"windows": [30]}}
        params = ToolDispatcher.build_process_data_params(args)
        assert params["windows"] == [30]

    def test_invalid_params_json_ignored(self):
        args = {"column": "country", "params_json": "{not valid json"}
        params = ToolDispatcher.build_process_data_params(args)
        assert params["column"] == "country"
        assert "windows" not in params
