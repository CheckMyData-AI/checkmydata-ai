from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.orchestrator import AgentResponse, OrchestratorAgent, SQLResultBlock
from app.agents.response_builder import ResponseBuilder
from app.config import settings
from app.connectors.base import ConnectionConfig, QueryResult
from app.core.workflow_tracker import WorkflowTracker
from app.llm.base import LLMResponse, Message, ToolCall

# -------------------------------------------------------------------
# OrchestratorAgent tool-call dedup & history boundary tests
#
# (Legacy app.core.orchestrator tests removed with the deprecated
# module — T-ARCH-4. connector_key coverage lives in
# tests/unit/test_connection_lifecycle.py.)
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
        kept, skipped = OrchestratorAgent._dedup_tool_calls(calls)
        assert len(kept) == 2
        assert len(skipped) == 0

    def test_exact_duplicate_removed(self):
        calls = [
            self._tc("1", question="revenue last month"),
            self._tc("2", question="revenue last month"),
        ]
        kept, skipped = OrchestratorAgent._dedup_tool_calls(calls)
        assert len(kept) == 1
        assert kept[0].id == "1"
        assert "2" in skipped
        assert "Duplicate" in skipped["2"]

    def test_non_query_database_not_deduped(self):
        calls = [
            self._tc("1", name="process_data", question="some op"),
            self._tc("2", name="process_data", question="some op"),
        ]
        kept, skipped = OrchestratorAgent._dedup_tool_calls(calls)
        assert len(kept) == 2
        assert len(skipped) == 0

    def test_search_codebase_duplicates_removed(self):
        calls = [
            self._tc("1", name="search_codebase", question="what is X"),
            self._tc("2", name="search_codebase", question="what is X"),
        ]
        kept, skipped = OrchestratorAgent._dedup_tool_calls(calls)
        assert len(kept) == 1
        assert "2" in skipped

    def test_mixed_kept_and_skipped(self):
        calls = [
            self._tc("1", question="revenue by country"),
            self._tc("2", question="revenue by country"),  # duplicate
            self._tc("3", question="active users today"),
            self._tc("4", name="search_codebase", question="what is X"),
        ]
        kept, skipped = OrchestratorAgent._dedup_tool_calls(calls)
        assert len(kept) == 3
        assert "2" in skipped

    def test_empty_calls(self):
        kept, skipped = OrchestratorAgent._dedup_tool_calls([])
        assert kept == []
        assert skipped == {}

    def test_embedding_path_detects_paraphrase(self, monkeypatch):
        """When embeddings are available, paraphrases are caught (T13)."""
        from app.services import text_similarity

        def fake_encode(texts):
            # Two near-identical vectors for paraphrased queries, one orthogonal
            mapping = {
                "top 5 customers by revenue": [1.0, 0.0, 0.0],
                "five highest-revenue clients": [0.98, 0.199, 0.0],
                "active users today": [0.0, 0.0, 1.0],
            }
            return [mapping.get(t, [0.0, 0.0, 0.0]) for t in texts]

        monkeypatch.setattr(text_similarity, "encode_batch", fake_encode)

        calls = [
            self._tc("1", question="top 5 customers by revenue"),
            self._tc("2", question="five highest-revenue clients"),
            self._tc("3", question="active users today"),
        ]
        kept, skipped = OrchestratorAgent._dedup_tool_calls(calls)
        assert {tc.id for tc in kept} == {"1", "3"}
        assert "2" in skipped

    def test_falls_back_to_word_overlap_when_no_embeddings(self, monkeypatch):
        from app.services import text_similarity

        monkeypatch.setattr(text_similarity, "encode_batch", lambda _texts: None)

        calls = [
            self._tc("1", question="revenue by country"),
            self._tc("2", question="revenue by country"),
            self._tc("3", question="totally different question"),
        ]
        kept, skipped = OrchestratorAgent._dedup_tool_calls(calls)
        assert {tc.id for tc in kept} == {"1", "3"}
        assert "2" in skipped


class TestFilterAlreadyExecuted:
    """Tests for ToolDispatcher.filter_already_executed (per-turn dedup)."""

    def _tc(self, id: str, name: str = "query_database", question: str = "") -> ToolCall:
        args = {"question": question} if question else {}
        return ToolCall(id=id, name=name, arguments=args)

    def test_no_executed_history_passes_through(self):
        from app.agents.tool_dispatcher import ToolDispatcher

        calls = [self._tc("1", question="revenue last month")]
        kept, skipped = ToolDispatcher.filter_already_executed(calls, [])
        assert len(kept) == 1
        assert skipped == {}

    def test_repeated_question_skipped(self, monkeypatch):
        from app.agents.tool_dispatcher import ToolDispatcher
        from app.services import text_similarity

        # Force the word-overlap path for determinism.
        monkeypatch.setattr(text_similarity, "encode_batch", lambda _texts: None)

        calls = [self._tc("1", question="revenue by country")]
        executed = [("query_database", "revenue by country")]
        kept, skipped = ToolDispatcher.filter_already_executed(calls, executed)
        assert kept == []
        assert "1" in skipped
        assert "already answered earlier in this turn" in skipped["1"]

    def test_different_question_kept(self, monkeypatch):
        from app.agents.tool_dispatcher import ToolDispatcher
        from app.services import text_similarity

        monkeypatch.setattr(text_similarity, "encode_batch", lambda _texts: None)

        calls = [self._tc("1", question="active users today")]
        executed = [("query_database", "revenue by country")]
        kept, skipped = ToolDispatcher.filter_already_executed(calls, executed)
        assert len(kept) == 1
        assert skipped == {}

    def test_only_matches_same_tool(self, monkeypatch):
        from app.agents.tool_dispatcher import ToolDispatcher
        from app.services import text_similarity

        monkeypatch.setattr(text_similarity, "encode_batch", lambda _texts: None)

        calls = [self._tc("1", name="search_codebase", question="revenue by country")]
        executed = [("query_database", "revenue by country")]
        kept, skipped = ToolDispatcher.filter_already_executed(calls, executed)
        # Same question text but a different tool — not deduped.
        assert len(kept) == 1
        assert skipped == {}

    def test_embedding_paraphrase_skipped(self, monkeypatch):
        from app.agents.tool_dispatcher import ToolDispatcher
        from app.services import text_similarity

        def fake_encode(texts):
            mapping = {
                "five highest-revenue clients": [0.98, 0.199, 0.0],
                "top 5 customers by revenue": [1.0, 0.0, 0.0],
            }
            return [mapping.get(t, [0.0, 0.0, 0.0]) for t in texts]

        monkeypatch.setattr(text_similarity, "encode_batch", fake_encode)

        calls = [self._tc("1", question="five highest-revenue clients")]
        executed = [("query_database", "top 5 customers by revenue")]
        kept, skipped = ToolDispatcher.filter_already_executed(calls, executed)
        assert kept == []
        assert "1" in skipped


