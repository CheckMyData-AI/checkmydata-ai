"""Tests for ConversationalAgent (backward-compatible wrapper).

These tests verify the end-to-end flow through the wrapper -> OrchestratorAgent
-> sub-agents pipeline.  We mock at the LLM level (mock_llm.complete) so the
tests verify the real orchestration logic.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.errors import AgentFatalError, AgentRetryableError
from app.connectors.base import ConnectionConfig
from app.core.agent import ConversationalAgent
from app.core.workflow_tracker import WorkflowTracker
from app.llm.base import LLMResponse, ToolCall
from app.llm.errors import (
    LLMAllProvidersFailedError,
    LLMAuthError,
    LLMConnectionError,
    LLMContentFilterError,
    LLMRateLimitError,
    LLMServerError,
    LLMTimeoutError,
    LLMTokenLimitError,
)


@pytest.fixture
def mock_tracker():
    t = MagicMock(spec=WorkflowTracker)
    t.begin = AsyncMock(return_value="wf-1")
    t.end = AsyncMock()
    t.emit = AsyncMock()
    t.has_ended = MagicMock(return_value=True)

    from contextlib import asynccontextmanager

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
                agent._orchestrator._ctx_loader,
                "resolve_connection_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch.object(
                agent._orchestrator._ctx_loader,
                "build_table_map",
                new_callable=AsyncMock,
                return_value="",
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
    """Agent respects the max iteration limit and uses adaptive step budget."""

    def _setup_always_tool_call(self, mock_llm):
        """Configure mock LLM to always return a tool call (never a final answer)."""
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

    @pytest.mark.asyncio
    async def test_max_iterations_reached(self, agent, mock_llm, config):
        self._setup_always_tool_call(mock_llm)

        from app.agents.sql_agent import SQLAgentResult

        with (
            patch.object(
                agent._orchestrator._sql,
                "run",
                new_callable=AsyncMock,
                return_value=SQLAgentResult(status="no_result", error="No query generated"),
            ),
            patch.object(
                agent._orchestrator._ctx_loader,
                "resolve_connection_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch.object(
                agent._orchestrator._ctx_loader,
                "build_table_map",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch("app.agents.orchestrator.settings") as mock_settings,
        ):
            mock_settings.max_orchestrator_iterations = 3
            mock_settings.max_simple_query_steps = 3
            mock_settings.orchestrator_wrap_up_steps = 1
            mock_settings.orchestrator_final_synthesis = False
            mock_settings.max_sub_agent_retries = 2
            mock_settings.max_context_tokens = 16000
            mock_settings.max_history_tokens = 4000
            mock_settings.schema_cache_ttl_seconds = 300
            mock_settings.agent_wall_clock_timeout_seconds = 600
            mock_settings.max_parallel_tool_calls = 3
            mock_settings.viz_timeout_seconds = 15

            resp = await agent.run(
                question="loop forever",
                project_id="proj-1",
                connection_config=config,
            )
        assert resp.response_type == "step_limit_reached"
        assert resp.steps_used == 3
        assert resp.steps_total == 3
        assert resp.continuation_context is not None

    @pytest.mark.asyncio
    async def test_final_synthesis_called_on_exhaustion(self, agent, mock_llm, config):
        """When synthesis is enabled, the orchestrator makes a final LLM call."""
        call_count = 0
        synthesis_content = "Here is the synthesized answer based on partial data."

        async def mock_complete(**kwargs):
            nonlocal call_count
            call_count += 1
            if kwargs.get("tools") is None:
                return LLMResponse(
                    content=synthesis_content,
                    tool_calls=[],
                    usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                )
            return LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id=f"tc-{call_count}", name="query_database", arguments={"question": "test"}
                    ),
                ],
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            )

        mock_llm.complete = AsyncMock(side_effect=mock_complete)

        from app.agents.sql_agent import SQLAgentResult

        with (
            patch.object(
                agent._orchestrator._sql,
                "run",
                new_callable=AsyncMock,
                return_value=SQLAgentResult(status="no_result", error="No query generated"),
            ),
            patch.object(
                agent._orchestrator._ctx_loader,
                "resolve_connection_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch.object(
                agent._orchestrator._ctx_loader,
                "build_table_map",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch("app.agents.orchestrator.settings") as mock_settings,
        ):
            mock_settings.max_orchestrator_iterations = 3
            mock_settings.max_simple_query_steps = 3
            mock_settings.orchestrator_wrap_up_steps = 1
            mock_settings.orchestrator_final_synthesis = True
            mock_settings.max_sub_agent_retries = 2
            mock_settings.max_context_tokens = 16000
            mock_settings.max_history_tokens = 4000
            mock_settings.schema_cache_ttl_seconds = 300
            mock_settings.agent_wall_clock_timeout_seconds = 600
            mock_settings.max_parallel_tool_calls = 3
            mock_settings.viz_timeout_seconds = 15

            resp = await agent.run(
                question="complex analysis",
                project_id="proj-1",
                connection_config=config,
            )
        assert synthesis_content in resp.answer

    @pytest.mark.asyncio
    async def test_final_synthesis_disabled_fallback(self, agent, mock_llm, config):
        """When synthesis is disabled, falls back to static partial text."""
        self._setup_always_tool_call(mock_llm)

        from app.agents.sql_agent import SQLAgentResult

        with (
            patch.object(
                agent._orchestrator._sql,
                "run",
                new_callable=AsyncMock,
                return_value=SQLAgentResult(status="no_result", error="No query generated"),
            ),
            patch.object(
                agent._orchestrator._ctx_loader,
                "resolve_connection_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch.object(
                agent._orchestrator._ctx_loader,
                "build_table_map",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch("app.agents.orchestrator.settings") as mock_settings,
        ):
            mock_settings.max_orchestrator_iterations = 3
            mock_settings.max_simple_query_steps = 3
            mock_settings.orchestrator_wrap_up_steps = 1
            mock_settings.orchestrator_final_synthesis = False
            mock_settings.max_sub_agent_retries = 2
            mock_settings.max_context_tokens = 16000
            mock_settings.max_history_tokens = 4000
            mock_settings.schema_cache_ttl_seconds = 300
            mock_settings.agent_wall_clock_timeout_seconds = 600
            mock_settings.max_parallel_tool_calls = 3
            mock_settings.viz_timeout_seconds = 15

            resp = await agent.run(
                question="loop forever",
                project_id="proj-1",
                connection_config=config,
            )
        assert "maximum" in resp.answer.lower()

    @pytest.mark.asyncio
    async def test_per_request_max_steps_override(self, agent, mock_llm, config):
        """Custom max_steps from the request overrides the global setting."""
        self._setup_always_tool_call(mock_llm)

        from app.agents.sql_agent import SQLAgentResult

        with (
            patch.object(
                agent._orchestrator._sql,
                "run",
                new_callable=AsyncMock,
                return_value=SQLAgentResult(status="no_result", error="No query generated"),
            ),
            patch.object(
                agent._orchestrator._ctx_loader,
                "resolve_connection_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch.object(
                agent._orchestrator._ctx_loader,
                "build_table_map",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch("app.agents.orchestrator.settings") as mock_settings,
        ):
            mock_settings.max_orchestrator_iterations = 100
            mock_settings.max_simple_query_steps = 4
            mock_settings.orchestrator_wrap_up_steps = 1
            mock_settings.orchestrator_final_synthesis = False
            mock_settings.max_sub_agent_retries = 2
            mock_settings.max_context_tokens = 16000
            mock_settings.max_history_tokens = 4000
            mock_settings.schema_cache_ttl_seconds = 300
            mock_settings.agent_wall_clock_timeout_seconds = 600
            mock_settings.max_parallel_tool_calls = 3
            mock_settings.viz_timeout_seconds = 15

            resp = await agent.run(
                question="loop forever",
                project_id="proj-1",
                connection_config=config,
                max_steps=2,
            )
        assert resp.steps_total == 2
        assert resp.steps_used == 2


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
        assert resp.error is not None
        assert "unexpected" in resp.answer.lower() or "error" in resp.answer.lower()

    @pytest.mark.asyncio
    async def test_llm_error_returns_friendly_message(self, agent, mock_llm):

        mock_llm.complete = AsyncMock(
            side_effect=LLMAllProvidersFailedError("all providers down"),
        )

        resp = await agent.run(
            question="Tell me something",
            project_id="proj-1",
        )
        assert resp.response_type == "error"
        assert "temporarily unavailable" in resp.answer.lower()


class TestTokenUsageAccumulation:
    @pytest.mark.asyncio
    async def test_token_usage_sums_across_iterations(self, agent, mock_llm):
        call_count = 0

        async def complete_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return LLMResponse(
                    content='{"intent": "mixed", "reason": "unclear"}',
                    usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                )
            if call_count == 2:
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


class TestOrchestratorErrorResilience:
    """Every LLM error type returns a friendly error response."""

    @pytest.mark.asyncio
    async def test_llm_rate_limit_error(self, agent, mock_llm):
        mock_llm.complete = AsyncMock(side_effect=LLMRateLimitError("rate limited"))
        resp = await agent.run(question="test", project_id="proj-1")
        assert resp.response_type == "error"
        assert "overloaded" in resp.answer.lower()

    @pytest.mark.asyncio
    async def test_llm_auth_error(self, agent, mock_llm):
        mock_llm.complete = AsyncMock(side_effect=LLMAuthError("bad key"))
        resp = await agent.run(question="test", project_id="proj-1")
        assert resp.response_type == "error"
        assert "configuration" in resp.answer.lower()

    @pytest.mark.asyncio
    async def test_llm_token_limit_error(self, agent, mock_llm):
        mock_llm.complete = AsyncMock(side_effect=LLMTokenLimitError("too many tokens"))
        resp = await agent.run(question="test", project_id="proj-1")
        assert resp.response_type in ("error", "text")
        answer_lower = resp.answer.lower()
        assert "too large" in answer_lower or "partial" in answer_lower

    @pytest.mark.asyncio
    async def test_llm_content_filter_error(self, agent, mock_llm):
        mock_llm.complete = AsyncMock(side_effect=LLMContentFilterError("blocked"))
        resp = await agent.run(question="test", project_id="proj-1")
        assert resp.response_type == "error"
        assert "content policy" in resp.answer.lower()

    @pytest.mark.asyncio
    async def test_llm_timeout_error(self, agent, mock_llm):
        mock_llm.complete = AsyncMock(side_effect=LLMTimeoutError("timed out"))
        resp = await agent.run(question="test", project_id="proj-1")
        assert resp.response_type == "error"
        assert "too long" in resp.answer.lower()

    @pytest.mark.asyncio
    async def test_llm_connection_error(self, agent, mock_llm):
        mock_llm.complete = AsyncMock(side_effect=LLMConnectionError("unreachable"))
        resp = await agent.run(question="test", project_id="proj-1")
        assert resp.response_type == "error"
        assert "could not reach" in resp.answer.lower()

    @pytest.mark.asyncio
    async def test_connection_refused_returns_db_error(self, agent, mock_llm):
        mock_llm.complete = AsyncMock(side_effect=RuntimeError("connection refused by host"))
        resp = await agent.run(question="test", project_id="proj-1")
        assert resp.response_type == "error"
        assert "database connection error" in resp.answer.lower()

    @pytest.mark.asyncio
    async def test_permission_denied_returns_permission_message(self, agent, mock_llm):
        mock_llm.complete = AsyncMock(side_effect=RuntimeError("access denied for user"))
        resp = await agent.run(question="test", project_id="proj-1")
        assert resp.response_type == "error"
        assert "permission" in resp.answer.lower()

    @pytest.mark.asyncio
    async def test_tracker_end_failure_does_not_crash(self, agent, mock_llm, mock_tracker):
        mock_llm.complete = AsyncMock(side_effect=RuntimeError("boom"))
        mock_tracker.end = AsyncMock(side_effect=RuntimeError("tracker broken"))

        resp = await agent.run(question="test", project_id="proj-1")
        assert resp.response_type == "error"
        assert resp.answer  # should still have a friendly message


class TestSubAgentErrorHandling:
    """Sub-agent handlers surface errors as tool results for the LLM."""

    @pytest.mark.asyncio
    async def test_sql_agent_retryable_error_retries(self, agent, mock_llm, config):
        call_count = 0

        async def complete_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return LLMResponse(
                    content='{"intent": "data_query", "reason": "db question"}',
                    usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                )
            if call_count == 2:
                return LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCall(id="tc-1", name="query_database", arguments={"question": "test"}),
                    ],
                    usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                )
            return LLMResponse(
                content="Query failed after retries.",
                tool_calls=[],
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            )

        mock_llm.complete = AsyncMock(side_effect=complete_side_effect)

        sql_call_count = 0

        from app.agents.sql_agent import SQLAgentResult

        async def sql_side_effect(*a, **kw):
            nonlocal sql_call_count
            sql_call_count += 1
            if sql_call_count == 1:
                raise AgentRetryableError("temporary issue")
            return SQLAgentResult(status="success", query="SELECT 1")

        with (
            patch.object(
                agent._orchestrator._sql,
                "run",
                new_callable=AsyncMock,
                side_effect=sql_side_effect,
            ),
            patch.object(
                agent._orchestrator._ctx_loader,
                "resolve_connection_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch.object(
                agent._orchestrator._ctx_loader,
                "build_table_map",
                new_callable=AsyncMock,
                return_value="",
            ),
        ):
            resp = await agent.run(
                question="test",
                project_id="proj-1",
                connection_config=config,
            )
        assert sql_call_count >= 2
        assert resp.response_type != "error"

    @pytest.mark.asyncio
    async def test_sql_agent_fatal_error_returns_error_string(self, agent, mock_llm, config):
        call_count = 0

        async def complete_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCall(id="tc-1", name="query_database", arguments={"question": "test"}),
                    ],
                    usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                )
            return LLMResponse(
                content="The query failed.",
                tool_calls=[],
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            )

        mock_llm.complete = AsyncMock(side_effect=complete_side_effect)

        with (
            patch.object(
                agent._orchestrator._sql,
                "run",
                new_callable=AsyncMock,
                side_effect=AgentFatalError("schema not found"),
            ),
            patch.object(
                agent._orchestrator._ctx_loader,
                "resolve_connection_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch.object(
                agent._orchestrator._ctx_loader,
                "build_table_map",
                new_callable=AsyncMock,
                return_value="",
            ),
        ):
            resp = await agent.run(
                question="test",
                project_id="proj-1",
                connection_config=config,
            )
        assert "The query failed" in resp.answer or "failed" in resp.answer.lower()

    @pytest.mark.asyncio
    async def test_sql_agent_max_retries_exhausted(self, agent, mock_llm, config):
        call_count = 0

        async def complete_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCall(id="tc-1", name="query_database", arguments={"question": "test"}),
                    ],
                    usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                )
            return LLMResponse(
                content="SQL query failed after retries.",
                tool_calls=[],
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            )

        mock_llm.complete = AsyncMock(side_effect=complete_side_effect)

        with (
            patch.object(
                agent._orchestrator._sql,
                "run",
                new_callable=AsyncMock,
                side_effect=AgentRetryableError("still failing"),
            ),
            patch.object(
                agent._orchestrator._ctx_loader,
                "resolve_connection_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch.object(
                agent._orchestrator._ctx_loader,
                "build_table_map",
                new_callable=AsyncMock,
                return_value="",
            ),
        ):
            resp = await agent.run(
                question="test",
                project_id="proj-1",
                connection_config=config,
            )
        assert "failed" in resp.answer.lower()

    @pytest.mark.asyncio
    async def test_manage_rules_db_error_returns_error_string(self, agent, mock_llm):
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
                            arguments={"action": "create", "name": "r1", "content": "rule text"},
                        ),
                    ],
                    usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                )
            return LLMResponse(
                content="Failed to manage rules.",
                tool_calls=[],
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            )

        mock_llm.complete = AsyncMock(side_effect=complete_side_effect)

        with patch("app.models.base.async_session_factory") as mock_sf:
            mock_sf.return_value.__aenter__ = AsyncMock(
                side_effect=RuntimeError("DB connection lost")
            )
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)

            resp = await agent.run(question="create a rule", project_id="proj-1", user_id="user-1")

        assert resp.response_type != "error" or "error" in resp.answer.lower()


class TestLLMCallWithRetry:
    """_llm_call_with_retry retries transient errors and re-raises on final failure."""

    @pytest.mark.asyncio
    async def test_retries_on_rate_limit_then_succeeds(self, agent, mock_llm):
        calls = []

        async def side_effect(**kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise LLMRateLimitError("rate limited", retry_after=0.01)
            return LLMResponse(
                content="Success after retry",
                tool_calls=[],
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            )

        mock_llm.complete = AsyncMock(side_effect=side_effect)

        resp = await agent.run(question="test", project_id="proj-1")
        assert resp.response_type == "text"
        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_retries_on_server_error_then_succeeds(self, agent, mock_llm):
        calls = []

        async def side_effect(**kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise LLMServerError("500 error", retry_after=0.01)
            return LLMResponse(
                content="Recovered",
                tool_calls=[],
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            )

        mock_llm.complete = AsyncMock(side_effect=side_effect)

        resp = await agent.run(question="test", project_id="proj-1")
        assert resp.response_type == "text"
        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_all_retries_exhausted_raises(self, agent, mock_llm):
        mock_llm.complete = AsyncMock(
            side_effect=LLMRateLimitError("rate limited forever", retry_after=0.01)
        )

        resp = await agent.run(question="test", project_id="proj-1")
        assert resp.response_type == "error"
        assert "overloaded" in resp.answer.lower()

    @pytest.mark.asyncio
    async def test_non_retryable_error_not_retried(self, agent, mock_llm):
        mock_llm.complete = AsyncMock(side_effect=LLMAuthError("bad key"))

        resp = await agent.run(question="test", project_id="proj-1")
        assert resp.response_type == "error"
        # Classification call fails, falls back to MIXED, full pipeline also fails = 2 calls
        assert mock_llm.complete.call_count <= 2


class TestClarificationFlow:
    """LLM calling ask_user returns a clarification_request response."""

    @pytest.mark.asyncio
    async def test_ask_user_tool_returns_clarification_response(self, agent, mock_llm):
        mock_llm.complete = AsyncMock(
            return_value=LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="tc-ask",
                        name="ask_user",
                        arguments={
                            "question": "Which table?",
                            "question_type": "free_text",
                        },
                    ),
                ],
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            )
        )

        resp = await agent.run(question="show me data", project_id="proj-1")
        assert resp.response_type == "clarification_request"
        assert "Which table?" in resp.answer

    @pytest.mark.asyncio
    async def test_clarification_data_payload_is_populated(self, agent, mock_llm):
        """Verify the structured clarification_data dict reaches the response."""
        mock_llm.complete = AsyncMock(
            return_value=LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="tc-ask-mc",
                        name="ask_user",
                        arguments={
                            "question": "Which currency?",
                            "question_type": "multiple_choice",
                            "options": "USD, EUR, GBP",
                            "context": "Revenue can be in different currencies",
                        },
                    ),
                ],
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            )
        )

        resp = await agent.run(question="show me revenue", project_id="proj-1")
        assert resp.response_type == "clarification_request"
        assert resp.clarification_data is not None
        assert resp.clarification_data["question"] == "Which currency?"
        assert resp.clarification_data["question_type"] == "multiple_choice"
        assert resp.clarification_data["options"] == ["USD", "EUR", "GBP"]
        assert resp.clarification_data["context"] == "Revenue can be in different currencies"

    @pytest.mark.asyncio
    async def test_ask_user_available_without_db_connection(self, agent, mock_llm):
        """ask_user tool must be available even when no DB is connected."""
        mock_llm.complete = AsyncMock(
            return_value=LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="tc-ask-kb",
                        name="ask_user",
                        arguments={
                            "question": "Which module are you asking about?",
                            "question_type": "free_text",
                        },
                    ),
                ],
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            )
        )

        resp = await agent.run(
            question="how does authentication work?",
            project_id="proj-1",
            connection_config=None,
        )
        assert resp.response_type == "clarification_request"
        assert resp.clarification_data is not None
        assert resp.clarification_data["question"] == "Which module are you asking about?"
        assert resp.clarification_data["question_type"] == "free_text"

    @pytest.mark.asyncio
    async def test_yes_no_clarification_has_no_options(self, agent, mock_llm):
        """yes_no type should work and options list should be empty."""
        mock_llm.complete = AsyncMock(
            return_value=LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="tc-yn",
                        name="ask_user",
                        arguments={
                            "question": "Is the amount in cents?",
                            "question_type": "yes_no",
                        },
                    ),
                ],
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            )
        )

        resp = await agent.run(question="show amounts", project_id="proj-1")
        assert resp.response_type == "clarification_request"
        assert resp.clarification_data is not None
        assert resp.clarification_data["question_type"] == "yes_no"
        assert resp.clarification_data["options"] == []


class TestAskUserToolAvailability:
    """Verify ask_user tool is always in the orchestrator tool set."""

    def test_ask_user_present_with_connection(self):
        from app.agents.tools.orchestrator_tools import get_orchestrator_tools

        tools = get_orchestrator_tools(has_connection=True)
        tool_names = [t.name for t in tools]
        assert "ask_user" in tool_names

    def test_ask_user_present_without_connection(self):
        from app.agents.tools.orchestrator_tools import get_orchestrator_tools

        tools = get_orchestrator_tools(has_connection=False)
        tool_names = [t.name for t in tools]
        assert "ask_user" in tool_names

    def test_ask_user_present_with_knowledge_base_only(self):
        from app.agents.tools.orchestrator_tools import get_orchestrator_tools

        tools = get_orchestrator_tools(has_connection=False, has_knowledge_base=True)
        tool_names = [t.name for t in tools]
        assert "ask_user" in tool_names
        assert "search_codebase" in tool_names

    def test_ask_user_present_with_no_capabilities(self):
        from app.agents.tools.orchestrator_tools import get_orchestrator_tools

        tools = get_orchestrator_tools(
            has_connection=False, has_knowledge_base=False, has_mcp_sources=False
        )
        tool_names = [t.name for t in tools]
        assert "ask_user" in tool_names


class TestVizFallback:
    """Viz agent failure falls back to table visualization."""

    @pytest.mark.asyncio
    async def test_viz_failure_falls_back_to_table(self, agent, mock_llm, config):
        from app.agents.sql_agent import SQLAgentResult
        from app.connectors.base import QueryResult

        call_count = 0

        async def complete_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return LLMResponse(
                    content='{"intent": "data_query", "reason": "db test"}',
                    usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                )
            if call_count == 2:
                return LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCall(id="tc-1", name="query_database", arguments={"question": "test"}),
                    ],
                    usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                )
            return LLMResponse(
                content="Here are the results.",
                tool_calls=[],
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            )

        mock_llm.complete = AsyncMock(side_effect=complete_side_effect)

        qr = QueryResult(
            columns=["id", "name"],
            rows=[[1, "Alice"], [2, "Bob"]],
            row_count=2,
            execution_time_ms=10.0,
        )

        with (
            patch.object(
                agent._orchestrator._sql,
                "run",
                new_callable=AsyncMock,
                return_value=SQLAgentResult(status="success", query="SELECT 1", results=qr),
            ),
            patch.object(
                agent._orchestrator._viz,
                "run",
                new_callable=AsyncMock,
                side_effect=RuntimeError("viz exploded"),
            ),
            patch.object(
                agent._orchestrator._ctx_loader,
                "resolve_connection_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch.object(
                agent._orchestrator._ctx_loader,
                "build_table_map",
                new_callable=AsyncMock,
                return_value="",
            ),
        ):
            resp = await agent.run(
                question="test",
                project_id="proj-1",
                connection_config=config,
            )

        assert resp.viz_type == "table"
        assert resp.response_type == "sql_result"


class TestThinkingEvents:
    """Verify that orchestrator emits 'thinking' tracker events."""

    @pytest.mark.asyncio
    async def test_thinking_emitted_on_tool_call(
        self,
        agent,
        mock_llm,
        mock_tracker,
        config,
    ):
        """When LLM decides to call a tool, a thinking event is emitted."""
        call_count = 0

        async def complete_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return LLMResponse(
                    content='{"intent": "data_query", "reason": "find users"}',
                    usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                )
            if call_count == 2:
                return LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="tc-1",
                            name="query_database",
                            arguments={"question": "find users"},
                        ),
                    ],
                    usage={
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                    },
                )
            return LLMResponse(
                content="Done",
                tool_calls=[],
                usage={
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            )

        mock_llm.complete = AsyncMock(side_effect=complete_side_effect)

        from app.agents.sql_agent import SQLAgentResult

        with (
            patch.object(
                agent._orchestrator._sql,
                "run",
                new_callable=AsyncMock,
                return_value=SQLAgentResult(status="success"),
            ),
            patch.object(
                agent._orchestrator._ctx_loader,
                "resolve_connection_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch.object(
                agent._orchestrator._ctx_loader,
                "build_table_map",
                new_callable=AsyncMock,
                return_value="",
            ),
        ):
            await agent.run(
                question="find users",
                project_id="proj-1",
                connection_config=config,
            )

        thinking_calls = [c for c in mock_tracker.emit.call_args_list if c.args[1] == "thinking"]
        assert len(thinking_calls) >= 2
        details = [c.args[3] for c in thinking_calls]
        assert any("Analyzing" in d for d in details)
        assert any("SQL Agent" in d for d in details)

    @pytest.mark.asyncio
    async def test_thinking_emitted_on_final_answer(
        self,
        agent,
        mock_llm,
        mock_tracker,
    ):
        """A thinking event fires when the LLM produces a final answer."""
        mock_llm.complete = AsyncMock(
            return_value=LLMResponse(
                content="Hello!",
                tool_calls=[],
                usage={
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            )
        )
        await agent.run(
            question="Hi",
            project_id="proj-1",
            connection_config=None,
        )

        thinking_calls = [c for c in mock_tracker.emit.call_args_list if c.args[1] == "thinking"]
        assert len(thinking_calls) >= 1
        details = [c.args[3] for c in thinking_calls]
        assert any("Composing" in d or "Analyzing" in d for d in details)

    @pytest.mark.asyncio
    async def test_thinking_includes_tool_name(
        self,
        agent,
        mock_llm,
        mock_tracker,
        config,
    ):
        """Thinking detail mentions the tool name being called."""
        call_count = 0

        async def complete_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return LLMResponse(
                    content='{"intent": "knowledge_query", "reason": "code question"}',
                    usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                )
            if call_count == 2:
                return LLMResponse(
                    content="Let me search",
                    tool_calls=[
                        ToolCall(
                            id="tc-1",
                            name="search_codebase",
                            arguments={
                                "question": "what framework",
                            },
                        ),
                    ],
                    usage={
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                    },
                )
            return LLMResponse(
                content="It uses FastAPI",
                tool_calls=[],
                usage={
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            )

        mock_llm.complete = AsyncMock(side_effect=complete_side_effect)

        from app.agents.knowledge_agent import KnowledgeResult

        collection = MagicMock()
        collection.count = MagicMock(return_value=5)

        with (
            patch.object(
                agent._orchestrator._knowledge,
                "run",
                new_callable=AsyncMock,
                return_value=KnowledgeResult(
                    answer="FastAPI",
                    status="success",
                ),
            ),
            patch.object(
                agent._orchestrator._vector_store,
                "get_or_create_collection",
                return_value=collection,
            ),
        ):
            await agent.run(
                question="what framework?",
                project_id="proj-1",
                connection_config=None,
            )

        thinking_calls = [c for c in mock_tracker.emit.call_args_list if c.args[1] == "thinking"]
        details = [c.args[3] for c in thinking_calls]
        assert any("Knowledge Agent" in d for d in details)
