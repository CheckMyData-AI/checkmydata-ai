"""M1 / REQ-011 — an analytics answer charts like any other tabular answer.

Spec ``docs/superpowers/specs/2026-08-01-m0-ga4-spine-design.md`` §3.3 gate 5:
"``VizAgent`` renders as for any tabular result."

``AnalyticsResult`` carries ``report`` / ``columns`` / ``rows`` / ``truncated``,
but the orchestrator's visualization pipeline only ever looked at
``SQLAgentResult``.  Since ``AnalyticsResult`` subclasses ``AgentResult`` and not
``SQLAgentResult``, an analytics answer never produced a result block, never
reached ``VizAgent``, and those four fields were dead.

These tests pin the behaviour, not the plumbing:

1. an analytics sub-result with columns and rows reaches ``VizAgent`` with its
   real table, and its chart lands in the response the chat route reads;
2. ``truncated=True`` survives the trip to the chart — a capped table must not
   become a chart that reads as complete;
3. never-collected periods (``pending_periods``) mark the chart partial too —
   three of seven days must not be drawn as a full week;
4. an analytics result with **no rows** produces no chart at all, rather than an
   empty one that reads as "the answer is zero";
5. SQL charting is untouched — same call to ``VizAgent``, same blocks, and in a
   mixed answer the top-level viz fields still describe the SQL result.

No network: the LLM router, the dispatcher, the viz agent and the workflow
tracker are all mocked.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.analytics_agent import AnalyticsResult
from app.agents.base import AgentContext
from app.agents.orchestrator import AgentResponse, OrchestratorAgent
from app.agents.sql_agent import SQLAgentResult
from app.agents.tools.orchestrator_tools import get_orchestrator_tools
from app.agents.viz_agent import VizResult
from app.connectors.base import QueryResult
from app.core.workflow_tracker import WorkflowTracker
from app.llm.base import LLMResponse, ToolCall

# ---------------------------------------------------------------------------
# Shared doubles (same conventions as test_orchestrator_termination.py)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_tracker():
    t = MagicMock(spec=WorkflowTracker)
    t.begin = AsyncMock(return_value="wf-1")
    t.end = AsyncMock()
    t.emit = AsyncMock()
    t.has_ended = MagicMock(return_value=False)

    @asynccontextmanager
    async def fake_step(wf_id: str, step: str, detail: str = "", **kwargs: Any):
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
def mock_vs():
    vs = MagicMock()
    collection = MagicMock()
    collection.count = MagicMock(return_value=0)
    vs.get_or_create_collection = MagicMock(return_value=collection)
    return vs


@pytest.fixture
def orch(mock_llm, mock_vs, mock_tracker):
    return OrchestratorAgent(
        llm_router=mock_llm,
        vector_store=mock_vs,
        workflow_tracker=mock_tracker,
    )


@pytest.fixture
def base_context(mock_llm, mock_tracker):
    return AgentContext(
        project_id="test-proj",
        connection_config=None,
        user_question="How many sessions did organic search bring last week?",
        chat_history=[],
        llm_router=mock_llm,
        tracker=mock_tracker,
        workflow_id="wf-1",
        project_name="TestProject",
    )


# ---------------------------------------------------------------------------
# LLM turns: one tool call, then a final answer.
# ---------------------------------------------------------------------------


def _analytics_turn(call_id: str = "a1") -> LLMResponse:
    return LLMResponse(
        content="",
        tool_calls=[
            ToolCall(
                id=call_id,
                name="query_analytics_source",
                arguments={"question": "sessions from organic search last week"},
            )
        ],
    )


def _sql_turn(call_id: str = "s1", question: str = "how many orders?") -> LLMResponse:
    return LLMResponse(
        content="",
        tool_calls=[ToolCall(id=call_id, name="query_database", arguments={"question": question})],
    )


def _final_turn() -> LLMResponse:
    return LLMResponse(content="Organic search brought 1,234 sessions.", tool_calls=[])


def _analytics_result(
    *,
    columns: list[str] | None = None,
    rows: list[list[Any]] | None = None,
    truncated: bool = False,
    pending_periods: list[str] | None = None,
    report: str | None = "traffic_overview",
) -> AnalyticsResult:
    return AnalyticsResult(
        status="success",
        answer="Organic search brought 1,234 sessions.",
        raw_answer="Organic search brought 1,234 sessions.",
        report=report,
        columns=["date", "sessions"] if columns is None else columns,
        rows=[["2026-07-20", 600], ["2026-07-21", 634]] if rows is None else rows,
        truncated=truncated,
        pending_periods=pending_periods or [],
    )


def _sql_result(*, query: str = "SELECT count(*) AS c, 'x' AS k FROM orders") -> SQLAgentResult:
    return SQLAgentResult(
        query=query,
        query_explanation="Counts the orders.",
        results=QueryResult(columns=["c", "k"], rows=[[42, "x"]], row_count=1),
    )


def _apply_mock_settings(mock_settings: Any) -> None:  # noqa: ANN001
    mock_settings.max_orchestrator_iterations = 20
    mock_settings.agent_wall_clock_timeout_seconds = 10_000
    mock_settings.agent_emergency_synthesis_pct = 0.90
    mock_settings.orchestrator_final_synthesis = False
    mock_settings.max_context_tokens = 100_000
    mock_settings.tool_result_insert_max_chars = 10_000
    mock_settings.history_tail_messages = 10
    mock_settings.orchestrator_result_gate_enabled = False
    mock_settings.answer_validator_enabled = False
    mock_settings.answer_validator_fail_closed = False
    mock_settings.answer_validator_min_chars = 10
    mock_settings.orchestrator_pipeline_table_threshold = 5
    mock_settings.orchestrator_max_result_corrections = 3
    mock_settings.query_empty_result_retry = False
    mock_settings.max_pipeline_replans = 2
    mock_settings.custom_rules_dir = ""
    mock_settings.history_summary_model = None
    mock_settings.max_history_tokens = 4_000
    mock_settings.viz_timeout_seconds = 30
    mock_settings.max_parallel_tool_calls = 3


async def _run_loop(
    orch: OrchestratorAgent,
    context: AgentContext,
    *,
    turns: list[LLMResponse],
    dispatched: list[tuple[str, Any]],
    viz_result: VizResult | None = None,
) -> tuple[AgentResponse, AsyncMock]:
    """Drive ``_run_tool_loop`` over scripted LLM turns and dispatch results.

    Returns the response plus the ``VizAgent.run`` mock so a test can assert on
    what was actually handed to the viz pipeline.
    """
    viz_mock = AsyncMock(
        return_value=viz_result
        or VizResult(viz_type="bar_chart", viz_config={"x": "date", "y": "sessions"})
    )
    tools = get_orchestrator_tools(has_connection=True, has_analytics_sources=True)

    with (
        patch.object(orch, "_llm_call_with_retry", new=AsyncMock(side_effect=turns)),
        patch.object(orch._dispatcher, "dispatch", new=AsyncMock(side_effect=dispatched)),
        patch.object(orch._viz, "run", new=viz_mock),
        patch.object(orch, "_stream_tokens", new=AsyncMock()),
        patch.object(orch, "_validate_partial_answer", new=AsyncMock(return_value=True)),
        patch("app.agents.orchestrator.settings") as mock_settings,
    ):
        _apply_mock_settings(mock_settings)
        resp = await orch._run_tool_loop(
            context,
            "wf-1",
            has_connection=True,
            db_type="postgres",
            has_kb=False,
            has_mcp=False,
            has_repo=False,
            has_analytics=True,
            table_map="",
            project_overview="",
            recent_learnings="",
            tools=tools,
        )
    return resp, viz_mock


# ---------------------------------------------------------------------------
# 1. REQ-011 — the named test
# ---------------------------------------------------------------------------


class TestAnalyticsResultReachesTheVizPipeline:
    async def test_analytics_result_renders_chart(self, orch, base_context):
        """An analytics table must reach ``VizAgent`` and come back as a chart."""
        resp, viz_mock = await _run_loop(
            orch,
            base_context,
            turns=[_analytics_turn(), _final_turn()],
            dispatched=[("Sessions: 1234", _analytics_result())],
        )

        viz_mock.assert_awaited_once()
        passed = viz_mock.await_args.kwargs["results"]
        assert isinstance(passed, QueryResult), (
            f"VizAgent must receive a QueryResult, got {type(passed).__name__}"
        )
        assert passed.columns == ["date", "sessions"], (
            f"the analytics columns must reach VizAgent, got {passed.columns}"
        )
        assert passed.rows == [["2026-07-20", 600], ["2026-07-21", 634]], (
            f"the analytics rows must reach VizAgent, got {passed.rows}"
        )
        assert passed.row_count == 2, f"row_count must match the rows, got {passed.row_count}"

        assert len(resp.sql_results) == 1, (
            f"the analytics table must produce one result block, got {resp.sql_results}"
        )
        block = resp.sql_results[0]
        assert block.viz_type == "bar_chart", (
            f"the block must carry the chosen chart, got {block.viz_type}"
        )
        assert block.results is passed, "the block must carry the very table VizAgent saw"

        # The chat route renders the single-result case from the top-level
        # fields; a viz_type with no results renders nothing at all.
        assert resp.viz_type == "bar_chart", f"top-level viz_type, got {resp.viz_type}"
        assert resp.viz_config == {"x": "date", "y": "sessions"}, (
            f"top-level viz_config, got {resp.viz_config}"
        )
        assert resp.results is passed, (
            "top-level results must be the analytics table so the chat route "
            f"has data to render, got {resp.results}"
        )

    async def test_analytics_block_names_the_report_it_read(self, orch, base_context):
        """Traceability: the block must say which report the chart came from."""
        resp, _ = await _run_loop(
            orch,
            base_context,
            turns=[_analytics_turn(), _final_turn()],
            dispatched=[("Sessions: 1234", _analytics_result(report="traffic_overview"))],
        )

        assert len(resp.sql_results) == 1
        assert resp.sql_results[0].query_explanation == "traffic_overview", (
            "the block must name the analytics report it was read from, got "
            f"{resp.sql_results[0].query_explanation!r}"
        )
        assert resp.sql_results[0].query is None, (
            "an analytics block has no SQL — inventing one would be a lie, got "
            f"{resp.sql_results[0].query!r}"
        )


# ---------------------------------------------------------------------------
# 2-3. The honesty signals must survive the trip to the chart
# ---------------------------------------------------------------------------


class TestPartialAnalyticsDataStaysPartial:
    async def test_truncated_analytics_result_keeps_the_truncation_flag(self, orch, base_context):
        """A row-capped table must not become a chart that reads as complete."""
        resp, viz_mock = await _run_loop(
            orch,
            base_context,
            turns=[_analytics_turn(), _final_turn()],
            dispatched=[("Sessions: 1234 (capped)", _analytics_result(truncated=True))],
        )

        passed = viz_mock.await_args.kwargs["results"]
        assert passed.truncated is True, (
            "truncated=True must travel on the QueryResult the way the SQL path "
            "carries it; otherwise every downstream reader sees a complete table"
        )
        assert resp.sql_results[0].results.truncated is True, (
            "the result block handed to the API must stay marked truncated"
        )
        assert resp.results is not None and resp.results.truncated is True

    async def test_never_collected_periods_mark_the_chart_partial(self, orch, base_context):
        """Uncollected periods are partial data too, even with no row cap hit."""
        resp, viz_mock = await _run_loop(
            orch,
            base_context,
            turns=[_analytics_turn(), _final_turn()],
            dispatched=[
                (
                    "Sessions: 1234 (2 days missing)",
                    _analytics_result(
                        truncated=False,
                        pending_periods=["2026-07-22", "2026-07-23"],
                    ),
                )
            ],
        )

        passed = viz_mock.await_args.kwargs["results"]
        assert passed.truncated is True, (
            "a window with never-collected periods is partial: charting it as a "
            "complete series is the same lie in a different medium"
        )
        assert resp.sql_results[0].results.truncated is True


# ---------------------------------------------------------------------------
# 4. No rows -> no chart
# ---------------------------------------------------------------------------


class TestEmptyAnalyticsResultDoesNotChart:
    async def test_analytics_result_with_no_rows_produces_no_chart(self, orch, base_context):
        resp, viz_mock = await _run_loop(
            orch,
            base_context,
            turns=[_analytics_turn(), _final_turn()],
            dispatched=[
                ("No rows on file for this window.", _analytics_result(rows=[])),
            ],
        )

        viz_mock.assert_not_awaited()
        assert resp.sql_results == [], (
            f"an empty table must not become a result block, got {resp.sql_results}"
        )
        assert resp.viz_type == "text", f"no chart for no rows, got {resp.viz_type}"
        assert resp.results is None, f"no data to render, got {resp.results}"

    async def test_analytics_result_with_no_columns_produces_no_chart(self, orch, base_context):
        resp, viz_mock = await _run_loop(
            orch,
            base_context,
            turns=[_analytics_turn(), _final_turn()],
            dispatched=[("No table.", _analytics_result(columns=[], rows=[]))],
        )

        viz_mock.assert_not_awaited()
        assert resp.sql_results == []
        assert resp.viz_type == "text"


# ---------------------------------------------------------------------------
# 5. Regression — SQL charting is unchanged
# ---------------------------------------------------------------------------


class TestSqlChartingUnchanged:
    async def test_sql_result_still_charts(self, orch, base_context):
        resp, viz_mock = await _run_loop(
            orch,
            base_context,
            turns=[_sql_turn(), _final_turn()],
            dispatched=[("42 rows", _sql_result())],
        )

        viz_mock.assert_awaited_once()
        assert viz_mock.await_args.kwargs["query"] == (
            "SELECT count(*) AS c, 'x' AS k FROM orders"
        ), "the SQL text must still be handed to VizAgent"
        assert len(resp.sql_results) == 1
        assert resp.sql_results[0].query == "SELECT count(*) AS c, 'x' AS k FROM orders"
        assert resp.sql_results[0].query_explanation == "Counts the orders."
        assert resp.viz_type == "bar_chart"
        assert resp.response_type == "sql_result"

    async def test_repeated_identical_sql_is_still_deduped(self, orch, base_context):
        """Two reads of the same query stay one block (existing behaviour)."""
        wide = SQLAgentResult(
            query="SELECT a, b FROM t",
            results=QueryResult(columns=["a", "b"], rows=[[1, 2], [3, 4]], row_count=2),
        )
        narrow = SQLAgentResult(
            query="select a, b from T",
            results=QueryResult(columns=["a", "b"], rows=[[1, 2]], row_count=1),
        )
        resp, _ = await _run_loop(
            orch,
            base_context,
            turns=[
                _sql_turn("s1", "how many orders?"),
                _sql_turn("s2", "and how many orders again?"),
                _final_turn(),
            ],
            dispatched=[("narrow", narrow), ("wide", wide)],
        )

        assert len(resp.sql_results) == 1, (
            f"the same query read twice is one block, got {len(resp.sql_results)}"
        )
        assert resp.sql_results[0].results.row_count == 2, "the widest read must win the dedup"

    async def test_mixed_answer_keeps_sql_as_the_primary_result(self, orch, base_context):
        """SQL + analytics: both chart, and the top-level fields stay on SQL."""
        resp, viz_mock = await _run_loop(
            orch,
            base_context,
            turns=[_analytics_turn(), _sql_turn(), _final_turn()],
            dispatched=[
                ("Sessions: 1234", _analytics_result()),
                ("42 rows", _sql_result()),
            ],
        )

        assert viz_mock.await_count == 2, (
            f"both tables must reach VizAgent, got {viz_mock.await_count} calls"
        )
        assert len(resp.sql_results) == 2, (
            f"SQL and analytics each get a block, got {len(resp.sql_results)}"
        )
        assert resp.results is not None and resp.results.columns == ["c", "k"], (
            "the top-level result must still describe the SQL result, got "
            f"{resp.results.columns if resp.results else None}"
        )