class TestHistoryBoundaryInPrompt:
    """Verify the orchestrator prompt builder includes focus directives."""

    def test_principles_in_prompt(self):
        from app.agents.prompts.orchestrator_prompt import build_orchestrator_system_prompt

        prompt = build_orchestrator_system_prompt(
            has_connection=True,
            db_type="postgres",
        )
        assert "PRINCIPLES:" in prompt
        assert "query_database" in prompt

    def test_process_data_mentioned_in_prompt(self):
        from app.agents.prompts.orchestrator_prompt import build_orchestrator_system_prompt

        prompt = build_orchestrator_system_prompt(
            has_connection=True,
            db_type="postgres",
        )
        assert "process_data" in prompt

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

    def test_process_data_sequential_guideline(self):
        from app.agents.prompts.orchestrator_prompt import build_orchestrator_system_prompt

        prompt = build_orchestrator_system_prompt(
            has_connection=True,
            db_type="postgres",
        )
        assert "process_data" in prompt
        assert "sequentially" in prompt

    def test_custom_rules_injected_into_prompt(self):
        from app.agents.prompts.orchestrator_prompt import build_orchestrator_system_prompt

        prompt = build_orchestrator_system_prompt(
            has_connection=True,
            db_type="postgres",
            custom_rules="## Custom Rules\n### Revenue\nDivide amount by 100.",
        )
        assert "CUSTOM RULES & BUSINESS LOGIC" in prompt
        assert "Divide amount by 100" in prompt

    def test_custom_rules_empty_omitted(self):
        from app.agents.prompts.orchestrator_prompt import build_orchestrator_system_prompt

        prompt = build_orchestrator_system_prompt(
            has_connection=True,
            db_type="postgres",
            custom_rules="",
        )
        assert "CUSTOM RULES & BUSINESS LOGIC" not in prompt

    def test_custom_rules_placed_after_table_map(self):
        from app.agents.prompts.orchestrator_prompt import build_orchestrator_system_prompt

        prompt = build_orchestrator_system_prompt(
            has_connection=True,
            db_type="postgres",
            table_map="users, orders",
            custom_rules="Some rule",
        )
        tables_pos = prompt.index("DATABASE TABLES")
        rules_pos = prompt.index("CUSTOM RULES & BUSINESS LOGIC")
        assert rules_pos > tables_pos

    def test_rule_freshness_check_present_when_rules(self):
        from app.agents.prompts.orchestrator_prompt import build_orchestrator_system_prompt

        prompt = build_orchestrator_system_prompt(
            has_connection=True,
            custom_rules="Some rule content",
        )
        assert "RULE FRESHNESS CHECK" in prompt

    def test_rule_freshness_check_absent_without_rules(self):
        from app.agents.prompts.orchestrator_prompt import build_orchestrator_system_prompt

        prompt = build_orchestrator_system_prompt(
            has_connection=True,
            custom_rules="",
        )
        assert "RULE FRESHNESS CHECK" not in prompt

    def test_query_planning_mentions_ask_user(self):
        from app.agents.prompts.orchestrator_prompt import build_orchestrator_system_prompt

        prompt = build_orchestrator_system_prompt(
            has_connection=True,
            db_type="postgres",
        )
        assert "ask_user" in prompt
        assert "TABLE RESOLUTION WARNINGS" in prompt or "query_database" in prompt


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
            status: str = "completed"
            final_answer: str = "answer"
            replan_eligible: bool = False
            failed_stage: object = None
            failed_validation: object = None
            data_gate_outcome: object = None

        captured_ctx = {}

        async def _capture_execute(
            _plan,
            context,
            *,
            resume_from=0,
            stage_ctx=None,
            staleness_warning=None,
        ):
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
            patch(
                "app.agents.orchestrator.ResponseBuilder.build_pipeline_response",
                return_value=MagicMock(),
            ),
            patch("app.agents.orchestrator.StageExecutor") as mock_executor_cls,
            patch("app.agents.orchestrator.AdaptivePlanner") as mock_planner_cls,
            patch.object(
                agent._ctx_loader,
                "load_recent_learnings",
                new=AsyncMock(return_value=None),
            ),
        ):
            mock_planner = mock_planner_cls.return_value
            # B1: the complex pipeline must use the public planner (plan()),
            # which injects validation criteria, not the private _llm_plan().
            mock_planner.plan = AsyncMock(return_value=plan)
            mock_planner._llm_plan = AsyncMock(return_value=plan)

            mock_executor = mock_executor_cls.return_value
            mock_executor.execute = AsyncMock(side_effect=_capture_execute)

            await agent._run_complex_pipeline(
                ctx, wf_id="wf-1", table_map="", db_type="postgres", staleness_warning=None
            )

        # B1: public planner used, private one not.
        mock_planner.plan.assert_awaited()
        mock_planner._llm_plan.assert_not_awaited()

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
        result = await agent._dispatcher._handle_process_data(tc, "wf-1")
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
        agent._wf_sql_results["wf-1"] = [sql_res]

        enriched_qr = QueryResult(
            columns=["ip", "amount", "country"],
            rows=[["1.2.3.4", 100, "US"]],
            row_count=1,
        )
        mock_processed = ProcessedData(query_result=enriched_qr, summary="Added country")

        with patch("app.agents.tool_dispatcher.get_data_processor") as mock_gdp:
            mock_gdp.return_value.process.return_value = mock_processed
            tc = ToolCall(
                id="tc1",
                name="process_data",
                arguments={"operation": "ip_to_country", "column": "ip"},
            )
            result_text = await agent._dispatcher._handle_process_data(tc, "wf-1")

        assert sql_res.results is qr_original
        assert agent._wf_sql_results["wf-1"][-1].results is enriched_qr
        assert "Added country" in result_text

    @pytest.mark.asyncio
    async def test_missing_operation_defaults_to_passthrough(self):
        """Re-audit (R5-8 parity): a process_data call with no 'operation'
        must default to passthrough (forward rows unchanged) rather than
        raising a ValueError on the unified dispatcher path."""
        from app.agents.sql_agent import SQLAgentResult
        from app.core.workflow_tracker import WorkflowTracker
        from app.services.data_processor import ProcessedData

        qr = QueryResult(columns=["id"], rows=[[1]], row_count=1)
        sql_res = SQLAgentResult(status="success", query="SELECT 1", results=qr)

        tracker = MagicMock(spec=WorkflowTracker)
        tracker.emit = AsyncMock()
        agent = OrchestratorAgent(llm_router=MagicMock(), workflow_tracker=tracker)
        agent._wf_sql_results["wf-1"] = [sql_res]

        passthrough = ProcessedData(query_result=qr, summary="forwarded unchanged")
        with patch("app.agents.tool_dispatcher.get_data_processor") as mock_gdp:
            mock_gdp.return_value.process.return_value = passthrough
            tc = ToolCall(id="tc1", name="process_data", arguments={})
            result_text = await agent._dispatcher._handle_process_data(tc, "wf-1")

        # The processor was invoked with the passthrough operation, not "".
        _, call_args, _ = mock_gdp.return_value.process.mock_calls[0]
        assert call_args[1] == "passthrough"
        assert "no query results" not in result_text.lower()


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
            patch.object(agent._ctx_loader, "has_mcp_sources", new=AsyncMock(return_value=False)),
            patch.object(
                agent._dispatcher,
                "dispatch",
                new=AsyncMock(return_value=("result text", None)),
            ),
            patch("app.agents.orchestrator.settings") as mock_settings,
            patch("app.agents.orchestrator.time") as mock_time,
        ):
            mock_settings.max_orchestrator_iterations = 10
            mock_settings.max_simple_query_steps = 4
            mock_settings.max_parallel_tool_calls = 1
            mock_settings.history_tail_messages = 4
            mock_settings.agent_wall_clock_timeout_seconds = 30
            mock_settings.max_context_tokens = 8000
            mock_settings.max_history_tokens = 2500
            mock_settings.viz_timeout_seconds = 15
            mock_settings.agent_emergency_synthesis_pct = 0.90
            mock_settings.orchestrator_final_synthesis = True
            mock_settings.orchestrator_pipeline_table_threshold = 3
            mock_settings.answer_validator_enabled = True
            mock_settings.answer_validator_min_chars = 80

            _tick = iter([0.0] + [35.0] * 30)
            mock_time.monotonic = MagicMock(side_effect=_tick)

            await agent.run(ctx)

            assert call_count == 2
            second_call_messages = mock_router.complete.call_args_list[1].kwargs.get(
                "messages",
                mock_router.complete.call_args_list[1][0][0]
                if mock_router.complete.call_args_list[1][0]
                else [],
            )
            synthesis_msgs = [
                m
                for m in second_call_messages
                if m.role == "system"
                and ("TIME LIMIT REACHED" in m.content or "analysis budget" in m.content)
            ]
            assert len(synthesis_msgs) >= 1

    @pytest.mark.asyncio
    async def test_hard_timeout_uses_timeout_text_and_sets_flag(self):
        """Hard wall-clock cutoff uses _build_timeout_text and sets response_type."""
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
            content="",
            tool_calls=[
                ToolCall(
                    id="tc1",
                    name="query_database",
                    arguments={"question": "test query"},
                ),
            ],
            usage={"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        )

        mock_router.complete = AsyncMock(return_value=tool_calls_response)
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
            patch.object(agent._ctx_loader, "has_mcp_sources", new=AsyncMock(return_value=False)),
            patch.object(
                agent._dispatcher,
                "dispatch",
                new=AsyncMock(return_value=("result text", None)),
            ),
            patch("app.agents.orchestrator.settings") as mock_settings,
            patch("app.agents.orchestrator.time") as mock_time,
        ):
            mock_settings.max_orchestrator_iterations = 100
            mock_settings.max_simple_query_steps = 4
            mock_settings.max_parallel_tool_calls = 1
            mock_settings.history_tail_messages = 4
            mock_settings.agent_wall_clock_timeout_seconds = 30
            mock_settings.max_context_tokens = 8000
            mock_settings.max_history_tokens = 2500
            mock_settings.orchestrator_final_synthesis = False
            mock_settings.viz_timeout_seconds = 15
            mock_settings.agent_emergency_synthesis_pct = 0.90
            mock_settings.orchestrator_pipeline_table_threshold = 3
            mock_settings.answer_validator_enabled = True
            mock_settings.answer_validator_min_chars = 80

            _tick = iter([0.0] + [50.0] * 30)
            mock_time.monotonic = MagicMock(side_effect=_tick)

            resp = await agent.run(ctx)

        assert resp.response_type == "step_limit_reached"
        assert "time limit" in resp.answer.lower() or "analysis steps" in resp.answer.lower()


