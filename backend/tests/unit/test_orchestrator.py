from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.orchestrator import OrchestratorAgent
from app.connectors.base import ConnectionConfig, QueryResult, SchemaInfo
from app.core.orchestrator import Orchestrator, OrchestratorResponse
from app.llm.base import LLMResponse, Message, ToolCall


@pytest.fixture
def mock_llm_router():
    router = MagicMock()
    router.complete = AsyncMock()
    router.stream = AsyncMock()
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
    )


@pytest.fixture
def orchestrator(mock_llm_router, mock_vector_store, mock_custom_rules):
    return Orchestrator(
        llm_router=mock_llm_router,
        vector_store=mock_vector_store,
        custom_rules=mock_custom_rules,
    )


class TestOrchestratorConnectorKey:
    def test_key_includes_db_info(self, orchestrator, config):
        key = orchestrator._connector_key(config)
        assert "postgres" in key
        assert "localhost" in key
        assert "5432" in key
        assert "testdb" in key

    def test_key_includes_ssh_info(self, orchestrator):
        config = ConnectionConfig(
            db_type="postgres",
            db_host="localhost",
            db_port=5432,
            db_name="testdb",
            ssh_host="jump.example.com",
            ssh_port=22,
            ssh_user="deploy",
        )
        key = orchestrator._connector_key(config)
        assert "jump.example.com" in key
        assert "22" in key
        assert "deploy" in key

    def test_different_ssh_different_keys(self, orchestrator):
        config_a = ConnectionConfig(
            db_type="postgres",
            db_host="db",
            db_port=5432,
            db_name="mydb",
            ssh_host="jump1.example.com",
            ssh_port=22,
            ssh_user="a",
        )
        config_b = ConnectionConfig(
            db_type="postgres",
            db_host="db",
            db_port=5432,
            db_name="mydb",
            ssh_host="jump2.example.com",
            ssh_port=22,
            ssh_user="b",
        )
        assert orchestrator._connector_key(config_a) != orchestrator._connector_key(config_b)


class TestOrchestratorProcessQuestion:
    @pytest.mark.asyncio
    async def test_successful_query(self, orchestrator, mock_llm_router, config):
        mock_llm_router.complete = AsyncMock(
            side_effect=[
                LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="1",
                            name="execute_query",
                            arguments={"query": "SELECT 1", "explanation": "test"},
                        )
                    ],
                ),
                LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="2",
                            name="recommend_visualization",
                            arguments={
                                "viz_type": "table",
                                "config": "{}",
                                "summary": "Result is 1",
                            },
                        )
                    ],
                ),
            ]
        )

        mock_connector = AsyncMock()
        mock_connector.connect = AsyncMock()
        mock_connector.execute_query = AsyncMock(
            return_value=QueryResult(
                columns=["?column?"],
                rows=[[1]],
                row_count=1,
                execution_time_ms=1.0,
            )
        )
        mock_connector.introspect_schema = AsyncMock(return_value=SchemaInfo(db_type="postgres"))

        with patch("app.core.orchestrator.get_connector", return_value=mock_connector):
            result = await orchestrator.process_question(
                question="What is 1?",
                project_id="test-project",
                connection_config=config,
            )

        assert isinstance(result, OrchestratorResponse)
        assert result.query == "SELECT 1"
        assert result.error is None

    @pytest.mark.asyncio
    async def test_safety_blocks_dangerous_query(self, orchestrator, mock_llm_router, config):
        mock_llm_router.complete = AsyncMock(
            return_value=LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="1",
                        name="execute_query",
                        arguments={"query": "DROP TABLE users", "explanation": "drop"},
                    )
                ],
            )
        )

        mock_connector = AsyncMock()
        mock_connector.introspect_schema = AsyncMock(return_value=SchemaInfo(db_type="postgres"))

        with patch("app.core.orchestrator.get_connector", return_value=mock_connector):
            result = await orchestrator.process_question(
                question="Drop users table",
                project_id="test-project",
                connection_config=config,
            )

        assert result.error is not None
        assert "blocked" in result.answer.lower() or "blocked" in result.error.lower()

    @pytest.mark.asyncio
    async def test_no_query_generated(self, orchestrator, mock_llm_router, config):
        mock_llm_router.complete = AsyncMock(
            return_value=LLMResponse(
                content="I cannot generate a query for this.",
            )
        )

        mock_connector = AsyncMock()
        mock_connector.introspect_schema = AsyncMock(return_value=SchemaInfo(db_type="postgres"))

        with patch("app.core.orchestrator.get_connector", return_value=mock_connector):
            result = await orchestrator.process_question(
                question="Hello",
                project_id="test-project",
                connection_config=config,
            )

        assert result.error is not None


