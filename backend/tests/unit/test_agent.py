"""Tests for ConversationalAgent (backward-compatible wrapper).

These tests verify the end-to-end flow through the wrapper -> OrchestratorAgent
-> sub-agents pipeline.  We mock at the LLM level (mock_llm.complete) so the
tests verify the real orchestration logic.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.connectors.base import ConnectionConfig
from app.core.agent import ConversationalAgent
from app.core.workflow_tracker import WorkflowTracker
from app.llm.base import LLMResponse, ToolCall


@pytest.fixture
def mock_tracker():
    t = MagicMock(spec=WorkflowTracker)
    t.begin = AsyncMock(return_value="wf-1")
    t.end = AsyncMock()
    t.emit = AsyncMock()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_step(wf_id, step, detail=""):
        yield

    t.step = MagicMock(side_effect=fake_step)
    return t


@pytest.fixture
def mock_llm():
    router = MagicMock()
    router.complete = AsyncMock()
    return router


@pytest.fixture
def mock_vector_store():
    vs = MagicMock()
    vs.query = MagicMock(return_value=[])
    collection = MagicMock()
    collection.count = MagicMock(return_value=0)
    vs.get_or_create_collection = MagicMock(return_value=collection)
    return vs


@pytest.fixture
def mock_custom_rules():
    cr = MagicMock()
    cr.load_rules = MagicMock(return_value=[])
    cr.load_db_rules = AsyncMock(return_value=[])
    cr.rules_to_context = MagicMock(return_value="")
    return cr


@pytest.fixture
def config():
    return ConnectionConfig(
        db_type="postgres",
        db_host="localhost",
        db_port=5432,
        db_name="testdb",
        db_user="user",
    )


@pytest.fixture
def agent(mock_llm, mock_vector_store, mock_custom_rules, mock_tracker):
    return ConversationalAgent(
        llm_router=mock_llm,
        vector_store=mock_vector_store,
        custom_rules=mock_custom_rules,
        workflow_tracker=mock_tracker,
    )


class TestConversationalResponse:
    """Agent responds with text when the LLM does not call any tool."""

    @pytest.mark.asyncio
    async def test_text_response_no_tools(self, agent, mock_llm):
        mock_llm.complete = AsyncMock(
            return_value=LLMResponse(
                content="Hello! How can I help you?",
                tool_calls=[],
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            )
        )
        resp = await agent.run(
            question="Hi!",
            project_id="proj-1",
            connection_config=None,
        )
        assert resp.response_type == "text"
        assert resp.answer == "Hello! How can I help you?"
        assert resp.query is None
        assert resp.results is None

    @pytest.mark.asyncio
    async def test_text_response_with_connection(self, agent, mock_llm, config):
        mock_llm.complete = AsyncMock(
            return_value=LLMResponse(
                content="Sure, I can help with that. What would you like to know?",
                tool_calls=[],
                usage={"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            )
        )
        with (
            patch.object(
                agent._orchestrator,
                "_resolve_connection_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch.object(
                agent._orchestrator, "_build_table_map", new_callable=AsyncMock, return_value=""
            ),
        ):
            resp = await agent.run(
                question="Thanks for the earlier results",
                project_id="proj-1",
                connection_config=config,
            )
        assert resp.response_type == "text"
        assert "help" in resp.answer.lower()


class TestKnowledgeSearch:
    """Agent calls search_codebase (meta-tool) for project questions."""

    @pytest.mark.asyncio
    async def test_knowledge_search_flow(self, agent, mock_llm, mock_vector_store):
        collection = MagicMock()
        collection.count = MagicMock(return_value=10)
        mock_vector_store.get_or_create_collection = MagicMock(return_value=collection)

        mock_vector_store.query = MagicMock(
            return_value=[
                {
                    "document": "The project uses PostgreSQL 15",
                    "metadata": {"source_path": "README.md", "doc_type": "markdown"},
                    "distance": 0.1,
                },
            ]
        )

        call_count = 0

        async def complete_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1

            tools = kwargs.get("tools")
            tool_names = {t.name for t in tools} if tools else set()

            if call_count == 1 and "search_codebase" in tool_names:
                return LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="tc-1",
                            name="search_codebase",
                            arguments={"question": "What database does the project use?"},
                        ),
                    ],
                    usage={"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70},
                )

            if "search_knowledge" in tool_names:
                return LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="tc-k1",
                            name="search_knowledge",
                            arguments={"query": "database type", "max_results": 5},
                        ),
                    ],
                    usage={"prompt_tokens": 30, "completion_tokens": 10, "total_tokens": 40},
                )

            return LLMResponse(
                content="The project uses PostgreSQL 15 as documented in README.md.",
                tool_calls=[],
                usage={"prompt_tokens": 80, "completion_tokens": 30, "total_tokens": 110},
            )

        mock_llm.complete = AsyncMock(side_effect=complete_side_effect)

        resp = await agent.run(
            question="What database does the project use?",
            project_id="proj-1",
        )
        assert resp.response_type in ("knowledge", "text")


class TestMaxIterations:
    """Agent respects the max iteration limit."""

    @pytest.mark.asyncio
    async def test_max_iterations_reached(self, agent, mock_llm, config):
        mock_llm.complete = AsyncMock(
            return_value=LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="tc-x",
                        name="query_database",
                        arguments={"question": "test"},
                    ),
                ],
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            )
        )

        with (
            patch.object(
                agent._orchestrator._sql,
                "run",
                new_callable=AsyncMock,
            ) as mock_sql_run,
            patch.object(
                agent._orchestrator,
                "_resolve_connection_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch.object(
                agent._orchestrator, "_build_table_map", new_callable=AsyncMock, return_value=""
            ),
        ):
            from app.agents.sql_agent import SQLAgentResult

            mock_sql_run.return_value = SQLAgentResult(
                status="no_result",
                error="No query generated",
            )

            resp = await agent.run(
                question="loop forever",
                project_id="proj-1",
                connection_config=config,
            )
        assert "maximum" in resp.answer.lower()


class TestErrorHandling:
    """Agent handles errors gracefully."""

    @pytest.mark.asyncio
    async def test_general_error_returns_error_response(self, agent, mock_llm):
        mock_llm.complete = AsyncMock(side_effect=RuntimeError("LLM provider down"))

        resp = await agent.run(
            question="Tell me something",
            project_id="proj-1",
        )
        assert resp.response_type == "error"
        assert "error" in resp.answer.lower()


class TestTokenUsageAccumulation:
    @pytest.mark.asyncio
    async def test_token_usage_sums_across_iterations(self, agent, mock_llm):
        call_count = 0

        async def complete_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="tc-1",
                            name="manage_rules",
                            arguments={"action": "create", "name": "test", "content": "test"},
                        ),
                    ],
                    usage={"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
                )
            return LLMResponse(
                content="No rules found.",
                tool_calls=[],
                usage={"prompt_tokens": 150, "completion_tokens": 30, "total_tokens": 180},
            )

        mock_llm.complete = AsyncMock(side_effect=complete_side_effect)

        with patch("app.models.base.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch(
                "app.services.membership_service.MembershipService.get_role",
                new_callable=AsyncMock,
                return_value="owner",
            ):
                with patch(
                    "app.services.rule_service.RuleService.create",
                    new_callable=AsyncMock,
                ) as mock_create:
                    mock_rule = MagicMock()
                    mock_rule.name = "test"
                    mock_rule.id = "r-1"
                    mock_rule.content = "test content"
                    mock_create.return_value = mock_rule

                    resp = await agent.run(
                        question="rules?",
                        project_id="proj-1",
                        user_id="user-1",
                    )
        assert resp.token_usage["total_tokens"] == 300


class TestAgentResponseStructure:
    """AgentResponse has all expected fields."""

    @pytest.mark.asyncio
    async def test_response_has_workflow_id(self, agent, mock_llm):
        mock_llm.complete = AsyncMock(
            return_value=LLMResponse(
                content="Hi!",
                tool_calls=[],
                usage={"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
            )
        )

        resp = await agent.run(question="Hello", project_id="proj-1")
        assert resp.workflow_id is not None

    @pytest.mark.asyncio
    async def test_response_has_tool_call_log(self, agent, mock_llm):
        mock_llm.complete = AsyncMock(
            return_value=LLMResponse(
                content="No tools needed.",
                tool_calls=[],
                usage={},
            )
        )

        resp = await agent.run(question="Hi", project_id="proj-1")
        assert isinstance(resp.tool_call_log, list)