class TestBuildTimeoutText:
    """Tests for _build_timeout_text static method."""

    def test_no_data(self):
        text = OrchestratorAgent._build_timeout_text(None, [])
        assert "time limit" in text.lower()
        assert "analysis steps" not in text.lower()

    def test_with_sql_result(self):
        from app.agents.sql_agent import SQLAgentResult

        qr = QueryResult(columns=["id"], rows=[[1], [2]], row_count=2)
        sql_res = SQLAgentResult(status="success", query="SELECT 1", results=qr)
        text = OrchestratorAgent._build_timeout_text(sql_res, [])
        assert "time limit" in text.lower()
        assert "2 rows" in text

    def test_with_knowledge_sources(self):
        from app.core.types import RAGSource

        sources = [RAGSource(source_path="a.md"), RAGSource(source_path="b.md")]
        text = OrchestratorAgent._build_timeout_text(None, sources)
        assert "time limit" in text.lower()
        assert "2 relevant document" in text


class TestBuildPartialText:
    """Tests for _build_partial_text static method."""

    def test_no_data(self):
        text = OrchestratorAgent._build_partial_text(None, [])
        assert "maximum number of analysis steps" in text.lower()

    def test_with_sql_result(self):
        from app.agents.sql_agent import SQLAgentResult

        qr = QueryResult(columns=["id"], rows=[[1]], row_count=1)
        sql_res = SQLAgentResult(status="success", query="SELECT 1", results=qr)
        text = OrchestratorAgent._build_partial_text(sql_res, [])
        assert "1 rows" in text or "1 row" in text

    def test_with_knowledge_sources(self):
        from app.core.types import RAGSource

        sources = [RAGSource(source_path="a.md")]
        text = OrchestratorAgent._build_partial_text(None, sources)
        assert "1 relevant document" in text


