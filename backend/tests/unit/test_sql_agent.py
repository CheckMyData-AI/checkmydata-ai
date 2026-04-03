"""Comprehensive unit tests for SQLAgent."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.base import AgentContext
from app.agents.errors import AgentFatalError
from app.agents.sql_agent import SQLAgent, SQLAgentResult
from app.connectors.base import ColumnInfo, ConnectionConfig, QueryResult, SchemaInfo, TableInfo
from app.core.query_validation import ValidationLoopResult
from app.core.workflow_tracker import WorkflowTracker
from app.llm.base import LLMResponse, ToolCall

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
    return router


@pytest.fixture
def mock_vector_store():
    vs = MagicMock()
    vs.query = MagicMock(return_value=[])
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
        connection_id="conn-1",
    )


@pytest.fixture
def agent(mock_llm, mock_vector_store, mock_custom_rules):
    return SQLAgent(
        llm_router=mock_llm,
        vector_store=mock_vector_store,
        rules_engine=mock_custom_rules,
    )


@pytest.fixture
def context(config, mock_llm, mock_tracker):
    return AgentContext(
        project_id="proj-1",
        connection_config=config,
        user_question="Show me all users",
        chat_history=[],
        llm_router=mock_llm,
        tracker=mock_tracker,
        workflow_id="wf-1",
    )


@pytest.fixture
def context_no_conn(mock_llm, mock_tracker):
    return AgentContext(
        project_id="proj-1",
        connection_config=None,
        user_question="Hello",
        chat_history=[],
        llm_router=mock_llm,
        tracker=mock_tracker,
        workflow_id="wf-1",
    )


def _stub_run_preamble(agent):
    """Patch the async helpers called at the top of run() so they don't hit the DB."""
    agent._has_db_index = AsyncMock(return_value=False)
    agent._is_db_index_stale = AsyncMock(return_value=False)
    agent._has_code_db_sync = AsyncMock(return_value=False)
    agent._has_learnings = AsyncMock(return_value=False)
    agent._build_table_map = AsyncMock(return_value="")
    agent._load_learnings_prompt = AsyncMock(return_value="")