class TestEnricherReceivesSyncAndRules:
    """Orchestrator passes sync/rules/distinct_values to ContextEnricher."""

    @pytest.mark.asyncio
    async def test_enricher_receives_sync_and_rules(self, orchestrator, mock_llm_router, config):
        from unittest.mock import patch as _patch

        mock_llm_router.complete = AsyncMock(
            side_effect=[
                LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="1",
                            name="execute_query",
                            arguments={"query": "SELECT 1", "explanation": "test"},
                        )
                    ],
                ),
                LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="2",
                            name="recommend_visualization",
                            arguments={
                                "viz_type": "table",
                                "config": "{}",
                                "summary": "Result is 1",
                            },
                        )
                    ],
                ),
            ]
        )

        mock_connector = AsyncMock()
        mock_connector.connect = AsyncMock()
        mock_connector.execute_query = AsyncMock(
            return_value=QueryResult(
                columns=["?column?"],
                rows=[[1]],
                row_count=1,
                execution_time_ms=1.0,
            )
        )
        mock_connector.introspect_schema = AsyncMock(return_value=SchemaInfo(db_type="postgres"))

        captured_enricher_kwargs = {}

        original_init = None

        def capture_enricher_init(self_enricher, *args, **kwargs):
            captured_enricher_kwargs.update(kwargs)
            original_init(self_enricher, *args, **kwargs)

        from app.core.context_enricher import ContextEnricher

        original_init = ContextEnricher.__init__

        mock_sync_entry = MagicMock()
        mock_sync_entry.table_name = "orders"
        mock_sync_entry.conversion_warnings = "amount in cents"

        mock_db_entry = MagicMock()
        mock_db_entry.table_name = "orders"
        mock_db_entry.column_distinct_values_json = '{"status": ["active"]}'

        with (
            _patch("app.core.orchestrator.get_connector", return_value=mock_connector),
            _patch.object(
                orchestrator,
                "_get_sync_for_repair",
                new_callable=AsyncMock,
                return_value=("- orders: amount in cents", ""),
            ),
            _patch.object(
                orchestrator,
                "_get_repair_rules_context",
                new_callable=AsyncMock,
                return_value="Use amount/100",
            ),
            _patch.object(
                orchestrator,
                "_get_distinct_values",
                new_callable=AsyncMock,
                return_value={"orders": {"status": ["active"]}},
            ),
            _patch.object(ContextEnricher, "__init__", side_effect=capture_enricher_init),
        ):
            _result = await orchestrator.process_question(
                question="What is 1?",
                project_id="test-project",
                connection_config=config,
            )

        assert "sync_context" in captured_enricher_kwargs
        assert captured_enricher_kwargs["sync_context"] == "- orders: amount in cents"
        assert "rules_context" in captured_enricher_kwargs
        assert captured_enricher_kwargs["rules_context"] == "Use amount/100"
        assert "distinct_values" in captured_enricher_kwargs
        assert "orders" in captured_enricher_kwargs["distinct_values"]


class TestOrchestratorDisconnect:
    @pytest.mark.asyncio
    async def test_disconnect_all(self, orchestrator):
        mock_conn = AsyncMock()
        orchestrator._connectors["key1"] = mock_conn
        orchestrator._schema_cache["key1"] = (SchemaInfo(db_type="postgres"), 0.0)
        await orchestrator.disconnect_all()
        mock_conn.disconnect.assert_called_once()
        assert len(orchestrator._connectors) == 0
        assert len(orchestrator._schema_cache) == 0


# -------------------------------------------------------------------
# OrchestratorAgent tool-call dedup & history boundary tests
# -------------------------------------------------------------------


class TestDedupToolCalls:
    """Tests for OrchestratorAgent._dedup_tool_calls static method."""

    def _tc(self, id: str, name: str = "query_database", question: str = "") -> ToolCall:
        args = {"question": question} if question else {}
        return ToolCall(id=id, name=name, arguments=args)

    def test_no_duplicates_passes_through(self):
        calls = [
            self._tc("1", question="revenue last month"),
            self._tc("2", question="user count"),
        ]
        kept, skipped = OrchestratorAgent._dedup_tool_calls(calls, [])
        assert len(kept) == 2
        assert len(skipped) == 0

    def test_exact_duplicate_removed(self):
        calls = [
            self._tc("1", question="revenue last month"),
            self._tc("2", question="revenue last month"),
        ]
        kept, skipped = OrchestratorAgent._dedup_tool_calls(calls, [])
        assert len(kept) == 1
        assert kept[0].id == "1"
        assert "2" in skipped
        assert "Duplicate" in skipped["2"]

    def test_non_query_database_not_deduped(self):
        calls = [
            self._tc("1", name="process_data", question="some op"),
            self._tc("2", name="process_data", question="some op"),
        ]
        kept, skipped = OrchestratorAgent._dedup_tool_calls(calls, [])
        assert len(kept) == 2
        assert len(skipped) == 0

    def test_search_codebase_duplicates_removed(self):
        calls = [
            self._tc("1", name="search_codebase", question="what is X"),
            self._tc("2", name="search_codebase", question="what is X"),
        ]
        kept, skipped = OrchestratorAgent._dedup_tool_calls(calls, [])
        assert len(kept) == 1
        assert "2" in skipped

    def test_mixed_kept_and_skipped(self):
        calls = [
            self._tc("1", question="revenue by country"),
            self._tc("2", question="revenue by country"),  # duplicate
            self._tc("3", question="active users today"),
            self._tc("4", name="search_codebase", question="what is X"),
        ]
        kept, skipped = OrchestratorAgent._dedup_tool_calls(calls, [])
        assert len(kept) == 3
        assert "2" in skipped

    def test_empty_calls(self):
        kept, skipped = OrchestratorAgent._dedup_tool_calls([], [])
        assert kept == []
        assert skipped == {}