class TestSQLResultBlock:
    """Tests for the SQLResultBlock dataclass and compound sql_results."""

    def test_defaults(self):
        block = SQLResultBlock()
        assert block.query is None
        assert block.results is None
        assert block.viz_type == "table"
        assert block.viz_config == {}
        assert block.insights == []

    def test_agent_response_sql_results_default_empty(self):
        resp = AgentResponse(answer="hello")
        assert resp.sql_results == []

    def test_agent_response_with_multiple_blocks(self):
        qr1 = QueryResult(columns=["a"], rows=[[1]], row_count=1)
        qr2 = QueryResult(columns=["b"], rows=[[2]], row_count=1)
        blocks = [
            SQLResultBlock(query="SELECT a", results=qr1, viz_type="bar_chart"),
            SQLResultBlock(query="SELECT b", results=qr2, viz_type="pie_chart"),
        ]
        resp = AgentResponse(
            answer="Two queries",
            query="SELECT b",
            results=qr2,
            sql_results=blocks,
        )
        assert len(resp.sql_results) == 2
        assert resp.sql_results[0].query == "SELECT a"
        assert resp.sql_results[0].viz_type == "bar_chart"
        assert resp.sql_results[1].query == "SELECT b"
        assert resp.sql_results[1].viz_type == "pie_chart"
        assert resp.query == "SELECT b"
        assert resp.results is qr2


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
        """A greeting should be routed as direct and skip heavy context."""
        mock_llm.complete = AsyncMock(
            side_effect=[
                LLMResponse(
                    content=(
                        '{"route": "direct", "complexity": "simple", '
                        '"approach": "Greeting", "estimated_queries": 0, '
                        '"needs_multiple_data_sources": false}'
                    )
                ),
                LLMResponse(content="Hello! I am your data assistant."),
            ]
        )
        with (
            patch(
                "app.agents.context_loader.ContextLoader.has_mcp_sources",
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
    async def test_run_does_not_resurrect_enriched_cache(self, orch, mock_llm, base_context):
        """B4: a fresh wf_id never reuses a prior _wf_enriched entry.

        wf_id is minted per request, so the old cross-turn reuse block at the
        top of run() always missed; pre-seeding it must not leak into the
        current run's _wf_sql_results. The anti-leak cleanup still prunes.
        """
        import time as _t

        from app.agents.sql_agent import SQLAgentResult

        stale_marker = SQLAgentResult(query="SELECT 1")
        orch._wf_enriched["wf-1"] = (stale_marker, _t.time())  # fresh, same wf id

        mock_llm.complete = AsyncMock(
            side_effect=[
                LLMResponse(
                    content=(
                        '{"route": "direct", "complexity": "simple", '
                        '"approach": "Greeting", "estimated_queries": 0, '
                        '"needs_multiple_data_sources": false}'
                    )
                ),
                LLMResponse(content="Hi there."),
            ]
        )
        with patch(
            "app.agents.context_loader.ContextLoader.has_mcp_sources",
            new_callable=AsyncMock,
            return_value=False,
        ):
            await orch.run(base_context)

        # Pre-fix the dead block seeded _wf_sql_results["wf-1"] from _wf_enriched.
        assert "wf-1" not in orch._wf_sql_results

    @pytest.mark.asyncio
    async def test_single_call_dispatch_survives_exception(self, orch, mock_llm, base_context):
        """B2: an unexpected exception in a single-tool-call turn must not crash
        the turn — it is folded into a directive and the loop continues."""
        from app.agents.tools.orchestrator_tools import get_orchestrator_tools
        from app.llm.base import LLMResponse, ToolCall

        mock_llm.complete = AsyncMock(
            side_effect=[
                LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCall(id="t1", name="search_codebase", arguments={"question": "x"})
                    ],
                ),
                LLMResponse(content="Final answer based on what I have."),
            ]
        )
        orch._dispatcher.dispatch = AsyncMock(side_effect=RuntimeError("boom"))

        tools = get_orchestrator_tools(has_knowledge_base=True)
        resp = await orch._run_tool_loop(
            base_context,
            "wf-1",
            has_connection=False,
            db_type=None,
            has_kb=True,
            has_mcp=False,
            has_repo=False,
            table_map="",
            project_overview=None,
            recent_learnings=None,
            custom_rules="",
            tools=tools,
            staleness_warning=None,
            route_result=None,
        )

        # Turn survived (no raise) and produced the final answer.
        assert resp.answer == "Final answer based on what I have."
        # The failure was surfaced to the model as a tool message directive.
        second_call_msgs = mock_llm.complete.call_args_list[1].kwargs["messages"]
        assert any(
            m.role == "tool" and "failed" in (m.content or "").lower() for m in second_call_msgs
        )

    @pytest.mark.asyncio
    async def test_budget_marker_does_not_accumulate(self, orch, mock_llm, base_context):
        """I4/B3: the per-iteration [Budget: marker is replaced, not stacked.

        Otherwise the native Anthropic path (which folds all system messages
        together) accumulates a pile of stale budget lines.
        """
        from app.agents.tools.orchestrator_tools import get_orchestrator_tools
        from app.llm.base import LLMResponse, ToolCall

        def _tc(i):
            return LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(id=f"t{i}", name="search_codebase", arguments={"question": f"q{i}"})
                ],
            )

        mock_llm.complete = AsyncMock(
            side_effect=[_tc(0), _tc(1), _tc(2), LLMResponse(content="Done.")]
        )
        orch._dispatcher.dispatch = AsyncMock(return_value=("ok result", None))

        tools = get_orchestrator_tools(has_knowledge_base=True)
        await orch._run_tool_loop(
            base_context,
            "wf-1",
            has_connection=False,
            db_type=None,
            has_kb=True,
            has_mcp=False,
            has_repo=False,
            table_map="",
            project_overview=None,
            recent_learnings=None,
            custom_rules="",
            tools=tools,
            staleness_warning=None,
            route_result=None,
        )

        final_msgs = mock_llm.complete.call_args_list[-1].kwargs["messages"]
        budget_count = sum(
            1
            for m in final_msgs
            if m.role == "system" and (m.content or "").startswith("[Budget:")
        )
        assert budget_count <= 1, f"expected <=1 budget marker, got {budget_count}"

    @pytest.mark.asyncio
    async def test_answer_gate_downgrades_suspicious_normal_completion(
        self, orch, mock_llm, base_context
    ):
        """I6: a suspicious (zero-row) normal completion whose answer is judged
        inadequate is downgraded to a continuable response_type."""
        from app.agents.sql_agent import SQLAgentResult
        from app.agents.tools.orchestrator_tools import get_orchestrator_tools
        from app.connectors.base import QueryResult
        from app.llm.base import LLMResponse, ToolCall

        empty_sql = SQLAgentResult(
            status="success",
            query="SELECT count(*) FROM t",
            results=QueryResult(columns=["c"], rows=[], row_count=0),
        )
        mock_llm.complete = AsyncMock(
            side_effect=[
                LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCall(id="t1", name="query_database", arguments={"question": "how many"})
                    ],
                ),
                LLMResponse(content="There are plenty of records."),
            ]
        )
        orch._dispatcher.dispatch = AsyncMock(return_value=("0 rows", empty_sql))
        orch._validate_partial_answer = AsyncMock(return_value=False)

        tools = get_orchestrator_tools(has_connection=True)
        resp = await orch._run_tool_loop(
            base_context,
            "wf-1",
            has_connection=True,
            db_type="postgres",
            has_kb=False,
            has_mcp=False,
            has_repo=False,
            table_map="",
            project_overview=None,
            recent_learnings=None,
            custom_rules="",
            tools=tools,
            staleness_warning=None,
            route_result=None,
        )

        orch._validate_partial_answer.assert_awaited()
        assert resp.response_type == "step_limit_reached"

    @pytest.mark.asyncio
    async def test_answer_gate_skipped_on_clean_normal_completion(
        self, orch, mock_llm, base_context
    ):
        """I6 cost guard: a clean, non-suspicious result makes NO answer-gate
        call on the normal completion path."""
        from app.agents.sql_agent import SQLAgentResult
        from app.agents.tools.orchestrator_tools import get_orchestrator_tools
        from app.connectors.base import QueryResult
        from app.llm.base import LLMResponse, ToolCall

        good_sql = SQLAgentResult(
            status="success",
            query="SELECT * FROM t",
            results=QueryResult(columns=["c"], rows=[[1], [2]], row_count=2),
        )
        mock_llm.complete = AsyncMock(
            side_effect=[
                LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCall(id="t1", name="query_database", arguments={"question": "list"})
                    ],
                ),
                LLMResponse(content="Here are the two records."),
            ]
        )
        orch._dispatcher.dispatch = AsyncMock(return_value=("2 rows", good_sql))
        orch._validate_partial_answer = AsyncMock(return_value=True)
        viz = MagicMock()
        viz.viz_type = "table"
        viz.viz_config = {}
        viz.token_usage = {}
        orch._viz.run = AsyncMock(return_value=viz)

        tools = get_orchestrator_tools(has_connection=True)
        resp = await orch._run_tool_loop(
            base_context,
            "wf-1",
            has_connection=True,
            db_type="postgres",
            has_kb=False,
            has_mcp=False,
            has_repo=False,
            table_map="",
            project_overview=None,
            recent_learnings=None,
            custom_rules="",
            tools=tools,
            staleness_warning=None,
            route_result=None,
        )

        orch._validate_partial_answer.assert_not_awaited()
        assert resp.response_type == "sql_result"

    @pytest.mark.asyncio
    async def test_fallback_on_router_error(self, orch, mock_llm, base_context):
        """If router fails, the orchestrator should fall back to unified agent."""
        mock_llm.complete = AsyncMock(
            side_effect=[
                RuntimeError("LLM is down"),
                LLMResponse(content="I can help with data analysis."),
            ]
        )
        with (
            patch(
                "app.agents.context_loader.ContextLoader.has_mcp_sources",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.agents.context_loader.ContextLoader.check_staleness",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.agents.context_loader.ContextLoader.load_project_overview",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.agents.context_loader.ContextLoader.load_recent_learnings",
                new_callable=AsyncMock,
                return_value=None,
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
                LLMResponse(
                    content=(
                        '{"route": "query", "complexity": "simple", '
                        '"approach": "Count users", "estimated_queries": 1, '
                        '"needs_multiple_data_sources": false}'
                    )
                ),
                LLMResponse(content="There are 42 users in the database."),
            ]
        )
        with (
            patch(
                "app.agents.context_loader.ContextLoader.has_mcp_sources",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.agents.context_loader.ContextLoader.build_table_map",
                new_callable=AsyncMock,
                return_value="users: id, email",
            ),
            patch(
                "app.agents.context_loader.ContextLoader.load_project_overview",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.agents.context_loader.ContextLoader.load_recent_learnings",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            resp = await orch.run(ctx)

        assert resp.response_type == "text"
        assert "42" in resp.answer

    @pytest.mark.asyncio
    async def test_data_query_loads_custom_rules(self, orch, mock_llm, base_context):
        """Data queries should load custom rules into the orchestrator system prompt."""
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
            user_question="What is total revenue?",
            chat_history=[],
            llm_router=mock_llm,
            tracker=base_context.tracker,
            workflow_id="wf-1",
            project_name="TestProject",
        )

        mock_llm.complete = AsyncMock(
            side_effect=[
                LLMResponse(
                    content=(
                        '{"route": "query", "complexity": "simple", '
                        '"approach": "Revenue lookup", "estimated_queries": 1, '
                        '"needs_multiple_data_sources": false}'
                    )
                ),
                LLMResponse(content="Revenue is $42."),
            ]
        )

        with (
            patch(
                "app.agents.context_loader.ContextLoader.has_mcp_sources",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.agents.context_loader.ContextLoader.build_table_map",
                new_callable=AsyncMock,
                return_value="orders: id, amount",
            ),
            patch(
                "app.agents.context_loader.ContextLoader.load_project_overview",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.agents.context_loader.ContextLoader.load_recent_learnings",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch.object(
                orch,
                "_load_custom_rules_text",
                new_callable=AsyncMock,
                return_value="## Custom Rules\n### Revenue\nDivide amount by 100.",
            ) as mock_load_rules,
        ):
            await orch.run(ctx)

        mock_load_rules.assert_called_once_with("test-proj")
        second_call_kwargs = mock_llm.complete.call_args_list[1].kwargs
        messages = second_call_kwargs.get("messages", [])
        system_msg = messages[0]
        assert "CUSTOM RULES & BUSINESS LOGIC" in system_msg.content
        assert "Divide amount by 100" in system_msg.content

    @pytest.mark.asyncio
    async def test_knowledge_query_path(self, orch, mock_llm, base_context, mock_vs):
        """A code question should only load KB context, not DB context."""
        collection = MagicMock()
        collection.count = MagicMock(return_value=5)
        mock_vs.get_or_create_collection = MagicMock(return_value=collection)

        mock_llm.complete = AsyncMock(
            side_effect=[
                LLMResponse(
                    content=(
                        '{"route": "knowledge", "complexity": "simple", '
                        '"approach": "Look up User model", "estimated_queries": 0, '
                        '"needs_multiple_data_sources": false}'
                    )
                ),
                LLMResponse(content="The User model has fields id, email, name."),
            ]
        )
        base_context.user_question = "What does the User model look like?"

        with (
            patch(
                "app.agents.context_loader.ContextLoader.has_mcp_sources",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.agents.context_loader.ContextLoader.check_staleness",
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
                LLMResponse(
                    content=(
                        '{"route": "direct", "complexity": "simple", '
                        '"approach": "Meta question", "estimated_queries": 0, '
                        '"needs_multiple_data_sources": false}'
                    )
                ),
                LLMResponse(content="I can help you explore your data."),
            ]
        )
        with (
            patch(
                "app.agents.context_loader.ContextLoader.has_mcp_sources",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.agents.context_loader.ContextLoader.build_table_map",
                new_callable=AsyncMock,
            ) as mock_table_map,
            patch(
                "app.agents.context_loader.ContextLoader.load_project_overview",
                new_callable=AsyncMock,
            ) as mock_overview,
            patch(
                "app.agents.context_loader.ContextLoader.load_recent_learnings",
                new_callable=AsyncMock,
            ) as mock_learnings,
        ):
            base_context.user_question = "What can you do?"
            await orch.run(base_context)

        mock_table_map.assert_not_called()
        mock_overview.assert_not_called()
        mock_learnings.assert_not_called()


class TestBuildSqlResultsPayload:
    """Tests for the _build_sql_results_payload helper in chat.py."""

    def test_returns_none_for_single_block(self):
        from app.api.routes.chat import _build_sql_results_payload

        qr = QueryResult(columns=["a"], rows=[[1]], row_count=1)
        block = SQLResultBlock(query="SELECT 1", results=qr)
        assert _build_sql_results_payload([block]) is None

    def test_returns_none_for_empty(self):
        from app.api.routes.chat import _build_sql_results_payload

        assert _build_sql_results_payload([]) is None

    def test_returns_list_for_two_blocks(self):
        from app.api.routes.chat import _build_sql_results_payload

        qr1 = QueryResult(columns=["x"], rows=[[1], [2]], row_count=2)
        qr2 = QueryResult(columns=["y"], rows=[[3]], row_count=1)
        blocks = [
            SQLResultBlock(
                query="SELECT x",
                query_explanation="first",
                results=qr1,
                viz_type="bar_chart",
            ),
            SQLResultBlock(
                query="SELECT y",
                query_explanation="second",
                results=qr2,
                viz_type="pie_chart",
            ),
        ]
        result = _build_sql_results_payload(blocks, "test answer")
        assert result is not None
        assert len(result) == 2
        assert result[0]["query"] == "SELECT x"
        assert result[0]["query_explanation"] == "first"
        assert result[0]["raw_result"]["columns"] == ["x"]
        assert result[0]["raw_result"]["total_rows"] == 2
        assert result[1]["query"] == "SELECT y"
        assert result[1]["raw_result"]["total_rows"] == 1
        for blk_dict in result:
            assert "visualization" in blk_dict
            assert "insights" in blk_dict


class TestApplyContinuationContext:
    """Tests for _apply_continuation_context producing structured continuation summaries."""

    def _make_context(self, question="Show me sales", extra=None):
        from app.agents.base import AgentContext

        mock_llm = MagicMock()
        mock_tracker = MagicMock()
        return AgentContext(
            project_id="test-proj",
            connection_config=None,
            user_question=question,
            chat_history=[],
            llm_router=mock_llm,
            tracker=mock_tracker,
            workflow_id="wf-test",
            extra=extra or {},
        )

    def test_with_rich_continuation_context(self):
        import json

        continuation = json.dumps(
            {
                "sql_queries": [
                    {
                        "query": "SELECT product, SUM(amount) FROM sales GROUP BY product",
                        "row_count": 5,
                        "columns": ["product", "total"],
                        "sample_rows": [["Widget", 1000], ["Gadget", 2000]],
                        "explanation": "Aggregate sales by product",
                    }
                ],
                "tool_call_log": [
                    {
                        "tool": "query_database",
                        "arguments": "{}",
                        "result_preview": "5 rows returned",
                    },
                ],
                "partial_answer": "Based on the data, Widget has 1000 in sales...",
                "knowledge_source_count": 0,
                "steps_used": 15,
                "steps_total": 15,
            }
        )
        ctx = self._make_context(
            extra={
                "pipeline_action": "continue_analysis",
                "continuation_context": continuation,
            }
        )

        result = OrchestratorAgent._apply_continuation_context(ctx)

        summary = result.extra.get("_continuation_summary", "")
        assert "CONTINUATION" in summary
        assert "Do NOT re-execute" in summary
        assert "SELECT product, SUM(amount)" in summary
        assert "5 rows" in summary
        assert "product, total" in summary
        assert "Widget" in summary
        assert "15/15 steps" in summary
        assert "partial_answer" not in summary or "Based on the data" in summary
        assert "pipeline_action" not in result.extra

    def test_without_continuation_context(self):
        ctx = self._make_context(extra={"pipeline_action": "continue_analysis"})

        result = OrchestratorAgent._apply_continuation_context(ctx)

        summary = result.extra.get("_continuation_summary", "")
        assert "CONTINUATION" in summary
        assert "pipeline_action" not in result.extra

    def test_user_question_unchanged(self):
        ctx = self._make_context(
            question="Show me sales",
            extra={"pipeline_action": "continue_analysis"},
        )

        result = OrchestratorAgent._apply_continuation_context(ctx)

        assert result.user_question == "Show me sales"

    def test_malformed_json_handled_gracefully(self):
        ctx = self._make_context(
            extra={
                "pipeline_action": "continue_analysis",
                "continuation_context": "not-valid-json{",
            }
        )

        result = OrchestratorAgent._apply_continuation_context(ctx)

        summary = result.extra.get("_continuation_summary", "")
        assert "CONTINUATION" in summary


class TestContinuationSkipsClassification:
    """Verify that continue_analysis skips intent classification and goes to full pipeline."""

    @pytest.fixture
    def mock_llm(self):
        llm = MagicMock()
        llm.complete = AsyncMock()
        llm.get_context_window = MagicMock(return_value=128000)
        return llm

    @pytest.fixture
    def mock_tracker(self):
        tracker = MagicMock()
        tracker.start = AsyncMock()
        tracker.end = AsyncMock()
        tracker.emit = AsyncMock()
        tracker.step = MagicMock()
        step_cm = AsyncMock()
        step_cm.__aenter__ = AsyncMock(return_value=None)
        step_cm.__aexit__ = AsyncMock(return_value=False)
        tracker.step.return_value = step_cm
        return tracker

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

    @pytest.mark.asyncio
    async def test_continue_analysis_skips_intent(self, orch, mock_llm, mock_tracker):
        from app.agents.base import AgentContext

        ctx = AgentContext(
            project_id="test-proj",
            connection_config=ConnectionConfig(
                db_type="postgres",
                db_host="localhost",
                db_port=5432,
                db_name="testdb",
                db_user="user",
            ),
            user_question="Show me monthly revenue",
            chat_history=[],
            llm_router=mock_llm,
            tracker=mock_tracker,
            workflow_id="wf-cont",
            extra={
                "pipeline_action": "continue_analysis",
                "continuation_context": (
                    '{"sql_queries": [], "tool_call_log": [],'
                    ' "partial_answer": "", "steps_used": 10,'
                    ' "steps_total": 15}'
                ),
            },
        )

        with (
            patch(
                "app.agents.context_loader.ContextLoader.has_mcp_sources",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.agents.orchestrator.OrchestratorAgent._run_unified_agent",
                new_callable=AsyncMock,
                return_value=AgentResponse(answer="Continued analysis"),
            ) as mock_unified,
            patch(
                "app.agents.orchestrator.route_request",
                new_callable=AsyncMock,
            ) as mock_route,
        ):
            resp = await orch.run(ctx)

        mock_route.assert_not_called()
        mock_unified.assert_called_once()
        assert resp.answer == "Continued analysis"


# ------------------------------------------------------------------
# Two-phase loop and synthesis tests
# ------------------------------------------------------------------


class TestSynthesisPhaseToolStrip:
    """Verify that during synthesis phase, tools are stripped from the LLM call."""

    @pytest.mark.asyncio
    async def test_synthesis_phase_strips_tools(self):
        """When synthesis deadline is reached, LLM call should have tools=None."""
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
            content="Here is the complete answer based on data gathered.",
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
            patch.object(agent._ctx_loader, "has_mcp_sources", new=AsyncMock(return_value=False)),
            patch.object(
                agent._dispatcher,
                "dispatch",
                new=AsyncMock(return_value=("result text", None)),
            ),
            patch("app.agents.orchestrator.settings") as mock_settings,
            patch("app.agents.orchestrator.time") as mock_time,
        ):
            mock_settings.max_orchestrator_iterations = 10
            mock_settings.max_parallel_tool_calls = 1
            mock_settings.agent_wall_clock_timeout_seconds = 100
            mock_settings.max_context_tokens = 8000
            mock_settings.max_history_tokens = 2500
            mock_settings.viz_timeout_seconds = 15
            mock_settings.agent_emergency_synthesis_pct = 0.90
            mock_settings.orchestrator_final_synthesis = True
            mock_settings.orchestrator_pipeline_table_threshold = 3
            mock_settings.answer_validator_enabled = True
            mock_settings.answer_validator_min_chars = 80

            _tick = iter([0.0] + [95.0] * 30)
            mock_time.monotonic = MagicMock(side_effect=_tick)

            await agent.run(ctx)

            assert call_count == 2
            second_call_kwargs = mock_router.complete.call_args_list[1].kwargs
            assert second_call_kwargs.get("tools") is None


