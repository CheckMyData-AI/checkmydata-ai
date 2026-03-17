from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.connectors.base import ConnectionConfig, QueryResult
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
        resp = await agent.run(
            question="Thanks for the earlier results",
            project_id="proj-1",
            connection_config=config,
        )
        assert resp.response_type == "text"
        assert "help" in resp.answer.lower()


class TestKnowledgeSearch:
    """Agent calls search_knowledge for project questions."""

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
            if call_count == 1:
                return LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="tc-1",
                            name="search_knowledge",
                            arguments={"query": "project database", "max_results": 3},
                        ),
                    ],
                    usage={"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70},
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
        assert resp.response_type == "knowledge"
        assert len(resp.knowledge_sources) > 0
        assert resp.knowledge_sources[0].source_path == "README.md"


class TestSQLQueryFlow:
    """Agent calls execute_query for data questions."""

    @pytest.mark.asyncio
    @patch("app.core.tool_executor.get_connector")
    async def test_sql_query_flow(self, mock_get_connector, agent, mock_llm, config):
        mock_connector = MagicMock()
        mock_connector.connect = AsyncMock()
        mock_connector.introspect_schema = AsyncMock(
            return_value=MagicMock(
                tables=[],
                db_type="postgres",
                db_name="testdb",
            )
        )
        mock_get_connector.return_value = mock_connector

        from app.core.query_validation import ValidationLoopResult

        query_result = QueryResult(
            columns=["count"],
            rows=[[42]],
            row_count=1,
            execution_time_ms=5.0,
        )

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
                            name="execute_query",
                            arguments={
                                "query": "SELECT COUNT(*) FROM users",
                                "explanation": "Count users",
                            },
                        ),
                    ],
                    usage={"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130},
                )
            return LLMResponse(
                content="There are 42 users in the database.",
                tool_calls=[],
                usage={"prompt_tokens": 150, "completion_tokens": 20, "total_tokens": 170},
            )

        mock_llm.complete = AsyncMock(side_effect=complete_side_effect)

        with patch("app.core.tool_executor.ValidationLoop") as mock_vl_cls:
            mock_vl_instance = MagicMock()
            mock_vl_instance.execute = AsyncMock(
                return_value=ValidationLoopResult(
                    success=True,
                    query="SELECT COUNT(*) FROM users",
                    explanation="Count users",
                    results=query_result,
                    attempts=[],
                    total_attempts=1,
                )
            )
            mock_vl_cls.return_value = mock_vl_instance

            with patch.object(agent, "_query_builder") as mock_qb:
                mock_qb.interpret_results = AsyncMock(
                    return_value={
                        "viz_type": "number",
                        "config": {},
                        "summary": "42 users",
                        "usage": {},
                    }
                )

                resp = await agent.run(
                    question="How many users?",
                    project_id="proj-1",
                    connection_config=config,
                )

        assert resp.response_type == "sql_result"
        assert resp.query == "SELECT COUNT(*) FROM users"
        assert resp.results is not None
        assert resp.results.row_count == 1


class TestMaxIterations:
    """Agent respects the max iteration limit."""

    @pytest.mark.asyncio
    async def test_max_iterations_reached(self, agent, mock_llm, config):
        mock_llm.complete = AsyncMock(
            return_value=LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(id="tc-x", name="get_custom_rules", arguments={}),
                ],
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            )
        )

        resp = await agent.run(
            question="loop forever",
            project_id="proj-1",
            connection_config=config,
        )
        assert "maximum" in resp.answer.lower()
        assert mock_llm.complete.call_count == 5  # MAX_TOOL_ITERATIONS