class TestHistoryBoundaryInPrompt:
    """Verify the orchestrator prompt builder includes focus directives."""

    def test_current_turn_focus_in_prompt(self):
        from app.agents.prompts.orchestrator_prompt import build_orchestrator_system_prompt

        prompt = build_orchestrator_system_prompt(
            has_connection=True,
            db_type="postgres",
        )
        assert "CURRENT TURN FOCUS" in prompt
        assert "TOOL CALL ECONOMY" in prompt
        assert "SINGLE-QUESTION RULE" in prompt

    def test_guidelines_still_present(self):
        from app.agents.prompts.orchestrator_prompt import build_orchestrator_system_prompt

        prompt = build_orchestrator_system_prompt(
            has_connection=True,
            db_type="postgres",
        )
        assert "GUIDELINES:" in prompt
        assert "query_database" in prompt
        assert "REQUEST ANALYSIS PROTOCOL" in prompt

    def test_single_question_rule_excludes_process_data(self):
        from app.agents.prompts.orchestrator_prompt import build_orchestrator_system_prompt

        prompt = build_orchestrator_system_prompt(
            has_connection=True,
            db_type="postgres",
        )
        assert "data retrieval" in prompt
        assert "process_data" in prompt
        assert "do not count toward this limit" in prompt

    def test_mcp_source_capability_shown_when_enabled(self):
        from app.agents.prompts.orchestrator_prompt import build_orchestrator_system_prompt

        prompt = build_orchestrator_system_prompt(
            has_connection=True,
            db_type="postgres",
            has_mcp_sources=True,
        )
        assert "query_mcp_source" in prompt
        assert "External data sources" in prompt

    def test_mcp_source_hidden_when_disabled(self):
        from app.agents.prompts.orchestrator_prompt import build_orchestrator_system_prompt

        prompt = build_orchestrator_system_prompt(
            has_connection=True,
            db_type="postgres",
            has_mcp_sources=False,
        )
        assert "query_mcp_source" not in prompt

    def test_parallel_guideline_excludes_process_data(self):
        from app.agents.prompts.orchestrator_prompt import build_orchestrator_system_prompt

        prompt = build_orchestrator_system_prompt(
            has_connection=True,
            db_type="postgres",
        )
        assert "chain `process_data` calls sequentially" in prompt