class TestResponseTypeWithData:
    """Verify response_type is sql_result when data exists even after step limit."""

    def test_determine_response_type_sql(self):
        from app.agents.sql_agent import SQLAgentResult

        sql_res = SQLAgentResult(
            status="success",
            query="SELECT 1",
            results=QueryResult(columns=["a"], rows=[[1]], row_count=1),
        )
        result = ResponseBuilder.determine_response_type(sql_res, [])
        assert result == "sql_result"


class TestBuildSynthesisMessagesEnhanced:
    """Tests for the enhanced build_synthesis_messages with all_sql_results."""

    def test_includes_all_sql_results(self):
        from app.agents.sql_agent import SQLAgentResult

        sr1 = SQLAgentResult(
            status="success",
            query="SELECT month, revenue FROM sales",
            query_explanation="Monthly revenue",
            results=QueryResult(
                columns=["month", "revenue"],
                rows=[["Jan", 1000], ["Feb", 2000]],
                row_count=2,
            ),
        )
        sr2 = SQLAgentResult(
            status="success",
            query="SELECT method, total FROM payments",
            query_explanation="Payment methods",
            results=QueryResult(
                columns=["method", "total"],
                rows=[["card", 5000], ["cash", 3000]],
                row_count=2,
            ),
        )

        messages = [
            Message(role="system", content="You are a data assistant."),
            Message(role="user", content="Revenue analysis by payment method"),
        ]

        result = ResponseBuilder.build_synthesis_messages(
            messages,
            sr2,
            [],
            32000,
            all_sql_results=[sr1, sr2],
        )

        assert len(result) == 2
        user_msg = result[1].content
        assert "SELECT month, revenue" in user_msg
        assert "SELECT method, total" in user_msg
        assert "Monthly revenue" in user_msg
        assert "Payment methods" in user_msg
        assert "reached its step limit" not in user_msg
        assert "analysis is incomplete" not in user_msg

    def test_prompt_instructs_no_limits_mention(self):
        messages = [
            Message(role="system", content="You are a data assistant."),
            Message(role="user", content="Show me data"),
        ]
        result = ResponseBuilder.build_synthesis_messages(
            messages,
            None,
            [],
            32000,
        )
        user_msg = result[1].content
        assert "Do NOT mention step limits" in user_msg
        assert "complete answer" in user_msg.lower()

    def test_synthesis_instructs_user_language(self):
        messages = [
            Message(role="system", content="You are a data assistant."),
            Message(role="user", content="Покажи продажи"),
        ]
        result = ResponseBuilder.build_synthesis_messages(
            messages,
            None,
            [],
            32000,
        )
        user_msg = result[1].content
        assert "SAME language as the original question" in user_msg


