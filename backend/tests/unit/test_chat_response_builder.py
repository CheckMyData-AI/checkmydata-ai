"""Unit tests for :mod:`app.services.chat_response_builder` (T23)."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.chat_response_builder import (
    build_raw_result,
    build_search_snippet,
    build_sql_results_payload,
    build_structured_error,
    has_rules_changed,
)


class TestHasRulesChanged:
    def test_empty_log_false(self):
        assert has_rules_changed(None) is False
        assert has_rules_changed([]) is False

    def test_detects_manage_rules(self):
        assert has_rules_changed([{"tool": "manage_rules"}]) is True

    def test_detects_manage_custom_rules(self):
        assert has_rules_changed([{"tool": "manage_custom_rules"}]) is True

    def test_ignores_other_tools(self):
        assert has_rules_changed([{"tool": "sql_agent"}]) is False


class TestBuildStructuredError:
    def test_plain_exception(self):
        payload = build_structured_error(RuntimeError("boom"))
        assert payload["error_type"] == "internal"
        assert payload["is_retryable"] is True
        assert "unexpected" in payload["user_message"].lower()

    def test_llm_error_preserves_fields(self):
        from app.llm.errors import LLMRateLimitError

        exc = LLMRateLimitError("rate limited")
        payload = build_structured_error(exc)
        assert payload["error_type"] == "LLMRateLimitError"
        assert payload["is_retryable"] is True
        assert "overloaded" in payload["user_message"].lower()


class TestBuildRawResult:
    def test_no_results(self):
        assert build_raw_result(None, row_cap=100) is None

    def test_missing_columns(self):
        res = SimpleNamespace(columns=None, rows=[[1]])
        assert build_raw_result(res, row_cap=100) is None

    def test_caps_rows(self):
        res = SimpleNamespace(
            columns=["c"],
            rows=[[i] for i in range(10)],
            row_count=10,
        )
        out = build_raw_result(res, row_cap=3)
        assert out is not None
        assert len(out["rows"]) == 3
        assert out["total_rows"] == 10


class TestBuildSqlResultsPayload:
    def test_single_block_returns_none(self):
        blk = SimpleNamespace(
            query="SELECT 1",
            query_explanation="",
            results=None,
            viz_type="table",
            viz_config=None,
            insights=None,
        )
        assert build_sql_results_payload([blk], row_cap=100, answer="hi") is None

    def test_multiple_blocks_no_rows_skip_viz(self):
        blk = SimpleNamespace(
            query="SELECT 1",
            query_explanation="e",
            results=None,
            viz_type="table",
            viz_config=None,
            insights=[],
        )
        out = build_sql_results_payload([blk, blk], row_cap=100, answer="")
        assert out is not None
        assert len(out) == 2
        assert out[0]["visualization"] is None


class TestBuildSearchSnippet:
    def test_query_not_found_truncates(self):
        long_text = "abc" * 200
        snippet = build_search_snippet(long_text, "xyz", max_len=30)
        assert snippet.endswith("...")
        assert len(snippet) <= 33

    def test_query_found_centers(self):
        text = "x" * 100 + "needle" + "y" * 100
        snippet = build_search_snippet(text, "needle", max_len=60)
        assert "needle" in snippet


class TestBuildSynthesisMessagesPartialData:
    """DATA-04a: truncated results must surface as an explicit PARTIAL DATA line."""

    def test_synthesis_surfaces_partial_data_when_truncated(self):
        from app.agents.response_builder import ResponseBuilder
        from app.agents.sql_agent import SQLAgentResult
        from app.connectors.base import QueryResult
        from app.llm.base import Message

        sr = SQLAgentResult(
            query="SELECT SUM(amount) FROM purchases",
            query_explanation="total revenue",
            results=QueryResult(columns=["total"], rows=[[123456]], row_count=1, truncated=True),
        )
        msgs = ResponseBuilder.build_synthesis_messages(
            loop_messages=[
                Message(role="system", content="s"),
                Message(role="user", content="revenue?"),
            ],
            sql_result=sr,
            knowledge_sources=[],
            context_window=8000,
        )
        joined = "\n".join(m.content for m in msgs)
        assert "PARTIAL DATA" in joined

    def test_synthesis_no_partial_line_when_not_truncated(self):
        from app.agents.response_builder import ResponseBuilder
        from app.agents.sql_agent import SQLAgentResult
        from app.connectors.base import QueryResult
        from app.llm.base import Message

        sr = SQLAgentResult(
            query="SELECT SUM(amount) FROM purchases",
            query_explanation="total revenue",
            results=QueryResult(columns=["total"], rows=[[123456]], row_count=1, truncated=False),
        )
        msgs = ResponseBuilder.build_synthesis_messages(
            loop_messages=[
                Message(role="system", content="s"),
                Message(role="user", content="revenue?"),
            ],
            sql_result=sr,
            knowledge_sources=[],
            context_window=8000,
        )
        joined = "\n".join(m.content for m in msgs)
        assert "PARTIAL DATA" not in joined


# ---------------------------------------------------------------------------
# Fixtures for pipeline-response truncation tests (DATA-04b)
# ---------------------------------------------------------------------------

import pytest  # noqa: E402


@pytest.fixture
def pipeline_exec_result_truncated():
    """Minimal completed pipeline exec-result whose shown result is truncated."""
    from app.agents.stage_context import ExecutionPlan, PlanStage, StageContext, StageResult
    from app.connectors.base import QueryResult

    stage = PlanStage(stage_id="s1", description="revenue", tool="query_database")
    plan = ExecutionPlan(plan_id="p1", question="What is total revenue?", stages=[stage])
    stage_ctx = StageContext(plan=plan)
    stage_ctx.set_result(
        "s1",
        StageResult(
            stage_id="s1",
            status="success",
            query="SELECT SUM(amount) FROM purchases",
            query_result=QueryResult(
                columns=["total"], rows=[[123456]], row_count=1, truncated=True
            ),
        ),
    )
    from app.agents.stage_executor import _StageExecutorResult

    return _StageExecutorResult(
        status="completed",
        stage_ctx=stage_ctx,
        final_answer="Revenue is 123456.",
    )


@pytest.fixture
def pipeline_exec_result_not_truncated():
    """Minimal completed pipeline exec-result whose shown result is NOT truncated."""
    from app.agents.stage_context import ExecutionPlan, PlanStage, StageContext, StageResult
    from app.connectors.base import QueryResult

    stage = PlanStage(stage_id="s1", description="revenue", tool="query_database")
    plan = ExecutionPlan(plan_id="p1", question="What is total revenue?", stages=[stage])
    stage_ctx = StageContext(plan=plan)
    stage_ctx.set_result(
        "s1",
        StageResult(
            stage_id="s1",
            status="success",
            query="SELECT SUM(amount) FROM purchases",
            query_result=QueryResult(
                columns=["total"], rows=[[123456]], row_count=1, truncated=False
            ),
        ),
    )
    from app.agents.stage_executor import _StageExecutorResult

    return _StageExecutorResult(
        status="completed",
        stage_ctx=stage_ctx,
        final_answer="Revenue is 123456.",
    )


class TestBuildPipelineResponsePartialData:
    """DATA-04b: pipeline answer must surface truncation of the shown result."""

    def test_pipeline_response_appends_partial_data_when_truncated(
        self, pipeline_exec_result_truncated
    ):
        from app.agents.response_builder import ResponseBuilder

        resp = ResponseBuilder.build_pipeline_response(
            pipeline_exec_result_truncated,
            wf_id="wf1",
            staleness_warning=None,
            pipeline_run_id="run1",
        )
        assert "PARTIAL DATA" in resp.answer
        assert resp.results is not None and resp.results.truncated is True

    def test_pipeline_response_no_partial_data_when_not_truncated(
        self, pipeline_exec_result_not_truncated
    ):
        from app.agents.response_builder import ResponseBuilder

        resp = ResponseBuilder.build_pipeline_response(
            pipeline_exec_result_not_truncated,
            wf_id="wf1",
            staleness_warning=None,
            pipeline_run_id="run1",
        )
        assert "PARTIAL DATA" not in resp.answer