class TestPipelineScopedContext:
    """Verify _run_complex_pipeline passes scoped context to StageExecutor."""

    @pytest.mark.asyncio
    async def test_pipeline_scopes_history_before_executor(self):
        from dataclasses import dataclass
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.agents.base import AgentContext
        from app.agents.stage_context import (
            ExecutionPlan,
            PlanStage,
            StageContext,
        )

        mock_router = MagicMock()
        mock_router.complete = AsyncMock()
        mock_router.get_context_window = MagicMock(return_value=128_000)

        tracker = MagicMock()
        tracker.emit = AsyncMock()
        tracker.end = AsyncMock()
        tracker.step = MagicMock()
        tracker.step.return_value.__aenter__ = AsyncMock(return_value=None)
        tracker.step.return_value.__aexit__ = AsyncMock(return_value=False)

        agent = OrchestratorAgent(
            llm_router=mock_router,
            workflow_tracker=tracker,
        )

        history = [Message(role="user", content=f"msg-{i}") for i in range(12)]
        ctx = AgentContext(
            project_id="test-proj",
            connection_config=None,
            user_question="complex question",
            chat_history=history,
            llm_router=mock_router,
            tracker=tracker,
            workflow_id="wf-1",
        )

        plan = ExecutionPlan(
            plan_id="p1",
            question="complex question",
            stages=[
                PlanStage(
                    stage_id="s1",
                    description="fetch data",
                    tool="query_database",
                ),
            ],
        )

        @dataclass
        class _FakeExecResult:
            stage_ctx: StageContext
            final_answer: str = "answer"

        captured_ctx = {}

        async def _capture_execute(_plan, context, *, resume_from=0, stage_ctx=None):
            captured_ctx["ctx"] = context
            return _FakeExecResult(
                stage_ctx=stage_ctx or StageContext(plan=plan),
            )

        mock_pipeline_run = MagicMock()
        mock_pipeline_run.id = "run-1"

        with (
            patch.object(
                agent, "_create_pipeline_run", new=AsyncMock(return_value=mock_pipeline_run)
            ),
            patch.object(agent, "_persist_stage_results", new=AsyncMock()),
            patch.object(agent, "_build_pipeline_response", return_value=MagicMock()),
            patch("app.agents.orchestrator.StageExecutor") as mock_executor_cls,
            patch("app.agents.orchestrator.QueryPlanner") as mock_planner_cls,
        ):
            mock_planner = mock_planner_cls.return_value
            mock_planner.plan = AsyncMock(return_value=plan)

            mock_executor = mock_executor_cls.return_value
            mock_executor.execute = AsyncMock(side_effect=_capture_execute)

            await agent._run_complex_pipeline(
                ctx, wf_id="wf-1", table_map="", db_type="postgres", staleness_warning=None
            )

        assert "ctx" in captured_ctx, "StageExecutor.execute was not called"
        scoped = captured_ctx["ctx"]
        assert len(scoped.chat_history) <= 4, (
            f"Expected scoped history (<=4), got {len(scoped.chat_history)}"
        )


class TestLegacyQueryBuilderBoundary:
    """Verify the legacy QueryBuilder injects a history boundary."""

    @pytest.mark.asyncio
    async def test_boundary_injected_when_history_present(self):
        from app.core.query_builder import QueryBuilder

        mock_router = MagicMock()
        mock_resp = MagicMock()
        mock_resp.tool_calls = [
            MagicMock(
                name="execute_query",
                arguments={"query": "SELECT 1", "explanation": "test"},
            )
        ]
        mock_resp.usage = {}
        mock_router.complete = AsyncMock(return_value=mock_resp)

        from app.llm.base import Message

        history = [
            Message(role="user", content="old question"),
            Message(role="assistant", content="old answer"),
            Message(role="user", content="another old question"),
            Message(role="assistant", content="another old answer"),
            Message(role="user", content="yet another"),
            Message(role="assistant", content="yet another answer"),
        ]

        qb = QueryBuilder(mock_router)
        await qb.build_query("new question", "schema", "", "postgres", chat_history=history)

        call_messages = mock_router.complete.call_args.kwargs.get(
            "messages",
            mock_router.complete.call_args[0][0] if mock_router.complete.call_args[0] else [],
        )
        texts = [m.content for m in call_messages]
        assert any("END OF CONVERSATION HISTORY" in t for t in texts)
        assert (
            len([m for m in call_messages if m.role == "user" and m.content == "old question"]) == 0
        )

    @pytest.mark.asyncio
    async def test_no_boundary_when_no_history(self):
        from app.core.query_builder import QueryBuilder

        mock_router = MagicMock()
        mock_resp = MagicMock()
        mock_resp.tool_calls = [
            MagicMock(
                name="execute_query",
                arguments={"query": "SELECT 1", "explanation": "test"},
            )
        ]
        mock_resp.usage = {}
        mock_router.complete = AsyncMock(return_value=mock_resp)

        qb = QueryBuilder(mock_router)
        await qb.build_query("new question", "schema", "", "postgres")

        call_messages = mock_router.complete.call_args.kwargs.get(
            "messages",
            mock_router.complete.call_args[0][0] if mock_router.complete.call_args[0] else [],
        )
        texts = [m.content for m in call_messages]
        assert not any("END OF CONVERSATION HISTORY" in t for t in texts)


# ------------------------------------------------------------------
# H-5: _handle_process_data tests
# ------------------------------------------------------------------


