"""Tests for GitAgent — live read-only Git history specialist.

Covers the name property, the no-repo short-circuit, the bounded tool-calling
loop (plain answer + tool dispatch), deterministic helpers
(``get_release_timeline``, ``write_code_note``), and the result formatters.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.base import AgentContext
from app.agents.git_agent import GitAgent, GitAgentResult
from app.core.workflow_tracker import WorkflowTracker
from app.llm.base import LLMResponse, ToolCall


@pytest.fixture
def mock_tracker():
    t = MagicMock(spec=WorkflowTracker)
    t.begin = AsyncMock(return_value="wf-1")
    t.end = AsyncMock()
    t.emit = AsyncMock()

    @asynccontextmanager
    async def fake_step(wf_id, step, detail="", **kwargs):
        yield

    t.step = MagicMock(side_effect=fake_step)
    return t


@pytest.fixture
def mock_llm():
    router = MagicMock()
    router.complete = AsyncMock()
    router.get_context_window = MagicMock(return_value=128_000)
    return router


@pytest.fixture
def context(mock_llm, mock_tracker):
    return AgentContext(
        project_id="proj-1",
        connection_config=None,
        user_question="test question",
        chat_history=[],
        llm_router=mock_llm,
        tracker=mock_tracker,
        workflow_id="wf-1",
        user_id="user-1",
    )


@pytest.fixture
def repo_dir(tmp_path: Path) -> Path:
    """A directory that looks like a cloned repo (has a .git subdir)."""
    (tmp_path / ".git").mkdir()
    return tmp_path


@pytest.fixture
def agent(repo_dir):
    analyzer = MagicMock()
    analyzer.get_repo_dir = MagicMock(return_value=repo_dir)
    tracker = MagicMock()
    tracker.get_last_indexed_sha = AsyncMock(return_value=None)
    return GitAgent(repo_analyzer=analyzer, git_tracker=tracker)


def _llm_text(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        tool_calls=[],
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    )


def _llm_tool(tool_calls: list[ToolCall]) -> LLMResponse:
    return LLMResponse(
        content="",
        tool_calls=tool_calls,
        usage={"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
    )


class TestGitAgent:
    def test_name_property(self, agent):
        assert agent.name == "git"

    @pytest.mark.asyncio
    async def test_no_repo_returns_no_result(self, context, tmp_path):
        analyzer = MagicMock()
        analyzer.get_repo_dir = MagicMock(return_value=tmp_path)  # no .git
        bare = GitAgent(repo_analyzer=analyzer, git_tracker=MagicMock())

        result = await bare.run(context, question="What changed?")

        assert isinstance(result, GitAgentResult)
        assert result.status == "no_result"
        assert "does not have a cloned Git repository" in result.answer

    @pytest.mark.asyncio
    async def test_text_response_no_tools(self, agent, mock_llm, context):
        mock_llm.complete = AsyncMock(return_value=_llm_text("The repo uses trunk-based dev."))

        result = await agent.run(context, question="How does the repo work?")

        assert result.status == "success"
        assert result.answer == "The repo uses trunk-based dev."
        assert result.tool_call_log == []

    @pytest.mark.asyncio
    async def test_tool_dispatch_list_releases(self, agent, mock_llm, context):
        call_count = 0

        async def _complete(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _llm_tool(
                    [ToolCall(id="tc-1", name="list_releases", arguments={"max_count": 10})]
                )
            return _llm_text("There is one release: v1.0.0.")

        mock_llm.complete = AsyncMock(side_effect=_complete)

        fake_inspector = MagicMock()
        fake_inspector.list_releases = AsyncMock(
            return_value=[
                {
                    "tag_name": "v1.0.0",
                    "short_sha": "abc1234",
                    "commit_date": "2026-01-15",
                    "message": "First release",
                }
            ]
        )

        with patch("app.agents.git_agent.GitInspector", return_value=fake_inspector):
            result = await agent.run(context, question="What releases exist?")

        assert result.status == "success"
        assert "v1.0.0" in result.answer
        assert len(result.tool_call_log) == 1
        assert result.tool_call_log[0]["tool"] == "list_releases"
        assert "v1.0.0" in result.tool_call_log[0]["result_preview"]
        fake_inspector.list_releases.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_release_timeline_no_repo(self, tmp_path):
        analyzer = MagicMock()
        analyzer.get_repo_dir = MagicMock(return_value=tmp_path)
        bare = GitAgent(repo_analyzer=analyzer, git_tracker=MagicMock())

        out = await bare.get_release_timeline("proj-1")
        assert "No cloned Git repository" in out

    @pytest.mark.asyncio
    async def test_get_release_timeline_formats_table(self, agent):
        fake_inspector = MagicMock()
        fake_inspector.list_releases = AsyncMock(
            return_value=[
                {
                    "tag_name": "v2.0.0",
                    "short_sha": "def5678",
                    "commit_date": "2026-02-01",
                    "message": "Big release",
                }
            ]
        )
        with patch("app.agents.git_agent.GitInspector", return_value=fake_inspector):
            out = await agent.get_release_timeline("proj-1", max_count=5)

        assert "v2.0.0" in out
        assert "| tag | commit | date | summary |" in out

    @pytest.mark.asyncio
    async def test_write_code_note_requires_fields(self, agent):
        out = await agent.write_code_note("proj-1", "", "")
        assert "both 'subject' and 'note' are required" in out

    @pytest.mark.asyncio
    async def test_write_code_note_persists(self, agent):
        store = AsyncMock()
        fake_service = MagicMock()
        fake_service.store_insight = store

        @asynccontextmanager
        async def fake_session():
            yield MagicMock()

        with (
            patch("app.core.insight_memory.InsightMemoryService", return_value=fake_service),
            patch("app.models.base.async_session_factory", fake_session),
        ):
            out = await agent.write_code_note("proj-1", "auth.py:login", "Uses bcrypt rounds=12")

        assert "Saved code note" in out
        store.assert_awaited_once()
        kwargs = store.await_args.kwargs
        assert kwargs["insight_type"] == "code_finding"
        assert kwargs["title"] == "auth.py:login"

    def test_format_releases_empty(self):
        assert "No release tags" in GitAgent._format_releases([])

    def test_format_commits_empty(self):
        assert "No commits found" in GitAgent._format_commits([])

    def test_format_review_signals_merge(self):
        out = GitAgent._format_review_signals(
            {
                "short_sha": "abc1234",
                "is_merge_commit": True,
                "merge_source_branch": "feature/x",
                "reviewers": ["alice"],
            }
        )
        assert "merge commit: True" in out
        assert "feature/x" in out
        assert "alice" in out