def _make_llm_response(content="", tool_calls=None, usage=None):
    return LLMResponse(
        content=content,
        tool_calls=tool_calls or [],
        usage=usage or {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSQLAgent:
    # 1
    def test_name_property(self, agent):
        assert agent.name == "sql"

    # 2
    @pytest.mark.asyncio
    async def test_no_connection_config_raises(self, agent, context_no_conn):
        with pytest.raises(AgentFatalError, match="No database connection"):
            await agent.run(context_no_conn)

    # 3
    @pytest.mark.asyncio
    async def test_text_response_no_tools(self, agent, mock_llm, context):
        _stub_run_preamble(agent)
        mock_llm.complete = AsyncMock(
            return_value=_make_llm_response(content="I cannot build a query for that.")
        )

        result = await agent.run(context)
        assert isinstance(result, SQLAgentResult)
        assert result.status == "no_result"
        assert result.query is None

    # 4
    @pytest.mark.asyncio
    async def test_execute_query_success(self, agent, mock_llm, context):
        _stub_run_preamble(agent)

        qr = QueryResult(
            columns=["id", "name"],
            rows=[[1, "Alice"], [2, "Bob"]],
            row_count=2,
            execution_time_ms=5.0,
        )
        _loop_result = ValidationLoopResult(
            success=True,
            query="SELECT id, name FROM users",
            explanation="Fetch all users",
            results=qr,
            attempts=[],
            total_attempts=1,
        )

        call_count = 0

        async def complete_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_llm_response(
                    tool_calls=[
                        ToolCall(
                            id="tc-1",
                            name="execute_query",
                            arguments={
                                "query": "SELECT id, name FROM users",
                                "explanation": "Fetch all users",
                            },
                        ),
                    ],
                )
            return _make_llm_response(content="Here are your results.")

        mock_llm.complete = AsyncMock(side_effect=complete_side_effect)

        async def fake_execute(*args, **kwargs):
            run_state = kwargs.get("run_state", {})
            run_state["last_query"] = "SELECT id, name FROM users"
            run_state["last_explanation"] = "Fetch all users"
            run_state["last_result"] = qr
            return "Columns: id, name\nTotal rows: 2"

        with patch.object(agent, "_handle_execute_query", side_effect=fake_execute):
            result = await agent.run(context)

        assert result.status == "success"
        assert result.query == "SELECT id, name FROM users"
        assert result.results is qr

    # 5
    @pytest.mark.asyncio
    async def test_execute_query_failure(self, agent, mock_llm, context):
        _stub_run_preamble(agent)

        err_qr = QueryResult(columns=[], rows=[], row_count=0, error="relation does not exist")

        call_count = 0

        async def complete_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_llm_response(
                    tool_calls=[
                        ToolCall(
                            id="tc-1",
                            name="execute_query",
                            arguments={"query": "SELECT * FROM nonexistent", "explanation": "bad"},
                        ),
                    ],
                )
            return _make_llm_response(content="Query failed.")

        mock_llm.complete = AsyncMock(side_effect=complete_side_effect)

        async def fake_execute(*args, **kwargs):
            run_state = kwargs.get("run_state", {})
            run_state["last_query"] = "SELECT * FROM nonexistent"
            run_state["last_explanation"] = "bad"
            run_state["last_result"] = err_qr
            return "Query failed after 3 attempt(s): relation does not exist"

        with patch.object(agent, "_handle_execute_query", side_effect=fake_execute):
            result = await agent.run(context)

        assert result.status == "error"
        assert result.error == "relation does not exist"

    # 6
    @pytest.mark.asyncio
    async def test_get_schema_info_overview(self, agent, context):
        schema = SchemaInfo(
            tables=[
                TableInfo(
                    name="users", columns=[ColumnInfo(name="id", data_type="int")], row_count=100
                ),
                TableInfo(name="orders", columns=[], row_count=500),
            ],
            db_type="postgres",
            db_name="testdb",
        )
        agent._get_cached_schema = AsyncMock(return_value=schema)

        result_text = await agent._handle_get_schema_info({"scope": "overview"}, context, "wf-1")
        assert "users" in result_text
        assert "orders" in result_text
        assert "testdb" in result_text

    # 7
    @pytest.mark.asyncio
    async def test_get_schema_info_table_detail(self, agent, context):
        schema = SchemaInfo(
            tables=[
                TableInfo(
                    name="users",
                    columns=[
                        ColumnInfo(
                            name="id", data_type="int", is_primary_key=True, is_nullable=False
                        ),
                        ColumnInfo(name="email", data_type="varchar(255)"),
                    ],
                    row_count=100,
                ),
            ],
            db_type="postgres",
            db_name="testdb",
        )
        agent._get_cached_schema = AsyncMock(return_value=schema)

        result_text = await agent._handle_get_schema_info(
            {"scope": "table_detail", "table_name": "users"}, context, "wf-1"
        )
        assert "users" in result_text
        assert "email" in result_text
        assert "PK" in result_text

    # 8
    @pytest.mark.asyncio
    async def test_get_custom_rules(self, agent, mock_custom_rules, context):
        mock_custom_rules.rules_to_context.return_value = "Always use LEFT JOIN for orders."

        result_text = await agent._handle_get_custom_rules({}, context, "wf-1")
        assert "LEFT JOIN" in result_text

    # 9
    @pytest.mark.asyncio
    async def test_get_db_index(self, agent, context, config):
        mock_svc = MagicMock()
        mock_svc.get_index = AsyncMock(return_value=["entry1"])
        mock_svc.get_summary = AsyncMock(return_value=None)
        mock_svc.index_to_prompt_context = MagicMock(return_value="DB index overview")

        mock_session = AsyncMock()

        with (
            patch("app.models.base.async_session_factory") as mock_sf,
            patch("app.services.db_index_service.DbIndexService", return_value=mock_svc),
        ):
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)

            result_text = await agent._handle_get_db_index({"scope": "overview"}, context, "wf-1")

        assert result_text == "DB index overview"

    # 10
    @pytest.mark.asyncio
    async def test_get_sync_context(self, agent, context, config):
        mock_svc = MagicMock()
        mock_svc.get_sync = AsyncMock(return_value=["sync1"])
        mock_svc.get_summary = AsyncMock(return_value=None)
        mock_svc.sync_to_prompt_context = MagicMock(return_value="Sync context overview")

        mock_session = AsyncMock()

        with (
            patch("app.models.base.async_session_factory") as mock_sf,
            patch("app.services.code_db_sync_service.CodeDbSyncService", return_value=mock_svc),
        ):
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)

            result_text = await agent._handle_get_sync_context(
                {"scope": "overview"}, context, "wf-1"
            )

        assert result_text == "Sync context overview"

    # 11
    @pytest.mark.asyncio
    async def test_get_query_context(self, agent, context, config):
        agent._build_query_context = AsyncMock(return_value="## Query Context\n\nTable: users")

        result_text = await agent._handle_get_query_context(
            {"question": "Show users", "table_names": "users"}, context, "wf-1"
        )
        assert "Query Context" in result_text
        agent._build_query_context.assert_awaited_once()

    # 12
    @pytest.mark.asyncio
    async def test_get_agent_learnings(self, agent, context, config):
        mock_learning = MagicMock()
        mock_learning.category = "naming"
        mock_learning.lesson = "Column 'amt' stores cents, divide by 100"
        mock_learning.confidence = 0.9
        mock_learning.subject = "orders"

        mock_svc = MagicMock()
        mock_svc.get_learnings = AsyncMock(return_value=[mock_learning])

        mock_session = AsyncMock()

        with (
            patch("app.models.base.async_session_factory") as mock_sf,
            patch(
                "app.services.agent_learning_service.AgentLearningService", return_value=mock_svc
            ),
        ):
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch(
                "app.services.agent_learning_service.CATEGORY_LABELS",
                {"naming": "Naming Conventions"},
            ):
                result_text = await agent._handle_get_agent_learnings(
                    {"scope": "all"}, context, "wf-1"
                )

        assert "cents" in result_text
        assert "90%" in result_text

    # 13
    @pytest.mark.asyncio
    async def test_record_learning(self, agent, context, config):
        mock_entry = MagicMock()
        mock_entry.confidence = 0.8

        mock_svc = MagicMock()
        mock_svc.create_learning = AsyncMock(return_value=mock_entry)

        mock_session = AsyncMock()

        with (
            patch("app.models.base.async_session_factory") as mock_sf,
            patch(
                "app.services.agent_learning_service.AgentLearningService", return_value=mock_svc
            ),
        ):
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)

            result_text = await agent._handle_record_learning(
                {"category": "naming", "subject": "orders", "lesson": "amt is in cents"},
                context,
                "wf-1",
            )

        assert "Learning recorded successfully" in result_text
        assert "naming" in result_text
        mock_session.commit.assert_awaited_once()

    # 14
    @pytest.mark.asyncio
    async def test_unknown_tool(self, agent, context):
        tc = ToolCall(id="tc-u", name="nonexistent_tool", arguments={})
        result_text = await agent._dispatch_tool(tc, context, "wf-1")
        assert "unknown tool" in result_text.lower()
        assert "nonexistent_tool" in result_text

    # 15
    @pytest.mark.asyncio
    async def test_tool_exception(self, agent, context):
        agent._handle_get_schema_info = AsyncMock(side_effect=RuntimeError("DB down"))

        tc = ToolCall(id="tc-e", name="get_schema_info", arguments={"scope": "overview"})
        result_text = await agent._dispatch_tool(tc, context, "wf-1")
        assert "Error executing get_schema_info" in result_text
        assert "DB down" in result_text

    # 16
    @pytest.mark.asyncio
    async def test_max_iterations(self, agent, mock_llm, context):
        _stub_run_preamble(agent)

        mock_llm.complete = AsyncMock(
            return_value=_make_llm_response(
                content="partial",
                tool_calls=[
                    ToolCall(id="tc-loop", name="get_schema_info", arguments={"scope": "overview"}),
                ],
            )
        )

        agent._handle_get_schema_info = AsyncMock(return_value="schema overview text")

        result = await agent.run(context)

        from app.config import settings

        assert mock_llm.complete.call_count == settings.max_sql_iterations
        assert result.status == "no_result"

    # 17
    @pytest.mark.asyncio
    async def test_viz_suggestion_in_result(self, agent, mock_llm, context):
        _stub_run_preamble(agent)

        qr = QueryResult(
            columns=["month", "revenue"],
            rows=[["Jan", 1000], ["Feb", 1500]],
            row_count=2,
            execution_time_ms=3.0,
        )

        call_count = 0

        async def complete_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_llm_response(
                    tool_calls=[
                        ToolCall(
                            id="tc-q",
                            name="execute_query",
                            arguments={
                                "query": "SELECT month, revenue FROM sales",
                                "explanation": "Monthly revenue",
                            },
                        ),
                    ],
                )
            return _make_llm_response(content="Here is the revenue data.")

        mock_llm.complete = AsyncMock(side_effect=complete_side_effect)

        async def fake_execute(*args, **kwargs):
            run_state = kwargs.get("run_state", {})
            run_state["last_query"] = "SELECT month, revenue FROM sales"
            run_state["last_explanation"] = "Monthly revenue"
            run_state["last_result"] = qr
            return "Columns: month, revenue\nTotal rows: 2"

        with patch.object(agent, "_handle_execute_query", side_effect=fake_execute):
            result = await agent.run(context)

        assert result.status == "success"
        assert result.results is not None
        assert result.results.columns == ["month", "revenue"]

    # 18
    @pytest.mark.asyncio
    async def test_token_usage_accumulated(self, agent, mock_llm, context):
        _stub_run_preamble(agent)

        call_count = 0

        async def complete_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_llm_response(
                    tool_calls=[
                        ToolCall(
                            id="tc-1", name="get_schema_info", arguments={"scope": "overview"}
                        ),
                    ],
                    usage={"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
                )
            if call_count == 2:
                return _make_llm_response(
                    tool_calls=[
                        ToolCall(id="tc-2", name="get_custom_rules", arguments={}),
                    ],
                    usage={"prompt_tokens": 200, "completion_tokens": 40, "total_tokens": 240},
                )
            return _make_llm_response(
                content="Done.",
                usage={"prompt_tokens": 300, "completion_tokens": 60, "total_tokens": 360},
            )

        mock_llm.complete = AsyncMock(side_effect=complete_side_effect)
        agent._handle_get_schema_info = AsyncMock(return_value="overview")
        agent._handle_get_custom_rules = AsyncMock(return_value="no rules")

        result = await agent.run(context)

        assert result.token_usage["prompt_tokens"] == 600
        assert result.token_usage["completion_tokens"] == 120
        assert result.token_usage["total_tokens"] == 720

    # 19
    @pytest.mark.asyncio
    async def test_tool_call_log(self, agent, mock_llm, context):
        _stub_run_preamble(agent)

        call_count = 0

        async def complete_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_llm_response(
                    tool_calls=[
                        ToolCall(
                            id="tc-1", name="get_schema_info", arguments={"scope": "overview"}
                        ),
                        ToolCall(id="tc-2", name="get_custom_rules", arguments={}),
                    ],
                )
            return _make_llm_response(content="All done.")

        mock_llm.complete = AsyncMock(side_effect=complete_side_effect)
        agent._handle_get_schema_info = AsyncMock(return_value="schema overview")
        agent._handle_get_custom_rules = AsyncMock(return_value="rules text")

        result = await agent.run(context)

        assert len(result.tool_call_log) == 2
        assert result.tool_call_log[0]["tool"] == "get_schema_info"
        assert result.tool_call_log[1]["tool"] == "get_custom_rules"
        assert "result_preview" in result.tool_call_log[0]

    # 20
    @pytest.mark.asyncio
    async def test_learning_extraction(self, agent, mock_llm, context, config):
        _stub_run_preamble(agent)

        qr = QueryResult(
            columns=["id"],
            rows=[[1]],
            row_count=1,
            execution_time_ms=2.0,
        )

        call_count = 0

        async def complete_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_llm_response(
                    tool_calls=[
                        ToolCall(
                            id="tc-q",
                            name="execute_query",
                            arguments={
                                "query": "SELECT id FROM users",
                                "explanation": "Get user IDs",
                            },
                        ),
                    ],
                )
            return _make_llm_response(content="Here are the user IDs.")

        mock_llm.complete = AsyncMock(side_effect=complete_side_effect)

        mock_validation_loop = AsyncMock()
        mock_validation_loop.return_value.execute = AsyncMock(
            return_value=ValidationLoopResult(
                success=True,
                query="SELECT id FROM users",
                explanation="Get user IDs",
                results=qr,
                attempts=[MagicMock(), MagicMock()],
                total_attempts=2,
            )
        )

        mock_connector = AsyncMock()
        mock_connector.connect = AsyncMock()
        mock_connector.introspect_schema = AsyncMock(
            return_value=SchemaInfo(db_type="postgres", db_name="testdb")
        )

        with (
            patch("app.agents.sql_agent.get_connector", return_value=mock_connector),
            patch("app.agents.sql_agent.ValidationLoop") as mock_vl,
            patch.object(agent, "_build_validation_config", return_value=MagicMock()),
            patch.object(agent, "_load_db_index_hints", new_callable=AsyncMock, return_value=""),
            patch.object(
                agent,
                "_load_sync_for_repair",
                new_callable=AsyncMock,
                return_value=("", ""),
            ),
            patch.object(agent, "_load_rules_for_repair", new_callable=AsyncMock, return_value=""),
            patch.object(agent, "_load_distinct_values", new_callable=AsyncMock, return_value={}),
            patch.object(
                agent, "_load_learnings_for_repair", new_callable=AsyncMock, return_value=""
            ),
            patch.object(agent, "_extract_learnings", new_callable=AsyncMock) as mock_extract,
        ):
            vl_instance = mock_vl.return_value
            vl_instance.execute = AsyncMock(
                return_value=ValidationLoopResult(
                    success=True,
                    query="SELECT id FROM users",
                    explanation="Get user IDs",
                    results=qr,
                    attempts=[MagicMock(), MagicMock()],
                    total_attempts=2,
                )
            )

            result = await agent.run(context)

        assert result.status == "success"
        mock_extract.assert_awaited_once()
        call_args = mock_extract.call_args
        assert call_args[0][1] is True  # success=True


# ---------------------------------------------------------------------------
# Custom rules injection into system prompt
# ---------------------------------------------------------------------------


class TestSQLAgentCustomRulesInjection:
    """Verify that custom rules are loaded and injected into the SQL system prompt."""

    @pytest.mark.asyncio
    async def test_rules_loaded_into_system_prompt(
        self,
        agent,
        mock_llm,
        mock_custom_rules,
        context,
    ):
        _stub_run_preamble(agent)

        mock_custom_rules.rules_to_context.return_value = (
            "## Custom Rules\n### Revenue\nAlways divide amount by 100."
        )

        mock_llm.complete = AsyncMock(return_value=_make_llm_response(content="Done."))

        await agent.run(context)

        mock_custom_rules.load_rules.assert_called()
        mock_custom_rules.load_db_rules.assert_called()

        call_kwargs = mock_llm.complete.call_args.kwargs
        messages = call_kwargs.get("messages", [])
        system_msg = messages[0]
        assert "CUSTOM RULES & BUSINESS LOGIC" in system_msg.content
        assert "Always divide amount by 100" in system_msg.content

    @pytest.mark.asyncio
    async def test_empty_rules_omitted_from_prompt(
        self,
        agent,
        mock_llm,
        mock_custom_rules,
        context,
    ):
        _stub_run_preamble(agent)
        mock_custom_rules.rules_to_context.return_value = ""

        mock_llm.complete = AsyncMock(return_value=_make_llm_response(content="Done."))

        await agent.run(context)

        call_kwargs = mock_llm.complete.call_args.kwargs
        messages = call_kwargs.get("messages", [])
        system_msg = messages[0]
        assert "CUSTOM RULES & BUSINESS LOGIC" not in system_msg.content

    @pytest.mark.asyncio
    async def test_rules_truncated_when_too_long(self, agent, mock_custom_rules, context):
        long_rules = "x" * 5000
        mock_custom_rules.rules_to_context.return_value = long_rules

        text = await agent._load_rules_for_prompt("proj-1")

        assert len(text) < len(long_rules)
        assert text.endswith("... (truncated)")

    @pytest.mark.asyncio
    async def test_rules_load_failure_returns_empty(self, agent, mock_custom_rules, context):
        mock_custom_rules.load_rules.side_effect = RuntimeError("disk error")

        text = await agent._load_rules_for_prompt("proj-1")

        assert text == ""


# ---------------------------------------------------------------------------
# ALM integration: extract_learnings, query_context, repair learnings
# ---------------------------------------------------------------------------


class TestSQLAgentALMIntegration:
    """Tests for ALM-specific logic inside SQLAgent."""

    @pytest.fixture
    def agent(self, mock_tracker):
        a = SQLAgent()
        a._has_learnings = AsyncMock(return_value=False)
        a._load_learnings_prompt = AsyncMock(return_value="")
        return a

    @pytest.fixture
    def config(self):
        cfg = ConnectionConfig(
            db_type="postgres",
            db_host="127.0.0.1",
            db_port=5432,
            db_name="testdb",
        )
        cfg.connection_id = "conn-alm"
        return cfg

    @pytest.mark.asyncio
    async def test_extract_learnings_fires_when_multiple_attempts(self, agent, config):
        """_extract_learnings should call LearningAnalyzer.analyze when attempts >= 2."""
        mock_analyzer = MagicMock()
        mock_analyzer.analyze = AsyncMock(return_value=[])
        mock_session = AsyncMock()

        with (
            patch("app.knowledge.learning_analyzer.LearningAnalyzer", return_value=mock_analyzer),
            patch("app.models.base.async_session_factory") as mock_sf,
        ):
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)

            await agent._extract_learnings(
                attempts=[MagicMock(), MagicMock()],
                success=True,
                question="test query",
                cfg=config,
            )

        mock_analyzer.analyze.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_extract_learnings_skips_single_attempt(self, agent, config):
        """Single successful attempt should not trigger extraction."""
        with patch("app.knowledge.learning_analyzer.LearningAnalyzer") as mock_cls:
            await agent._extract_learnings(
                attempts=[MagicMock()],
                success=True,
                question="test",
                cfg=config,
            )
            mock_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_extract_learnings_skips_no_connection_id(self, agent):
        cfg = ConnectionConfig(db_type="postgres", db_host="h", db_name="db")
        with patch("app.knowledge.learning_analyzer.LearningAnalyzer") as mock_cls:
            await agent._extract_learnings(
                attempts=[MagicMock(), MagicMock()],
                success=True,
                question="test",
                cfg=cfg,
            )
            mock_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_track_applied_learnings(self, agent):
        """_track_applied_learnings should call apply_learning for each."""
        mock_svc = MagicMock()
        mock_svc.apply_learning = AsyncMock()

        mock_session = AsyncMock()
        learning1 = MagicMock()
        learning1.id = "l1"
        learning2 = MagicMock()
        learning2.id = "l2"

        with (
            patch("app.models.base.async_session_factory") as mock_sf,
            patch(
                "app.services.agent_learning_service.AgentLearningService",
                return_value=mock_svc,
            ),
        ):
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)

            await agent._track_applied_learnings([learning1, learning2])

        assert mock_svc.apply_learning.call_count == 2
        mock_session.commit.assert_awaited_once()