class TestDispatcherRemainingWall:
    """Verify ToolDispatcher.dispatch passes remaining_wall_seconds to SQL agent."""

    @pytest.mark.asyncio
    async def test_dispatch_passes_wall_seconds_to_sql_agent(self):
        from app.agents.base import AgentContext
        from app.agents.sql_agent import SQLAgent, SQLAgentResult
        from app.agents.tool_dispatcher import ToolDispatcher
        from app.agents.validation import AgentResultValidator
        from app.core.workflow_tracker import WorkflowTracker

        mock_sql = MagicMock(spec=SQLAgent)
        mock_sql.run = AsyncMock(
            return_value=SQLAgentResult(
                status="success",
                query="SELECT 1",
                results=QueryResult(columns=["a"], rows=[[1]], row_count=1),
            )
        )

        mock_tracker = MagicMock(spec=WorkflowTracker)
        mock_tracker.emit = AsyncMock()
        mock_tracker.step = MagicMock()
        mock_tracker.step.return_value.__aenter__ = AsyncMock()
        mock_tracker.step.return_value.__aexit__ = AsyncMock()

        mock_validator = MagicMock(spec=AgentResultValidator)
        mock_validator.validate_sql_result = MagicMock(
            return_value=MagicMock(passed=True, warnings=[], errors=[])
        )

        dispatcher = ToolDispatcher(
            sql_agent=mock_sql,
            knowledge_agent=MagicMock(),
            mcp_source_agent=MagicMock(),
            validator=mock_validator,
            tracker=mock_tracker,
            wf_sql_results={},
            wf_enriched={},
        )

        ctx = AgentContext(
            project_id="p1",
            connection_config=None,
            user_question="test",
            chat_history=[],
            llm_router=MagicMock(),
            tracker=mock_tracker,
            workflow_id="wf-1",
        )

        tc = ToolCall(id="tc1", name="query_database", arguments={"question": "test"})
        await dispatcher.dispatch(tc, ctx, "wf-1", {}, remaining_wall_seconds=45.0)

        mock_sql.run.assert_called_once()
        call_kwargs = mock_sql.run.call_args.kwargs
        assert call_kwargs.get("wall_clock_remaining") == 45.0