class TestErrorHandling:
    """Agent handles tool execution errors gracefully."""

    @pytest.mark.asyncio
    async def test_tool_error_propagates_in_message(self, agent, mock_llm, mock_vector_store):
        collection = MagicMock()
        collection.count = MagicMock(return_value=10)
        mock_vector_store.get_or_create_collection = MagicMock(return_value=collection)

        mock_vector_store.query = MagicMock(side_effect=RuntimeError("ChromaDB down"))

        call_count = 0

        async def complete_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCall(id="tc-1", name="search_knowledge", arguments={"query": "test"}),
                    ],
                    usage={},
                )
            return LLMResponse(
                content="I encountered an error searching the knowledge base.",
                tool_calls=[],
                usage={},
            )

        mock_llm.complete = AsyncMock(side_effect=complete_side_effect)

        resp = await agent.run(
            question="Tell me about the project",
            project_id="proj-1",
        )
        assert "error" in resp.answer.lower()


class TestToolCallsPropagation:
    """Agent includes tool_calls on assistant messages sent back to the LLM."""

    @pytest.mark.asyncio
    async def test_tool_calls_included_in_assistant_message(
        self, agent, mock_llm, mock_vector_store,
    ):
        collection = MagicMock()
        collection.count = MagicMock(return_value=10)
        mock_vector_store.get_or_create_collection = MagicMock(return_value=collection)
        mock_vector_store.query = MagicMock(return_value=[
            {
                "document": "test doc",
                "metadata": {"source_path": "test.py", "doc_type": "code"},
                "distance": 0.1,
            },
        ])

        tool_call = ToolCall(id="tc-1", name="search_knowledge", arguments={"query": "test"})
        call_count = 0

        async def complete_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return LLMResponse(
                    content="",
                    tool_calls=[tool_call],
                    usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                )
            messages = kwargs.get("messages", [])
            assistant_msgs = [m for m in messages if m.role == "assistant"]
            assert len(assistant_msgs) == 1
            assert assistant_msgs[0].tool_calls is not None
            assert len(assistant_msgs[0].tool_calls) == 1
            assert assistant_msgs[0].tool_calls[0].id == "tc-1"
            assert assistant_msgs[0].tool_calls[0].name == "search_knowledge"

            return LLMResponse(content="Done.", tool_calls=[], usage={})

        mock_llm.complete = AsyncMock(side_effect=complete_side_effect)

        resp = await agent.run(question="test", project_id="proj-1")
        assert call_count == 2
        assert resp.answer == "Done."


class TestSqlConfigForwarding:
    """Agent forwards sql_provider/sql_model to ToolExecutor separately from agent model."""

    @pytest.mark.asyncio
    async def test_sql_config_passed_to_tool_executor(self, agent, mock_llm):
        mock_llm.complete = AsyncMock(
            return_value=LLMResponse(
                content="Done.",
                tool_calls=[],
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            )
        )
        from unittest.mock import patch as _patch

        with _patch("app.core.agent.ToolExecutor") as mock_te_cls:
            mock_executor = MagicMock()
            mock_executor.ctx = MagicMock(
                last_query=None,
                last_query_result=None,
                last_query_explanation=None,
                rag_sources=[],
                total_token_usage={
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
            )
            mock_te_cls.return_value = mock_executor

            await agent.run(
                question="Hi",
                project_id="proj-1",
                preferred_provider="openai",
                model="gpt-4o",
                sql_provider="anthropic",
                sql_model="claude-3-opus",
            )

            init_kwargs = mock_te_cls.call_args
            assert init_kwargs.kwargs["preferred_provider"] == "openai"
            assert init_kwargs.kwargs["model"] == "gpt-4o"
            assert init_kwargs.kwargs["sql_provider"] == "anthropic"
            assert init_kwargs.kwargs["sql_model"] == "claude-3-opus"


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
                    tool_calls=[ToolCall(id="tc-1", name="get_custom_rules", arguments={})],
                    usage={"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
                )
            return LLMResponse(
                content="No rules found.",
                tool_calls=[],
                usage={"prompt_tokens": 150, "completion_tokens": 30, "total_tokens": 180},
            )

        mock_llm.complete = AsyncMock(side_effect=complete_side_effect)

        resp = await agent.run(question="rules?", project_id="proj-1")
        assert resp.token_usage["total_tokens"] == 300