class TestHandleProcessData:
    """Tests for OrchestratorAgent._handle_process_data and _build_process_data_params."""

    def test_exclude_empty_false_string_is_not_truthy(self):
        params = OrchestratorAgent._build_process_data_params({"exclude_empty": "false"})
        assert "exclude_empty" not in params

    def test_exclude_empty_true_string_is_truthy(self):
        params = OrchestratorAgent._build_process_data_params({"exclude_empty": "true"})
        assert params["exclude_empty"] is True

    def test_exclude_empty_yes_string_is_truthy(self):
        params = OrchestratorAgent._build_process_data_params({"exclude_empty": "yes"})
        assert params["exclude_empty"] is True

    def test_exclude_empty_1_string_is_truthy(self):
        params = OrchestratorAgent._build_process_data_params({"exclude_empty": "1"})
        assert params["exclude_empty"] is True

    def test_exclude_empty_empty_string_not_truthy(self):
        params = OrchestratorAgent._build_process_data_params({"exclude_empty": ""})
        assert "exclude_empty" not in params

    def test_aggregations_parsed(self):
        params = OrchestratorAgent._build_process_data_params(
            {"aggregations": "amount:sum,user_id:count_distinct"}
        )
        assert params["aggregations"] == [("amount", "sum"), ("user_id", "count_distinct")]

    def test_group_by_parsed(self):
        params = OrchestratorAgent._build_process_data_params({"group_by": "country, city"})
        assert params["group_by"] == ["country", "city"]

    def test_column_passed_through(self):
        params = OrchestratorAgent._build_process_data_params({"column": "user_ip"})
        assert params["column"] == "user_ip"

    @pytest.mark.asyncio
    async def test_no_sql_result_returns_error(self):
        from app.core.workflow_tracker import WorkflowTracker

        agent = OrchestratorAgent(
            llm_router=MagicMock(),
            workflow_tracker=MagicMock(spec=WorkflowTracker),
        )
        tc = ToolCall(id="tc1", name="process_data", arguments={"operation": "aggregate_data"})
        result = await agent._handle_process_data(tc, "wf-1")
        assert "no query results" in result.lower()

    @pytest.mark.asyncio
    async def test_process_data_does_not_mutate_original(self):
        from app.agents.sql_agent import SQLAgentResult
        from app.core.workflow_tracker import WorkflowTracker
        from app.services.data_processor import ProcessedData

        qr_original = QueryResult(
            columns=["ip", "amount"],
            rows=[["1.2.3.4", 100]],
            row_count=1,
        )
        sql_res = SQLAgentResult(status="success", query="SELECT 1", results=qr_original)

        tracker = MagicMock(spec=WorkflowTracker)
        tracker.emit = AsyncMock()
        agent = OrchestratorAgent(llm_router=MagicMock(), workflow_tracker=tracker)
        agent._wf_sql_results["wf-1"] = sql_res

        enriched_qr = QueryResult(
            columns=["ip", "amount", "country"],
            rows=[["1.2.3.4", 100, "US"]],
            row_count=1,
        )
        mock_processed = ProcessedData(query_result=enriched_qr, summary="Added country")

        with patch("app.agents.orchestrator.get_data_processor") as mock_gdp:
            mock_gdp.return_value.process.return_value = mock_processed
            tc = ToolCall(
                id="tc1",
                name="process_data",
                arguments={"operation": "ip_to_country", "column": "ip"},
            )
            result_text = await agent._handle_process_data(tc, "wf-1")

        assert sql_res.results is qr_original
        assert agent._wf_sql_results["wf-1"].results is enriched_qr
        assert "Added country" in result_text


# ------------------------------------------------------------------
# H-6: wall-clock timeout test
# ------------------------------------------------------------------