class TestDispatcherErrorContextRetry:
    """R5-4: SQL retry injects prior errors into the question."""

    def test_augment_question_with_error(self):
        from app.agents.tool_dispatcher import ToolDispatcher

        out = ToolDispatcher._augment_question_with_error("list users", ["unknown column 'usr_id'"])
        assert "list users" in out
        assert "PREVIOUS ATTEMPT FAILED" in out
        assert "usr_id" in out

    def test_augment_question_noop_without_errors(self):
        from app.agents.tool_dispatcher import ToolDispatcher

        assert ToolDispatcher._augment_question_with_error("q", []) == "q"
        assert ToolDispatcher._augment_question_with_error("q", [""]) == "q"

    @pytest.mark.asyncio
    async def test_retry_feeds_error_context_into_second_call(self):
        from app.agents.base import AgentContext
        from app.agents.sql_agent import SQLAgent, SQLAgentResult
        from app.agents.tool_dispatcher import ToolDispatcher
        from app.agents.validation import AgentResultValidator

        good = SQLAgentResult(
            status="success",
            query="SELECT 1",
            results=QueryResult(columns=["a"], rows=[[1]], row_count=1),
        )
        bad = SQLAgentResult(status="error", query=None, results=None, error="boom")

        mock_sql = MagicMock(spec=SQLAgent)
        mock_sql.run = AsyncMock(side_effect=[bad, good])

        mock_tracker = MagicMock(spec=WorkflowTracker)
        mock_tracker.emit = AsyncMock()
        mock_tracker.step = MagicMock()
        mock_tracker.step.return_value.__aenter__ = AsyncMock()
        mock_tracker.step.return_value.__aexit__ = AsyncMock()

        mock_validator = MagicMock(spec=AgentResultValidator)
        mock_validator.validate_sql_result = MagicMock(
            side_effect=[
                MagicMock(passed=False, warnings=[], errors=["unknown column"]),
                MagicMock(passed=True, warnings=[], errors=[]),
            ]
        )

        dispatcher = ToolDispatcher(
            sql_agent=mock_sql,
            knowledge_agent=MagicMock(),
            mcp_source_agent=MagicMock(),
            validator=mock_validator,
            tracker=mock_tracker,
            wf_sql_results={},
            wf_enriched={},
        )
        ctx = AgentContext(
            project_id="p1",
            connection_config=None,
            user_question="orig question",
            chat_history=[],
            llm_router=MagicMock(),
            tracker=mock_tracker,
            workflow_id="wf-1",
        )
        tc = ToolCall(id="tc1", name="query_database", arguments={"question": "orig question"})
        await dispatcher.dispatch(tc, ctx, "wf-1", {})

        assert mock_sql.run.call_count == 2
        first_q = mock_sql.run.call_args_list[0].kwargs["question"]
        second_q = mock_sql.run.call_args_list[1].kwargs["question"]
        assert first_q == "orig question"
        assert "PREVIOUS ATTEMPT FAILED" in second_q
        assert "unknown column" in second_q


class TestSqlAgentTimeBudget:
    """Verify SQL agent caps query timeout based on wall_clock_remaining."""

    def test_timeout_capped_by_wall_clock(self):
        from app.agents.sql_agent import SQLAgent

        agent = SQLAgent(
            llm_router=MagicMock(),
            vector_store=MagicMock(),
            rules_engine=MagicMock(),
        )
        agent._wall_clock_remaining = 20.0
        config = agent._build_validation_config()
        assert config.query_timeout_seconds <= 10

    def test_timeout_not_capped_when_no_wall_clock(self):
        from app.agents.sql_agent import SQLAgent

        agent = SQLAgent(
            llm_router=MagicMock(),
            vector_store=MagicMock(),
            rules_engine=MagicMock(),
        )
        agent._wall_clock_remaining = None
        config = agent._build_validation_config()
        assert config.query_timeout_seconds == 30

    def test_timeout_minimum_floor(self):
        from app.agents.sql_agent import SQLAgent

        agent = SQLAgent(
            llm_router=MagicMock(),
            vector_store=MagicMock(),
            rules_engine=MagicMock(),
        )
        agent._wall_clock_remaining = 2.0
        config = agent._build_validation_config()
        assert config.query_timeout_seconds >= 5


