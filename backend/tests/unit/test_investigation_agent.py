"""Comprehensive unit tests for InvestigationAgent."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.base import AgentContext
from app.agents.investigation_agent import InvestigationAgent, InvestigationResult
from app.connectors.base import ConnectionConfig, QueryResult
from app.llm.base import LLMResponse, ToolCall

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_tracker():
    t = MagicMock()
    t.begin = AsyncMock(return_value="wf-1")
    t.end = AsyncMock()
    t.emit = AsyncMock()

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
def config():
    return ConnectionConfig(
        db_type="postgres",
        db_host="localhost",
        db_port=5432,
        db_name="testdb",
        db_user="user",
        connection_id="conn-1",
        ssh_exec_mode=False,
    )


@pytest.fixture
def context(mock_tracker, mock_llm, config):
    return AgentContext(
        project_id="proj-1",
        connection_config=config,
        user_question="",
        chat_history=[],
        llm_router=mock_llm,
        tracker=mock_tracker,
        workflow_id="wf-1",
        preferred_provider="openai",
        model="gpt-4",
        sql_provider=None,
        sql_model=None,
    )


@pytest.fixture
def agent(mock_llm):
    return InvestigationAgent(llm_router=mock_llm)


@pytest.fixture
def run_kwargs():
    return {
        "investigation_id": "inv-42",
        "original_query": "SELECT SUM(amount) FROM orders",
        "original_result_summary": '{"total": 1000}',
        "user_complaint_type": "wrong_value",
        "user_complaint_detail": "Total should be 1500",
        "user_expected_value": "1500",
        "problematic_column": "amount",
    }


def _llm_response(
    content: str = "",
    tool_calls: list[ToolCall] | None = None,
    usage: dict | None = None,
) -> LLMResponse:
    return LLMResponse(
        content=content,
        tool_calls=tool_calls or [],
        usage=usage or {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        model="gpt-4",
        provider="openai",
    )


# ---------------------------------------------------------------------------
# 1. name property
# ---------------------------------------------------------------------------


class TestNameProperty:
    def test_returns_investigation(self, agent):
        assert agent.name == "investigation"


# ---------------------------------------------------------------------------
# 2-8. run() method
# ---------------------------------------------------------------------------


class TestRun:
    @pytest.mark.asyncio
    async def test_no_tool_calls_returns_no_fix_found(self, agent, context, run_kwargs):
        agent._llm.complete = AsyncMock(return_value=_llm_response(content="No issues found."))

        result = await agent.run(context, **run_kwargs)

        assert isinstance(result, InvestigationResult)
        assert result.status == "no_fix_found"
        assert result.corrected_query is None

    @pytest.mark.asyncio
    async def test_record_finding_returns_success(self, agent, context, run_kwargs):
        finding_tc = ToolCall(
            id="tc-1",
            name="record_investigation_finding",
            arguments={
                "corrected_query": "SELECT SUM(amount) FROM orders WHERE status='active'",
                "root_cause": "Missing filter",
                "root_cause_category": "filter_error",
            },
        )
        agent._llm.complete = AsyncMock(
            side_effect=[
                _llm_response(tool_calls=[finding_tc]),
                _llm_response(content="Done."),
            ]
        )

        with (
            patch("app.agents.investigation_agent.get_connector"),
            patch("app.agents.investigation_agent.get_investigation_tools", return_value=[]),
        ):
            with (
                patch(
                    "app.services.investigation_service.InvestigationService"
                ) as mock_inv_svc_cls,
                patch("app.models.base.async_session_factory") as mock_sf,
            ):
                mock_session = AsyncMock()
                mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
                mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
                mock_inv_svc = MagicMock()
                mock_inv_svc.record_finding = AsyncMock(return_value=MagicMock())
                mock_inv_svc_cls.return_value = mock_inv_svc

                result = await agent.run(context, **run_kwargs)

        assert result.status == "success"
        assert result.corrected_query == "SELECT SUM(amount) FROM orders WHERE status='active'"

    @pytest.mark.asyncio
    async def test_multiple_iterations_processes_all_tool_calls(self, agent, context, run_kwargs):
        ctx_tc = ToolCall(id="tc-1", name="get_original_context", arguments={})
        compare_tc = ToolCall(
            id="tc-2",
            name="compare_results",
            arguments={"original_summary": "old", "new_summary": "new"},
        )
        agent._llm.complete = AsyncMock(
            side_effect=[
                _llm_response(tool_calls=[ctx_tc]),
                _llm_response(tool_calls=[compare_tc]),
                _llm_response(content="Analysis complete."),
            ]
        )

        with patch("app.agents.investigation_agent.get_investigation_tools", return_value=[]):
            result = await agent.run(context, **run_kwargs)

        assert result.status == "no_fix_found"
        assert len(result.investigation_log) == 2
        assert result.investigation_log[0]["tool"] == "get_original_context"
        assert result.investigation_log[1]["tool"] == "compare_results"

    @pytest.mark.asyncio
    async def test_extracts_root_cause_from_finding(self, agent, context, run_kwargs):
        finding_tc = ToolCall(
            id="tc-1",
            name="record_investigation_finding",
            arguments={
                "corrected_query": "SELECT 1",
                "root_cause": "Date filter wrong",
                "root_cause_category": "date_error",
            },
        )
        agent._llm.complete = AsyncMock(
            side_effect=[
                _llm_response(tool_calls=[finding_tc]),
                _llm_response(content="Done."),
            ]
        )

        with patch("app.agents.investigation_agent.get_investigation_tools", return_value=[]):
            with (
                patch("app.services.investigation_service.InvestigationService") as mock_cls,
                patch("app.models.base.async_session_factory") as mock_sf,
            ):
                mock_session = AsyncMock()
                mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
                mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
                svc = MagicMock()
                svc.record_finding = AsyncMock(return_value=MagicMock())
                mock_cls.return_value = svc

                result = await agent.run(context, **run_kwargs)

        assert result.root_cause == "Date filter wrong"
        assert result.root_cause_category == "date_error"

    @pytest.mark.asyncio
    async def test_investigation_log_records_each_tool_call(self, agent, context, run_kwargs):
        tc1 = ToolCall(id="tc-1", name="get_original_context", arguments={})
        tc2 = ToolCall(
            id="tc-2",
            name="compare_results",
            arguments={"original_summary": "a", "new_summary": "b"},
        )
        agent._llm.complete = AsyncMock(
            side_effect=[
                _llm_response(tool_calls=[tc1, tc2]),
                _llm_response(content="Done."),
            ]
        )

        with patch("app.agents.investigation_agent.get_investigation_tools", return_value=[]):
            result = await agent.run(context, **run_kwargs)

        assert len(result.investigation_log) == 2
        assert result.investigation_log[0]["tool"] == "get_original_context"
        assert "arguments" in result.investigation_log[0]
        assert "result_preview" in result.investigation_log[0]

    @pytest.mark.asyncio
    async def test_respects_max_investigation_iterations(self, agent, context, run_kwargs):
        infinite_tc = ToolCall(id="tc-loop", name="get_original_context", arguments={})
        agent._llm.complete = AsyncMock(return_value=_llm_response(tool_calls=[infinite_tc]))

        with patch("app.agents.investigation_agent.get_investigation_tools", return_value=[]):
            with patch("app.agents.investigation_agent.settings") as mock_settings:
                mock_settings.max_investigation_iterations = 3
                result = await agent.run(context, **run_kwargs)

        assert agent._llm.complete.call_count == 3
        assert len(result.investigation_log) == 3
        assert result.status == "no_fix_found"

    @pytest.mark.asyncio
    async def test_accumulates_token_usage(self, agent, context, run_kwargs):
        tc = ToolCall(id="tc-1", name="get_original_context", arguments={})
        agent._llm.complete = AsyncMock(
            side_effect=[
                _llm_response(
                    tool_calls=[tc],
                    usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
                ),
                _llm_response(
                    content="Done.",
                    usage={"prompt_tokens": 120, "completion_tokens": 60, "total_tokens": 180},
                ),
            ]
        )

        with patch("app.agents.investigation_agent.get_investigation_tools", return_value=[]):
            result = await agent.run(context, **run_kwargs)

        assert result.token_usage["prompt_tokens"] == 220
        assert result.token_usage["completion_tokens"] == 110
        assert result.token_usage["total_tokens"] == 330


# ---------------------------------------------------------------------------
# 9-12. _dispatch_tool
# ---------------------------------------------------------------------------


class TestDispatchTool:
    @pytest.mark.asyncio
    async def test_dispatches_get_original_context(self, agent, context, run_kwargs):
        agent._investigation_context = {
            "original_query": "SELECT 1",
            "original_result_summary": "{}",
            "user_complaint_type": "wrong_value",
            "user_complaint_detail": "bad data",
            "user_expected_value": "42",
            "problematic_column": "col_a",
        }
        tc = ToolCall(id="tc-1", name="get_original_context", arguments={})

        result = await agent._dispatch_tool(tc, context)

        assert "SELECT 1" in result
        assert "wrong_value" in result

    @pytest.mark.asyncio
    async def test_dispatches_compare_results(self, agent, context):
        tc = ToolCall(
            id="tc-1",
            name="compare_results",
            arguments={"original_summary": "old_val", "new_summary": "new_val"},
        )

        result = await agent._dispatch_tool(tc, context)

        assert "ORIGINAL:" in result
        assert "old_val" in result
        assert "CORRECTED:" in result
        assert "new_val" in result

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self, agent, context):
        tc = ToolCall(id="tc-1", name="nonexistent_tool", arguments={})

        result = await agent._dispatch_tool(tc, context)

        assert "Error: unknown tool" in result
        assert "nonexistent_tool" in result

    @pytest.mark.asyncio
    async def test_exception_in_handler_returns_error_string(self, agent, context):
        tc = ToolCall(id="tc-1", name="get_original_context", arguments={})
        agent._handle_get_original_context = AsyncMock(side_effect=RuntimeError("boom"))

        result = await agent._dispatch_tool(tc, context)

        assert "Error:" in result
        assert "boom" in result


# ---------------------------------------------------------------------------
# 13. _handle_get_original_context
# ---------------------------------------------------------------------------


class TestHandleGetOriginalContext:
    @pytest.mark.asyncio
    async def test_returns_formatted_context(self, agent, context):
        agent._investigation_context = {
            "original_query": "SELECT * FROM t",
            "original_result_summary": '{"rows":5}',
            "user_complaint_type": "missing_data",
            "user_complaint_detail": "rows are missing",
            "user_expected_value": "10 rows",
            "problematic_column": "id",
        }

        result = await agent._handle_get_original_context({}, context)

        assert "Original query: SELECT * FROM t" in result
        assert '{"rows":5}' in result
        assert "missing_data" in result
        assert "rows are missing" in result
        assert "10 rows" in result
        assert "id" in result

    @pytest.mark.asyncio
    async def test_truncates_long_result_summary(self, agent, context):
        agent._investigation_context = {
            "original_query": "Q",
            "original_result_summary": "X" * 2000,
            "user_complaint_type": "t",
            "user_complaint_detail": "d",
            "user_expected_value": "v",
            "problematic_column": "c",
        }

        result = await agent._handle_get_original_context({}, context)

        summary_line = [line for line in result.split("\n") if "Result summary:" in line][0]
        after_prefix = summary_line.split("Result summary: ")[1]
        assert len(after_prefix) <= 1000


# ---------------------------------------------------------------------------
# 14-16. _handle_run_diagnostic_query
# ---------------------------------------------------------------------------


class TestHandleRunDiagnosticQuery:
    @pytest.mark.asyncio
    async def test_no_connection_returns_error(self, agent):
        ctx = MagicMock()
        ctx.connection_config = None

        result = await agent._handle_run_diagnostic_query(
            {"query": "SELECT 1", "hypothesis": "h"}, ctx
        )

        assert result == "Error: no database connection."

    @pytest.mark.asyncio
    async def test_success_returns_formatted_result(self, agent, context):
        mock_connector = AsyncMock()
        mock_connector.connect = AsyncMock()
        mock_connector.disconnect = AsyncMock()
        mock_connector.execute_query = AsyncMock(
            return_value=QueryResult(
                columns=["id", "amount"],
                rows=[[1, 100], [2, 200]],
                row_count=2,
            )
        )

        with patch("app.agents.investigation_agent.get_connector", return_value=mock_connector):
            result = await agent._handle_run_diagnostic_query(
                {"query": "SELECT id, amount FROM orders", "hypothesis": "Check totals"},
                context,
            )

        assert "Hypothesis: Check totals" in result
        assert "id, amount" in result
        assert "1 | 100" in result
        assert "2 | 200" in result
        mock_connector.disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_query_error_returns_error_message(self, agent, context):
        mock_connector = AsyncMock()
        mock_connector.connect = AsyncMock()
        mock_connector.disconnect = AsyncMock()
        mock_connector.execute_query = AsyncMock(
            return_value=QueryResult(error="relation does not exist")
        )

        with patch("app.agents.investigation_agent.get_connector", return_value=mock_connector):
            result = await agent._handle_run_diagnostic_query(
                {"query": "SELECT * FROM bad_table", "hypothesis": "test"},
                context,
            )

        assert "Query error:" in result
        assert "relation does not exist" in result

    @pytest.mark.asyncio
    async def test_truncates_rows_beyond_15(self, agent, context):
        rows = [[i, i * 10] for i in range(20)]
        mock_connector = AsyncMock()
        mock_connector.connect = AsyncMock()
        mock_connector.disconnect = AsyncMock()
        mock_connector.execute_query = AsyncMock(
            return_value=QueryResult(columns=["id", "val"], rows=rows, row_count=20)
        )

        with patch("app.agents.investigation_agent.get_connector", return_value=mock_connector):
            result = await agent._handle_run_diagnostic_query(
                {"query": "SELECT id, val FROM t", "hypothesis": "h"}, context
            )

        assert "5 more rows" in result


# ---------------------------------------------------------------------------
# 17. _handle_compare_results
# ---------------------------------------------------------------------------


class TestHandleCompareResults:
    @pytest.mark.asyncio
    async def test_formats_comparison(self, agent, context):
        result = await agent._handle_compare_results(
            {"original_summary": "Total: 1000", "new_summary": "Total: 1500"},
            context,
        )

        assert result == "ORIGINAL:\nTotal: 1000\n\nCORRECTED:\nTotal: 1500"

    @pytest.mark.asyncio
    async def test_handles_empty_summaries(self, agent, context):
        result = await agent._handle_compare_results({}, context)

        assert result == "ORIGINAL:\n\n\nCORRECTED:\n"


# ---------------------------------------------------------------------------
# 18. _handle_check_column_formats
# ---------------------------------------------------------------------------


class TestHandleCheckColumnFormats:
    @pytest.mark.asyncio
    async def test_no_connection_returns_error(self, agent):
        ctx = MagicMock()
        ctx.connection_config = None

        result = await agent._handle_check_column_formats(
            {"table_name": "t", "column_name": "c"}, ctx
        )

        assert result == "Error: no database connection."

    @pytest.mark.asyncio
    async def test_success_returns_formatted_distinct_values(self, agent, context):
        mock_connector = AsyncMock()
        mock_connector.connect = AsyncMock()
        mock_connector.disconnect = AsyncMock()
        mock_connector.execute_query = AsyncMock(
            return_value=QueryResult(
                columns=["status", "cnt"],
                rows=[["active", 50], ["inactive", 30]],
                row_count=2,
            )
        )

        with patch("app.agents.investigation_agent.get_connector", return_value=mock_connector):
            result = await agent._handle_check_column_formats(
                {"table_name": "orders", "column_name": "status"}, context
            )

        assert "orders.status" in result
        assert "active (count: 50)" in result
        assert "inactive (count: 30)" in result

    @pytest.mark.asyncio
    async def test_query_error_returns_error(self, agent, context):
        mock_connector = AsyncMock()
        mock_connector.connect = AsyncMock()
        mock_connector.disconnect = AsyncMock()
        mock_connector.execute_query = AsyncMock(return_value=QueryResult(error="column not found"))

        with patch("app.agents.investigation_agent.get_connector", return_value=mock_connector):
            result = await agent._handle_check_column_formats(
                {"table_name": "t", "column_name": "bad_col"}, context
            )

        assert "Error: column not found" in result


# ---------------------------------------------------------------------------
# 19. _handle_record_finding
# ---------------------------------------------------------------------------


class TestHandleRecordFinding:
    @pytest.mark.asyncio
    async def test_no_investigation_id_returns_error(self, agent, context):
        agent._investigation_context = {"investigation_id": ""}

        result = await agent._handle_record_finding(
            {"corrected_query": "SELECT 1", "root_cause": "x", "root_cause_category": "y"},
            context,
        )

        assert result == "Error: no investigation_id in context."

    @pytest.mark.asyncio
    async def test_success_records_finding(self, agent, context):
        agent._investigation_context = {"investigation_id": "inv-42"}

        with (
            patch("app.models.base.async_session_factory") as mock_sf,
            patch("app.services.investigation_service.InvestigationService") as mock_cls,
        ):
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
            svc = MagicMock()
            svc.record_finding = AsyncMock(return_value=MagicMock())
            mock_cls.return_value = svc

            result = await agent._handle_record_finding(
                {
                    "corrected_query": "SELECT SUM(amount) FROM orders WHERE active",
                    "root_cause": "Missing filter",
                    "root_cause_category": "filter_error",
                },
                context,
            )

        assert "Finding recorded" in result
        assert "Missing filter" in result
        assert "filter_error" in result
        svc.record_finding.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_investigation_not_found_returns_error(self, agent, context):
        agent._investigation_context = {"investigation_id": "inv-99"}

        with (
            patch("app.models.base.async_session_factory") as mock_sf,
            patch("app.services.investigation_service.InvestigationService") as mock_cls,
        ):
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
            svc = MagicMock()
            svc.record_finding = AsyncMock(return_value=None)
            mock_cls.return_value = svc

            result = await agent._handle_record_finding(
                {"corrected_query": "Q", "root_cause": "R", "root_cause_category": "C"},
                context,
            )

        assert result == "Error: investigation not found."


# ---------------------------------------------------------------------------
# _handle_get_related_learnings
# ---------------------------------------------------------------------------


class TestHandleGetRelatedLearnings:
    @pytest.mark.asyncio
    async def test_no_connection_returns_no_learnings(self, agent):
        ctx = MagicMock()
        ctx.connection_config = None

        result = await agent._handle_get_related_learnings({"table_name": "t"}, ctx)

        assert result == "No learnings available."

    @pytest.mark.asyncio
    async def test_no_connection_id_returns_no_learnings(self, agent):
        ctx = MagicMock()
        ctx.connection_config = MagicMock()
        ctx.connection_config.connection_id = None

        result = await agent._handle_get_related_learnings({"table_name": "t"}, ctx)

        assert result == "No learnings available."

    @pytest.mark.asyncio
    async def test_no_learnings_found(self, agent, context):
        with (
            patch("app.models.base.async_session_factory") as mock_sf,
            patch("app.services.agent_learning_service.AgentLearningService") as mock_cls,
        ):
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
            svc = MagicMock()
            svc.get_learnings_for_table = AsyncMock(return_value=[])
            mock_cls.return_value = svc

            result = await agent._handle_get_related_learnings({"table_name": "orders"}, context)

        assert "No learnings found" in result
        assert "orders" in result

    @pytest.mark.asyncio
    async def test_returns_formatted_learnings(self, agent, context):
        learning = MagicMock()
        learning.category = "date_handling"
        learning.lesson = "Dates stored as UTC"
        learning.confidence = 0.85
        learning.id = "lrn-1"

        with (
            patch("app.models.base.async_session_factory") as mock_sf,
            patch("app.services.agent_learning_service.AgentLearningService") as mock_cls,
        ):
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
            svc = MagicMock()
            svc.get_learnings_for_table = AsyncMock(return_value=[learning])
            mock_cls.return_value = svc

            result = await agent._handle_get_related_learnings({"table_name": "orders"}, context)

        assert "Learnings for 'orders' (1):" in result
        assert "[date_handling]" in result
        assert "Dates stored as UTC" in result
        assert "85% conf" in result


# ---------------------------------------------------------------------------
# InvestigationResult dataclass
# ---------------------------------------------------------------------------


class TestInvestigationResult:
    def test_defaults(self):
        r = InvestigationResult()
        assert r.status == "success"
        assert r.corrected_query is None
        assert r.corrected_result is None
        assert r.root_cause is None
        assert r.root_cause_category is None
        assert r.investigation_log == []

    def test_inherits_agent_result_fields(self):
        r = InvestigationResult(
            status="error",
            error="Something broke",
            corrected_query="SELECT 1",
        )
        assert r.status == "error"
        assert r.error == "Something broke"
        assert r.corrected_query == "SELECT 1"


# ---------------------------------------------------------------------------
# Edge cases in run()
# ---------------------------------------------------------------------------


class TestRunEdgeCases:
    @pytest.mark.asyncio
    async def test_uses_sql_provider_when_set(self, agent, context, run_kwargs):
        context.sql_provider = "anthropic"
        context.sql_model = "claude-3"
        agent._llm.complete = AsyncMock(return_value=_llm_response(content="Done."))

        with patch("app.agents.investigation_agent.get_investigation_tools", return_value=[]):
            await agent.run(context, **run_kwargs)

        call_kwargs = agent._llm.complete.call_args
        assert call_kwargs.kwargs["preferred_provider"] == "anthropic"
        assert call_kwargs.kwargs["model"] == "claude-3"

    @pytest.mark.asyncio
    async def test_falls_back_to_preferred_provider(self, agent, context, run_kwargs):
        context.sql_provider = None
        context.sql_model = None
        agent._llm.complete = AsyncMock(return_value=_llm_response(content="Done."))

        with patch("app.agents.investigation_agent.get_investigation_tools", return_value=[]):
            await agent.run(context, **run_kwargs)

        call_kwargs = agent._llm.complete.call_args
        assert call_kwargs.kwargs["preferred_provider"] == "openai"
        assert call_kwargs.kwargs["model"] == "gpt-4"

    @pytest.mark.asyncio
    async def test_default_kwargs(self, agent, context):
        """run() works even when no kwargs provided — uses defaults."""
        agent._llm.complete = AsyncMock(return_value=_llm_response(content="Nothing found."))

        with patch("app.agents.investigation_agent.get_investigation_tools", return_value=[]):
            result = await agent.run(context)

        assert result.status == "no_fix_found"
        assert agent._investigation_context["investigation_id"] == ""
        assert agent._investigation_context["user_complaint_type"] == "other"

    @pytest.mark.asyncio
    async def test_result_preview_truncated_to_300(self, agent, context, run_kwargs):
        """investigation_log result_preview should be at most 300 chars."""
        agent._investigation_context = {
            "original_query": "Q",
            "original_result_summary": "X" * 500,
            "user_complaint_type": "t",
            "user_complaint_detail": "d" * 500,
            "user_expected_value": "v" * 500,
            "problematic_column": "c",
        }
        tc = ToolCall(id="tc-1", name="get_original_context", arguments={})
        agent._llm.complete = AsyncMock(
            side_effect=[
                _llm_response(tool_calls=[tc]),
                _llm_response(content="Done."),
            ]
        )

        with patch("app.agents.investigation_agent.get_investigation_tools", return_value=[]):
            result = await agent.run(context, **run_kwargs)

        assert len(result.investigation_log[0]["result_preview"]) <= 300

    @pytest.mark.asyncio
    async def test_corrected_query_not_overwritten_by_empty(self, agent, context, run_kwargs):
        """A second finding with empty corrected_query shouldn't erase the first one."""
        tc1 = ToolCall(
            id="tc-1",
            name="record_investigation_finding",
            arguments={"corrected_query": "SELECT 1", "root_cause": "r1"},
        )
        tc2 = ToolCall(
            id="tc-2",
            name="record_investigation_finding",
            arguments={"corrected_query": "", "root_cause": "r2"},
        )
        agent._llm.complete = AsyncMock(
            side_effect=[
                _llm_response(tool_calls=[tc1, tc2]),
                _llm_response(content="Done."),
            ]
        )

        with patch("app.agents.investigation_agent.get_investigation_tools", return_value=[]):
            with (
                patch("app.models.base.async_session_factory") as mock_sf,
                patch("app.services.investigation_service.InvestigationService") as mock_cls,
            ):
                mock_session = AsyncMock()
                mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
                mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
                svc = MagicMock()
                svc.record_finding = AsyncMock(return_value=MagicMock())
                mock_cls.return_value = svc

                result = await agent.run(context, **run_kwargs)

        assert result.corrected_query == "SELECT 1"
        assert result.root_cause == "r2"

    @pytest.mark.asyncio
    async def test_diagnostic_query_disconnects_on_success(self, agent, context):
        mock_connector = AsyncMock()
        mock_connector.connect = AsyncMock()
        mock_connector.disconnect = AsyncMock()
        mock_connector.execute_query = AsyncMock(
            return_value=QueryResult(columns=["a"], rows=[["val"]], row_count=1)
        )

        with patch("app.agents.investigation_agent.get_connector", return_value=mock_connector):
            await agent._handle_run_diagnostic_query(
                {"query": "SELECT 1", "hypothesis": "h"}, context
            )

        mock_connector.disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_diagnostic_query_disconnects_on_error(self, agent, context):
        mock_connector = AsyncMock()
        mock_connector.connect = AsyncMock()
        mock_connector.disconnect = AsyncMock()
        mock_connector.execute_query = AsyncMock(return_value=QueryResult(error="syntax error"))

        with patch("app.agents.investigation_agent.get_connector", return_value=mock_connector):
            await agent._handle_run_diagnostic_query(
                {"query": "BAD SQL", "hypothesis": "h"}, context
            )

        mock_connector.disconnect.assert_awaited_once()
