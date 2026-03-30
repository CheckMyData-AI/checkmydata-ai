"""Unit tests for VizAgent — visualization specialist."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.base import AgentContext
from app.agents.viz_agent import VizAgent
from app.connectors.base import QueryResult
from app.core.workflow_tracker import WorkflowTracker
from app.llm.base import LLMResponse, ToolCall

# ── Fixtures ────────────────────────────────────────────────────────


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
def context(mock_llm, mock_tracker):
    return AgentContext(
        project_id="proj-1",
        connection_config=None,
        user_question="Show me monthly revenue",
        chat_history=[],
        llm_router=mock_llm,
        tracker=mock_tracker,
        workflow_id="wf-1",
    )


@pytest.fixture
def agent():
    return VizAgent()


# ── Helpers ─────────────────────────────────────────────────────────


def _qr(
    columns: list[str] | None = None,
    rows: list[list] | None = None,
    error: str | None = None,
    execution_time_ms: float = 42.0,
) -> QueryResult:
    columns = columns or []
    rows = rows or []
    return QueryResult(
        columns=columns,
        rows=rows,
        row_count=len(rows),
        execution_time_ms=execution_time_ms,
        error=error,
    )


# ── Tests ───────────────────────────────────────────────────────────


class TestVizAgent:
    """Comprehensive unit tests for VizAgent."""

    # 1. name property
    def test_name_property(self, agent):
        assert agent.name == "viz"

    # 2. empty results
    @pytest.mark.asyncio
    async def test_empty_results(self, agent, context):
        result = await agent.run(context, results=_qr())
        assert result.viz_type == "text"
        assert "No data" in result.summary

    # 3. error results
    @pytest.mark.asyncio
    async def test_error_results(self, agent, context):
        result = await agent.run(
            context,
            results=_qr(
                columns=["id"],
                rows=[[1]],
                error="relation does not exist",
            ),
        )
        assert result.viz_type == "text"
        assert "No data" in result.summary

    # 4. single numeric value
    @pytest.mark.asyncio
    async def test_single_value(self, agent, context):
        result = await agent.run(
            context,
            results=_qr(columns=["total_revenue"], rows=[[12345.67]]),
        )
        assert result.viz_type == "number"
        assert result.viz_config["value_column"] == "total_revenue"
        assert "12345.67" in result.summary

    # 5. single text value
    @pytest.mark.asyncio
    async def test_single_value_text(self, agent, context):
        result = await agent.run(
            context,
            results=_qr(columns=["status"], rows=[["active"]]),
        )
        assert result.viz_type == "text"
        assert result.summary == "active"

    # 6. preferred_viz respected
    @pytest.mark.asyncio
    async def test_preferred_viz_bar_chart(self, agent, context):
        result = await agent.run(
            context,
            results=_qr(
                columns=["month", "revenue"],
                rows=[["Jan", 100], ["Feb", 200]],
            ),
            preferred_viz="bar_chart",
        )
        assert result.viz_type == "bar_chart"

    # 7. pie_chart downgraded to bar_chart when too many categories
    @pytest.mark.asyncio
    async def test_preferred_viz_pie_too_many_categories(self, agent, context):
        rows = [[f"cat-{i}", i] for i in range(21)]
        result = await agent.run(
            context,
            results=_qr(columns=["category", "count"], rows=rows),
            preferred_viz="pie_chart",
        )
        assert result.viz_type == "bar_chart"

    # 8. LLM recommendation via tool call
    @pytest.mark.asyncio
    async def test_llm_recommendation(self, agent, context, mock_llm):
        mock_llm.complete = AsyncMock(
            return_value=LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="tc-1",
                        name="recommend_visualization",
                        arguments={
                            "viz_type": "line_chart",
                            "summary": "Revenue trend over months",
                            "config": '{"labels_column": "month", "data_columns": ["revenue"]}',
                        },
                    ),
                ],
                usage={"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70},
            )
        )

        result = await agent.run(
            context,
            results=_qr(
                columns=["month", "category", "region"],
                rows=[["Jan", "A", "US"], ["Feb", "B", "EU"], ["Mar", "C", "AP"]],
            ),
        )
        assert result.viz_type == "line_chart"
        assert result.viz_config["labels_column"] == "month"
        assert result.summary == "Revenue trend over months"

    # 9. LLM returns text without tool call → fallback to table
    @pytest.mark.asyncio
    async def test_llm_no_tool_call(self, agent, context, mock_llm):
        mock_llm.complete = AsyncMock(
            return_value=LLMResponse(
                content="A table would be best here.",
                tool_calls=[],
                usage={"prompt_tokens": 40, "completion_tokens": 10, "total_tokens": 50},
            )
        )

        result = await agent.run(
            context,
            results=_qr(
                columns=["name", "email", "role"],
                rows=[["Alice", "a@b.com", "admin"], ["Bob", "b@b.com", "user"]],
            ),
        )
        assert result.viz_type == "table"
        assert result.summary == "A table would be best here."

    # 10. post-validate: pie with >max_pie_categories rows → bar
    @pytest.mark.asyncio
    async def test_post_validate_pie_to_bar(self, agent, context, mock_llm):
        rows = [[f"cat-{i}", i] for i in range(21)]
        mock_llm.complete = AsyncMock(
            return_value=LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="tc-1",
                        name="recommend_visualization",
                        arguments={
                            "viz_type": "pie_chart",
                            "summary": "Distribution",
                            "config": "{}",
                        },
                    ),
                ],
                usage={"prompt_tokens": 30, "completion_tokens": 10, "total_tokens": 40},
            )
        )

        result = await agent.run(
            context,
            results=_qr(columns=["category", "count"], rows=rows),
        )
        assert result.viz_type == "bar_chart"

    # 11. post-validate: line_chart with <2 columns → table
    @pytest.mark.asyncio
    async def test_post_validate_line_too_few_cols(self, agent, context, mock_llm):
        mock_llm.complete = AsyncMock(
            return_value=LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="tc-1",
                        name="recommend_visualization",
                        arguments={
                            "viz_type": "line_chart",
                            "summary": "Trend",
                            "config": "{}",
                        },
                    ),
                ],
                usage={"prompt_tokens": 30, "completion_tokens": 10, "total_tokens": 40},
            )
        )

        result = await agent.run(
            context,
            results=_qr(columns=["value"], rows=[[10], [20], [30]]),
        )
        assert result.viz_type == "table"

    # 12. post-validate: bar_chart with <2 columns → table
    @pytest.mark.asyncio
    async def test_post_validate_bar_too_few_cols(self, agent, context, mock_llm):
        mock_llm.complete = AsyncMock(
            return_value=LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="tc-1",
                        name="recommend_visualization",
                        arguments={
                            "viz_type": "bar_chart",
                            "summary": "Counts",
                            "config": "{}",
                        },
                    ),
                ],
                usage={"prompt_tokens": 30, "completion_tokens": 10, "total_tokens": 40},
            )
        )

        result = await agent.run(
            context,
            results=_qr(columns=["value"], rows=[[10], [20]]),
        )
        assert result.viz_type == "table"

    # 13. token usage propagated from LLM response
    @pytest.mark.asyncio
    async def test_token_usage(self, agent, context, mock_llm):
        mock_llm.complete = AsyncMock(
            return_value=LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="tc-1",
                        name="recommend_visualization",
                        arguments={
                            "viz_type": "table",
                            "summary": "Data overview",
                            "config": "{}",
                        },
                    ),
                ],
                usage={"prompt_tokens": 80, "completion_tokens": 25, "total_tokens": 105},
            )
        )

        result = await agent.run(
            context,
            results=_qr(
                columns=["status", "description", "note"],
                rows=[["ok", "first", "a"], ["err", "second", "b"]],
            ),
        )
        assert result.token_usage["prompt_tokens"] == 80
        assert result.token_usage["completion_tokens"] == 25
        assert result.token_usage["total_tokens"] == 105

    # 14. _summarize_results truncates large result sets
    def test_summarize_results_truncation(self, agent):
        rows = [[i, f"name-{i}"] for i in range(50)]
        qr = _qr(columns=["id", "name"], rows=rows)
        summary = agent._summarize_results(qr, max_rows=20)

        assert "Columns (2)" in summary
        assert "Total rows: 50" in summary
        assert "and 30 more rows" in summary
        lines = summary.strip().split("\n")
        assert len(lines) == 23  # header(2) + 20 data rows + 1 truncation notice

    # 15. invalid JSON in tool config → fallback to {}
    @pytest.mark.asyncio
    async def test_invalid_json_in_tool_config(self, agent, context, mock_llm):
        mock_llm.complete = AsyncMock(
            return_value=LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="tc-1",
                        name="recommend_visualization",
                        arguments={
                            "viz_type": "bar_chart",
                            "summary": "Some chart",
                            "config": "{not valid json!!!}",
                        },
                    ),
                ],
                usage={"prompt_tokens": 30, "completion_tokens": 10, "total_tokens": 40},
            )
        )

        result = await agent.run(
            context,
            results=_qr(
                columns=["label", "note", "extra"],
                rows=[["a", "b", "c"], ["d", "e", "f"]],
            ),
        )
        assert result.viz_type == "bar_chart"

    # 16. preferred_viz generates proper config
    @pytest.mark.asyncio
    async def test_preferred_viz_generates_config(self, agent, context):
        result = await agent.run(
            context,
            results=_qr(
                columns=["month", "revenue"],
                rows=[["Jan", 100], ["Feb", 200]],
            ),
            preferred_viz="bar_chart",
        )
        assert result.viz_type == "bar_chart"
        assert "labels_column" in result.viz_config
        assert "data_columns" in result.viz_config

    # 17. preferred_viz pie generates data_column (singular)
    @pytest.mark.asyncio
    async def test_preferred_viz_pie_config(self, agent, context):
        result = await agent.run(
            context,
            results=_qr(
                columns=["category", "count"],
                rows=[["A", 10], ["B", 20], ["C", 30]],
            ),
            preferred_viz="pie_chart",
        )
        assert result.viz_type == "pie_chart"
        assert "labels_column" in result.viz_config
        assert "data_column" in result.viz_config

    # 18. preferred_viz scatter generates x/y columns
    @pytest.mark.asyncio
    async def test_preferred_viz_scatter_config(self, agent, context):
        result = await agent.run(
            context,
            results=_qr(
                columns=["age", "income"],
                rows=[[25, 50000], [30, 60000]],
            ),
            preferred_viz="scatter",
        )
        assert result.viz_type == "scatter"
        assert "x_column" in result.viz_config
        assert "y_column" in result.viz_config

    # 19. validate_and_fix_config regenerates when columns are wrong
    def test_validate_and_fix_config_regenerates(self, agent):
        results = _qr(
            columns=["month", "revenue"],
            rows=[["Jan", 100], ["Feb", 200]],
        )
        bad_config = {
            "labels_column": "nonexistent",
            "data_columns": ["also_missing"],
        }
        fixed = agent._validate_and_fix_config(bad_config, "bar_chart", results)
        assert fixed["labels_column"] in results.columns
        for dc in fixed.get("data_columns", []):
            assert dc in results.columns

    # 20. validate_and_fix_config keeps valid config
    def test_validate_and_fix_config_keeps_valid(self, agent):
        results = _qr(
            columns=["month", "revenue"],
            rows=[["Jan", 100], ["Feb", 200]],
        )
        good_config = {
            "labels_column": "month",
            "data_columns": ["revenue"],
        }
        fixed = agent._validate_and_fix_config(good_config, "bar_chart", results)
        assert fixed == good_config

    # 21. LLM returns wrong column names → config gets fixed
    @pytest.mark.asyncio
    async def test_llm_bad_columns_fixed(self, agent, context, mock_llm):
        mock_llm.complete = AsyncMock(
            return_value=LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="tc-1",
                        name="recommend_visualization",
                        arguments={
                            "viz_type": "bar_chart",
                            "summary": "Revenue by month",
                            "config": '{"labels_column": "wrong_name",'
                            ' "data_columns": ["bad_col"]}',
                        },
                    ),
                ],
                usage={"prompt_tokens": 30, "completion_tokens": 10, "total_tokens": 40},
            )
        )

        results = _qr(
            columns=["label", "note", "remark"],
            rows=[["a", "b", "c"], ["d", "e", "f"]],
        )
        result = await agent.run(context, results=results)
        assert result.viz_type == "bar_chart"
        assert result.viz_config["labels_column"] in results.columns
        for dc in result.viz_config.get("data_columns", []):
            assert dc in results.columns


class TestValidateAndFixConfigEdgeCases:
    def test_fix_config_pie_chart(self):
        """Invalid config for pie chart should be auto-fixed."""
        agent = VizAgent()
        results = _qr(
            columns=["name", "value"],
            rows=[["A", 10], ["B", 20]],
        )
        bad_config = {"labels_column": "nonexistent", "data_column": "also_bad"}
        fixed = agent._validate_and_fix_config(bad_config, "pie_chart", results)
        assert fixed["labels_column"] in results.columns

    def test_fix_config_scatter(self):
        """Invalid config for scatter should be auto-fixed."""
        agent = VizAgent()
        results = _qr(
            columns=["x", "y"],
            rows=[[1, 10], [2, 20]],
        )
        bad_config = {"x_column": "nonexistent", "y_column": "also_bad"}
        fixed = agent._validate_and_fix_config(bad_config, "scatter", results)
        assert "x_column" in fixed

    def test_fix_config_bad_data_columns(self):
        """data_columns list with invalid column triggers fix."""
        agent = VizAgent()
        results = _qr(
            columns=["month", "revenue"],
            rows=[["Jan", 100], ["Feb", 200]],
        )
        bad_config = {"labels_column": "month", "data_columns": ["nonexistent"]}
        fixed = agent._validate_and_fix_config(bad_config, "bar_chart", results)
        assert fixed["labels_column"] in results.columns
        for dc in fixed.get("data_columns", []):
            assert dc in results.columns


class TestGenerateConfig:
    def test_table_type_returns_empty(self):
        results = _qr(columns=["a", "b"], rows=[["x", 1]])
        cfg = VizAgent._generate_config(results, "table")
        assert cfg == {}

    def test_unknown_type_returns_empty(self):
        results = _qr(columns=["a", "b"], rows=[["x", 1]])
        cfg = VizAgent._generate_config(results, "unknown_viz")
        assert cfg == {}


class TestSummarizeResults:
    def test_empty_results(self):
        results = _qr(columns=["x"], rows=[])
        summary = VizAgent._summarize_results(results)
        assert summary == "No rows returned."