class TestToolLoopMessageRoles:
    """Anthropic outage regression: the tool loop must never build a non-leading
    ``system`` message, even with chat history and a continuation summary.

    Anthropic/Bedrock via OpenRouter 400 on a mid-conversation ``system`` role,
    which previously broke every multi-turn chat.
    """

    @pytest.mark.asyncio
    async def test_no_midconversation_system_message(self):
        from app.agents.base import AgentContext
        from app.core.workflow_tracker import WorkflowTracker

        mock_router = MagicMock()
        mock_tracker = MagicMock(spec=WorkflowTracker)
        mock_tracker.emit = AsyncMock()
        mock_tracker.step = MagicMock()
        mock_tracker.step.return_value.__aenter__ = AsyncMock()
        mock_tracker.step.return_value.__aexit__ = AsyncMock()
        mock_tracker.start = AsyncMock(return_value="wf-roles")
        mock_tracker.end = AsyncMock()

        # First (and only) LLM call returns a plain answer -> loop exits at once.
        final_response = LLMResponse(
            content="Here is the answer.",
            tool_calls=[],
            usage={"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        )
        mock_router.complete = AsyncMock(return_value=final_response)
        mock_router.get_context_window = MagicMock(return_value=128_000)

        agent = OrchestratorAgent(
            llm_router=mock_router,
            workflow_tracker=mock_tracker,
        )

        history = [
            Message(role="user", content="previous question"),
            Message(role="assistant", content="previous answer"),
        ]
        ctx = AgentContext(
            project_id="p1",
            connection_config=None,
            user_question="follow-up question",
            chat_history=history,
            llm_router=mock_router,
            tracker=mock_tracker,
            workflow_id="wf-roles",
            extra={
                "_skip_complexity": True,
                "_continuation_summary": "PRIOR WORK SUMMARY",
            },
        )

        with (
            patch.object(agent._ctx_loader, "has_mcp_sources", new=AsyncMock(return_value=False)),
            patch("app.agents.orchestrator.settings") as mock_settings,
            patch("app.agents.orchestrator.time") as mock_time,
        ):
            mock_settings.max_orchestrator_iterations = 10
            mock_settings.max_simple_query_steps = 4
            mock_settings.max_parallel_tool_calls = 1
            mock_settings.history_tail_messages = 4
            mock_settings.agent_wall_clock_timeout_seconds = 600
            mock_settings.max_context_tokens = 128_000
            mock_settings.max_history_tokens = 25_000
            mock_settings.viz_timeout_seconds = 15
            mock_settings.agent_emergency_synthesis_pct = 0.90
            mock_settings.orchestrator_final_synthesis = False
            mock_settings.orchestrator_pipeline_table_threshold = 3
            mock_settings.answer_validator_enabled = False
            mock_settings.answer_validator_min_chars = 80

            mock_time.monotonic = MagicMock(return_value=0.0)

            await agent.run(ctx)

        assert mock_router.complete.call_count >= 1
        first_messages = mock_router.complete.call_args_list[0].kwargs["messages"]
        # Leading message is the only system role.
        assert first_messages[0].role == "system"
        assert all(m.role != "system" for m in first_messages[1:])
        # The final user turn carries the folded marker + continuation summary.
        last = first_messages[-1]
        assert last.role == "user"
        assert "END OF CONVERSATION HISTORY" in last.content
        assert "PRIOR WORK SUMMARY" in last.content
        assert "NEW USER MESSAGE" in last.content
        assert "follow-up question" in last.content


class TestUnifiedResultGate:
    """R5-3: orchestrator-level result-quality gate on the unified tool loop."""

    def _agent(self):
        tracker = MagicMock(spec=WorkflowTracker)
        tracker.emit = AsyncMock()
        return OrchestratorAgent(llm_router=MagicMock(), workflow_tracker=tracker)

    def test_hard_failure_emits_directive_and_counts(self):
        from app.agents.sql_agent import SQLAgentResult

        agent = self._agent()
        # No query produced -> validator fails -> hard directive.
        bad = SQLAgentResult(status="success", query=None, results=None)
        directive = agent._result_gate_directive("wf-1", bad)
        assert directive is not None
        assert "RESULT CHECK FAILED" in directive
        assert agent._wf_correction_counts["wf-1"] == 1

    def test_budget_exhausts_after_max_corrections(self):
        from app.agents.sql_agent import SQLAgentResult

        agent = self._agent()
        bad = SQLAgentResult(status="error", query=None, results=None, error="boom")
        budget = settings.orchestrator_max_result_corrections
        for _ in range(budget):
            assert agent._result_gate_directive("wf-9", bad) is not None
        # Budget spent -> no further directives.
        assert agent._result_gate_directive("wf-9", bad) is None
        assert agent._wf_correction_counts["wf-9"] == budget

    def test_good_result_no_directive(self):
        from app.agents.sql_agent import SQLAgentResult

        agent = self._agent()
        qr = QueryResult(columns=["n"], rows=[[1]], row_count=1)
        ok = SQLAgentResult(status="success", query="SELECT 1", results=qr)
        assert agent._result_gate_directive("wf-2", ok) is None

    def test_empty_result_soft_directive_only_when_enabled(self, monkeypatch):
        from app.agents.sql_agent import SQLAgentResult

        agent = self._agent()
        qr = QueryResult(columns=["n"], rows=[], row_count=0)
        empty = SQLAgentResult(status="success", query="SELECT 1 WHERE false", results=qr)

        monkeypatch.setattr(settings, "query_empty_result_retry", False)
        assert agent._result_gate_directive("wf-3", empty) is None

        monkeypatch.setattr(settings, "query_empty_result_retry", True)
        directive = agent._result_gate_directive("wf-3", empty)
        assert directive is not None
        assert "0 rows" in directive

    def test_gate_disabled_returns_none(self, monkeypatch):
        from app.agents.sql_agent import SQLAgentResult

        agent = self._agent()
        bad = SQLAgentResult(status="error", query=None, results=None, error="boom")
        monkeypatch.setattr(settings, "orchestrator_result_gate_enabled", False)
        assert agent._result_gate_directive("wf-4", bad) is None

    def test_exhausted_budget_flags_suspicious(self):
        """R5-7: once corrections are spent and the result still fails the gate,
        the workflow is flagged suspicious so the chat layer can auto-route to
        the investigation agent."""
        from app.agents.sql_agent import SQLAgentResult

        agent = self._agent()
        bad = SQLAgentResult(status="error", query=None, results=None, error="boom")
        budget = settings.orchestrator_max_result_corrections
        for _ in range(budget):
            agent._result_gate_directive("wf-susp", bad)
        # Over budget now: no directive, but the suspicion is recorded.
        assert agent._result_gate_directive("wf-susp", bad) is None
        reason = agent.pop_suspicious_reason("wf-susp")
        assert reason is not None
        # Draining clears it.
        assert agent.pop_suspicious_reason("wf-susp") is None

    def test_good_result_never_flags_suspicious(self):
        """R5-7: a clean result must not leave a suspicious flag, even after
        many calls within budget."""
        from app.agents.sql_agent import SQLAgentResult

        agent = self._agent()
        qr = QueryResult(columns=["n"], rows=[[1]], row_count=1)
        ok = SQLAgentResult(status="success", query="SELECT 1", results=qr)
        for _ in range(settings.orchestrator_max_result_corrections + 2):
            agent._result_gate_directive("wf-clean", ok)
        assert agent.pop_suspicious_reason("wf-clean") is None

    def test_good_result_clears_stale_suspicious_after_exhausted_budget(self):
        """Re-audit fix: if the correction budget is spent on a failing result
        (flagging the workflow suspicious) but a later query in the SAME
        workflow returns a clean result, the stale suspicion must be cleared."""
        from app.agents.sql_agent import SQLAgentResult

        agent = self._agent()
        bad = SQLAgentResult(status="error", query=None, results=None, error="boom")
        budget = settings.orchestrator_max_result_corrections
        for _ in range(budget):
            agent._result_gate_directive("wf-recover", bad)
        # Exhaust budget on a bad result -> flagged suspicious.
        assert agent._result_gate_directive("wf-recover", bad) is None
        assert agent._wf_suspicious.get("wf-recover") is not None

        # A subsequent good query in the same workflow must clear the flag.
        qr = QueryResult(columns=["n"], rows=[[1]], row_count=1)
        ok = SQLAgentResult(status="success", query="SELECT 1", results=qr)
        assert agent._result_gate_directive("wf-recover", ok) is None
        assert agent.pop_suspicious_reason("wf-recover") is None


class TestEndPipelineWorkflow:
    """_end_pipeline_workflow must emit pipeline_end mapping the executor status
    so the resumed-pipeline path no longer leaks an unended workflow (phantom
    'running' task) and SSE consumers never show a green check on a failure."""

    def _agent(self):
        from unittest.mock import AsyncMock, MagicMock

        from app.agents.orchestrator import OrchestratorAgent

        tracker = MagicMock()
        tracker.end = AsyncMock()
        agent = OrchestratorAgent(llm_router=MagicMock(), workflow_tracker=tracker)
        return agent, tracker

    async def test_completed_status_ends_completed(self):
        from types import SimpleNamespace

        agent, tracker = self._agent()
        res = SimpleNamespace(status="completed", failed_stage=None)
        await agent._end_pipeline_workflow("wf1", res, label="resumed_pipeline")
        tracker.end.assert_awaited_once_with("wf1", "orchestrator", "completed", "resumed_pipeline")

    async def test_checkpoint_status_ends_checkpoint(self):
        from types import SimpleNamespace

        agent, tracker = self._agent()
        res = SimpleNamespace(status="checkpoint", failed_stage=None)
        await agent._end_pipeline_workflow("wf2", res, label="resumed_pipeline")
        tracker.end.assert_awaited_once_with(
            "wf2", "orchestrator", "checkpoint", "resumed_pipeline"
        )

    async def test_stage_failed_ends_failed_with_stage_id(self):
        from types import SimpleNamespace

        agent, tracker = self._agent()
        res = SimpleNamespace(status="stage_failed", failed_stage=SimpleNamespace(stage_id="s3"))
        await agent._end_pipeline_workflow("wf3", res, label="complex_pipeline")
        tracker.end.assert_awaited_once_with(
            "wf3", "orchestrator", "failed", "complex_pipeline stage=s3"
        )