class TestWallClockTimeout:
    """Test that the orchestrator respects wall-clock timeout."""

    @pytest.mark.asyncio
    async def test_soft_timeout_injects_wrap_up_message(self):
        """When elapsed > wall_clock_limit, a wrap-up message is injected."""
        from app.agents.base import AgentContext
        from app.core.workflow_tracker import WorkflowTracker

        mock_router = MagicMock()
        mock_tracker = MagicMock(spec=WorkflowTracker)
        mock_tracker.emit = AsyncMock()
        mock_tracker.step = MagicMock()
        mock_tracker.step.return_value.__aenter__ = AsyncMock()
        mock_tracker.step.return_value.__aexit__ = AsyncMock()
        mock_tracker.start = AsyncMock(return_value="wf-test")
        mock_tracker.end = AsyncMock()

        tool_calls_response = LLMResponse(
            content="thinking...",
            tool_calls=[
                ToolCall(
                    id="tc1",
                    name="query_database",
                    arguments={"question": "test query"},
                ),
            ],
            usage={"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        )

        final_response = LLMResponse(
            content="Here is the answer.",
            tool_calls=[],
            usage={"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        )

        call_count = 0

        async def mock_complete(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return tool_calls_response
            return final_response

        mock_router.complete = AsyncMock(side_effect=mock_complete)
        mock_router.get_context_window = MagicMock(return_value=8000)

        agent = OrchestratorAgent(
            llm_router=mock_router,
            workflow_tracker=mock_tracker,
        )

        ctx = AgentContext(
            project_id="p1",
            connection_config=None,
            user_question="test question",
            chat_history=[],
            llm_router=mock_router,
            tracker=mock_tracker,
            workflow_id="wf-test",
            extra={"_skip_complexity": True},
        )

        with (
            patch.object(agent, "_has_mcp_sources", new=AsyncMock(return_value=False)),
            patch.object(
                agent,
                "_handle_meta_tool",
                new=AsyncMock(return_value=("result text", None)),
            ),
            patch("app.agents.orchestrator.settings") as mock_settings,
            patch("app.agents.orchestrator.time") as mock_time,
        ):
            mock_settings.max_orchestrator_iterations = 10
            mock_settings.max_parallel_tool_calls = 1
            mock_settings.orchestrator_wrap_up_steps = 2
            mock_settings.agent_wall_clock_timeout_seconds = 30
            mock_settings.max_context_tokens = 8000
            mock_settings.max_history_tokens = 2500

            monotonic_values = [0.0, 35.0, 35.0, 35.0, 35.0]
            mock_time.monotonic = MagicMock(side_effect=monotonic_values)

            await agent.run(ctx)

            assert call_count == 2
            second_call_messages = mock_router.complete.call_args_list[1].kwargs.get(
                "messages",
                mock_router.complete.call_args_list[1][0][0]
                if mock_router.complete.call_args_list[1][0]
                else [],
            )
            wall_clock_msgs = [
                m
                for m in second_call_messages
                if m.role == "system" and "TIME LIMIT REACHED" in m.content
            ]
            assert len(wall_clock_msgs) >= 1


# ------------------------------------------------------------------
# H-7: trim_loop_messages and should_wrap_up tests
# ------------------------------------------------------------------


class TestTrimLoopMessages:
    """Tests for in-loop message trimming."""

    def test_short_messages_unchanged(self):
        from app.core.history_trimmer import trim_loop_messages

        msgs = [
            Message(role="system", content="You are a bot."),
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi there"),
        ]
        result, did_trim = trim_loop_messages(msgs, 100000)
        assert not did_trim
        assert len(result) == 3

    def test_trims_over_budget(self):
        from app.core.history_trimmer import trim_loop_messages

        system = Message(role="system", content="S" * 100)
        user = Message(role="user", content="U" * 100)
        assistant = Message(role="assistant", content="A" * 400)
        tool_msg = Message(role="tool", content="T" * 2000, tool_call_id="tc1", name="f")
        final_user = Message(role="user", content="Q" * 100)
        msgs = [system, user, assistant, tool_msg, final_user]

        budget = 300
        result, did_trim = trim_loop_messages(msgs, budget)
        assert did_trim
        assert result[0].role == "system"
        assert result[-1].content == final_user.content

    def test_preserves_system_and_last_user(self):
        from app.core.history_trimmer import trim_loop_messages

        system = Message(role="system", content="System prompt " * 10)
        msgs = [
            system,
            Message(role="assistant", content="A " * 200),
            Message(role="tool", content="T " * 200, tool_call_id="tc1", name="f"),
            Message(role="assistant", content="B " * 200),
            Message(role="tool", content="T2 " * 200, tool_call_id="tc2", name="g"),
            Message(role="user", content="final question"),
        ]

        result, did_trim = trim_loop_messages(msgs, 150)
        assert did_trim
        assert result[0].role == "system"
        assert result[-1].content == "final question"

    def test_empty_messages_returns_unchanged(self):
        from app.core.history_trimmer import trim_loop_messages

        result, did_trim = trim_loop_messages([], 1000)
        assert not did_trim
        assert result == []

    def test_summary_created_for_collapsed_pairs(self):
        from app.core.history_trimmer import trim_loop_messages

        system = Message(role="system", content="S")
        msgs = [
            system,
            Message(role="assistant", content="Calling query"),
            Message(
                role="tool",
                content="result data " * 100,
                tool_call_id="tc1",
                name="query_db",
            ),
            Message(role="assistant", content="Calling process"),
            Message(
                role="tool",
                content="processed data " * 100,
                tool_call_id="tc2",
                name="process",
            ),
            Message(role="user", content="final q"),
        ]

        result, did_trim = trim_loop_messages(msgs, 60)
        assert did_trim
        summary_msgs = [m for m in result if "Earlier analysis summary" in m.content]
        assert len(summary_msgs) >= 1


class TestShouldWrapUp:
    """Tests for should_wrap_up context threshold check."""

    def test_under_threshold_returns_false(self):
        from app.core.history_trimmer import should_wrap_up

        msgs = [Message(role="user", content="short")]
        assert should_wrap_up(msgs, 100000) is False

    def test_over_threshold_returns_true(self):
        from app.core.history_trimmer import CHARS_PER_TOKEN_ESTIMATE, should_wrap_up

        content = "x" * (CHARS_PER_TOKEN_ESTIMATE * 800)
        msgs = [Message(role="user", content=content)]
        assert should_wrap_up(msgs, 1000) is True

    def test_exactly_at_threshold(self):
        from app.core.history_trimmer import (
            _WRAP_UP_THRESHOLD,
            CHARS_PER_TOKEN_ESTIMATE,
            should_wrap_up,
        )

        max_tokens = 1000
        threshold_tokens = int(max_tokens * _WRAP_UP_THRESHOLD)
        content = "x" * (CHARS_PER_TOKEN_ESTIMATE * (threshold_tokens + 1))
        msgs = [Message(role="user", content=content)]
        assert should_wrap_up(msgs, max_tokens) is True


# ------------------------------------------------------------------
# M-3 / M-13: response type and validation tests
# ------------------------------------------------------------------


class TestDetermineResponseType:
    """Tests for _determine_response_type including mcp_source."""

    def test_sql_result_wins(self):
        from app.agents.sql_agent import SQLAgentResult

        sql_res = SQLAgentResult(
            status="success",
            query="SELECT 1",
            results=QueryResult(columns=["a"], rows=[[1]], row_count=1),
        )
        result = OrchestratorAgent._determine_response_type(sql_res, [], has_mcp_result=True)
        assert result == "sql_result"

    def test_knowledge_wins_over_mcp(self):
        from app.agents.knowledge_agent import RAGSource

        sources = [MagicMock(spec=RAGSource)]
        result = OrchestratorAgent._determine_response_type(None, sources, has_mcp_result=True)
        assert result == "knowledge"

    def test_mcp_source_when_only_mcp(self):
        result = OrchestratorAgent._determine_response_type(None, [], has_mcp_result=True)
        assert result == "mcp_source"

    def test_text_fallback(self):
        result = OrchestratorAgent._determine_response_type(None, [], has_mcp_result=False)
        assert result == "text"


class TestMcpValidation:
    """Tests for AgentResultValidator.validate_mcp_result."""

    def test_error_status_fails(self):
        from app.agents.validation import AgentResultValidator

        validator = AgentResultValidator()
        result = MagicMock(status="error", error="Connection refused")
        outcome = validator.validate_mcp_result(result)
        assert not outcome.passed
        assert "Connection refused" in outcome.errors[0]

    def test_empty_answer_warns(self):
        from app.agents.validation import AgentResultValidator

        validator = AgentResultValidator()
        result = MagicMock(status="success", answer="")
        outcome = validator.validate_mcp_result(result)
        assert outcome.passed
        assert len(outcome.warnings) == 1

    def test_valid_result_passes(self):
        from app.agents.validation import AgentResultValidator

        validator = AgentResultValidator()
        result = MagicMock(status="success", answer="Some data")
        outcome = validator.validate_mcp_result(result)
        assert outcome.passed
        assert len(outcome.errors) == 0


# ------------------------------------------------------------------
# Intent-based routing in OrchestratorAgent
# ------------------------------------------------------------------


class TestOrchestratorIntentRouting:
    """Verify the orchestrator routes to the correct execution path based on intent."""

    @pytest.fixture
    def mock_tracker(self):
        from contextlib import asynccontextmanager

        from app.core.workflow_tracker import WorkflowTracker

        t = MagicMock(spec=WorkflowTracker)
        t.begin = AsyncMock(return_value="wf-1")
        t.end = AsyncMock()
        t.emit = AsyncMock()
        t.has_ended = MagicMock(return_value=True)

        @asynccontextmanager
        async def fake_step(wf_id, step, detail="", **kwargs):
            yield

        t.step = MagicMock(side_effect=fake_step)
        return t

    @pytest.fixture
    def mock_llm(self):
        router = MagicMock()
        router.complete = AsyncMock()
        router.get_context_window = MagicMock(return_value=128_000)
        return router

    @pytest.fixture
    def mock_vs(self):
        vs = MagicMock()
        collection = MagicMock()
        collection.count = MagicMock(return_value=0)
        vs.get_or_create_collection = MagicMock(return_value=collection)
        return vs

    @pytest.fixture
    def orch(self, mock_llm, mock_vs, mock_tracker):
        return OrchestratorAgent(
            llm_router=mock_llm,
            vector_store=mock_vs,
            workflow_tracker=mock_tracker,
        )

    @pytest.fixture
    def base_context(self, mock_llm, mock_tracker):
        from app.agents.base import AgentContext

        return AgentContext(
            project_id="test-proj",
            connection_config=None,
            user_question="Hello!",
            chat_history=[],
            llm_router=mock_llm,
            tracker=mock_tracker,
            workflow_id="wf-1",
            project_name="TestProject",
        )

    @pytest.mark.asyncio
    async def test_direct_response_path(self, orch, mock_llm, base_context):
        """A greeting should be classified as direct_response and skip heavy context."""
        mock_llm.complete = AsyncMock(
            side_effect=[
                LLMResponse(content='{"intent": "direct_response", "reason": "greeting"}'),
                LLMResponse(content="Hello! I am your data assistant."),
            ]
        )
        with (
            patch(
                "app.agents.orchestrator.OrchestratorAgent._has_mcp_sources",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            resp = await orch.run(base_context)

        assert resp.response_type == "text"
        assert "assistant" in resp.answer.lower() or "hello" in resp.answer.lower()
        assert resp.query is None
        assert resp.results is None
        assert mock_llm.complete.call_count == 2

    @pytest.mark.asyncio
    async def test_mixed_fallback_on_classification_error(self, orch, mock_llm, base_context):
        """If classification fails, the orchestrator should fall back to the full pipeline."""
        mock_llm.complete = AsyncMock(
            side_effect=[
                RuntimeError("LLM is down"),
                LLMResponse(content="I can help with data analysis."),
            ]
        )
        with (
            patch(
                "app.agents.orchestrator.OrchestratorAgent._has_mcp_sources",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.agents.orchestrator.OrchestratorAgent._check_staleness",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.agents.orchestrator.OrchestratorAgent._load_project_overview",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.agents.orchestrator.OrchestratorAgent._load_recent_learnings",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.agents.orchestrator.detect_complexity",
                return_value=False,
            ),
            patch(
                "app.agents.orchestrator.detect_complexity_adaptive",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            resp = await orch.run(base_context)

        assert resp.response_type == "text"

    @pytest.mark.asyncio
    async def test_data_query_path(self, orch, mock_llm, base_context):
        """A data question should load DB context and enter the tool loop."""
        from app.agents.base import AgentContext

        ctx = AgentContext(
            project_id="test-proj",
            connection_config=ConnectionConfig(
                db_type="postgres",
                db_host="localhost",
                db_port=5432,
                db_name="testdb",
                db_user="user",
                connection_id="conn-1",
            ),
            user_question="How many users are there?",
            chat_history=[],
            llm_router=mock_llm,
            tracker=base_context.tracker,
            workflow_id="wf-1",
            project_name="TestProject",
        )

        mock_llm.complete = AsyncMock(
            side_effect=[
                LLMResponse(content='{"intent": "data_query", "reason": "user count"}'),
                LLMResponse(content="There are 42 users in the database."),
            ]
        )
        with (
            patch(
                "app.agents.orchestrator.OrchestratorAgent._has_mcp_sources",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.agents.orchestrator.OrchestratorAgent._build_table_map",
                new_callable=AsyncMock,
                return_value="users: id, email",
            ),
            patch(
                "app.agents.orchestrator.OrchestratorAgent._load_project_overview",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.agents.orchestrator.OrchestratorAgent._load_recent_learnings",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.agents.orchestrator.detect_complexity",
                return_value=False,
            ),
            patch(
                "app.agents.orchestrator.detect_complexity_adaptive",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            resp = await orch.run(ctx)

        assert resp.response_type == "text"
        assert "42" in resp.answer

    @pytest.mark.asyncio
    async def test_knowledge_query_path(self, orch, mock_llm, base_context, mock_vs):
        """A code question should only load KB context, not DB context."""
        collection = MagicMock()
        collection.count = MagicMock(return_value=5)
        mock_vs.get_or_create_collection = MagicMock(return_value=collection)

        mock_llm.complete = AsyncMock(
            side_effect=[
                LLMResponse(content='{"intent": "knowledge_query", "reason": "code architecture"}'),
                LLMResponse(content="The User model has fields id, email, name."),
            ]
        )
        base_context.user_question = "What does the User model look like?"

        with (
            patch(
                "app.agents.orchestrator.OrchestratorAgent._has_mcp_sources",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.agents.orchestrator.OrchestratorAgent._check_staleness",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            resp = await orch.run(base_context)

        assert resp.response_type == "text"
        assert "User model" in resp.answer

    @pytest.mark.asyncio
    async def test_direct_response_does_not_load_table_map(self, orch, mock_llm, base_context):
        """Verify _run_direct_response never calls _build_table_map."""
        mock_llm.complete = AsyncMock(
            side_effect=[
                LLMResponse(content='{"intent": "direct_response", "reason": "meta question"}'),
                LLMResponse(content="I can help you explore your data."),
            ]
        )
        with (
            patch(
                "app.agents.orchestrator.OrchestratorAgent._has_mcp_sources",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.agents.orchestrator.OrchestratorAgent._build_table_map",
                new_callable=AsyncMock,
            ) as mock_table_map,
            patch(
                "app.agents.orchestrator.OrchestratorAgent._load_project_overview",
                new_callable=AsyncMock,
            ) as mock_overview,
            patch(
                "app.agents.orchestrator.OrchestratorAgent._load_recent_learnings",
                new_callable=AsyncMock,
            ) as mock_learnings,
        ):
            base_context.user_question = "What can you do?"
            await orch.run(base_context)

        mock_table_map.assert_not_called()
        mock_overview.assert_not_called()
        mock_learnings.assert_not_called()
