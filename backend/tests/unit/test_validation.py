"""Unit tests for app.agents.validation."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from app.agents.validation import AgentResultValidator

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

validator = AgentResultValidator()


def _sql_result(
    *,
    status: str = "success",
    error: str | None = None,
    query: str | None = "SELECT 1",
    row_count: int = 5,
    execution_time_ms: float = 100.0,
    qr_error: str | None = None,
    has_results: bool = True,
):
    qr = None
    if has_results:
        qr = SimpleNamespace(
            row_count=row_count,
            execution_time_ms=execution_time_ms,
            error=qr_error,
        )
    return SimpleNamespace(status=status, error=error, query=query, results=qr)


def _viz_result(*, viz_type: str = "table"):
    return SimpleNamespace(viz_type=viz_type)


def _knowledge_result(
    *,
    status: str = "success",
    error: str | None = None,
    answer: str = "Some answer",
    sources: list | None = None,
):
    return SimpleNamespace(
        status=status,
        error=error,
        answer=answer,
        sources=sources if sources is not None else ["src1"],
    )


# ==================================================================
# validate_sql_result
# ==================================================================


class TestValidateSqlResult:
    def test_error_status(self):
        res = _sql_result(status="error", error="timeout")
        out = validator.validate_sql_result(res)
        assert out.passed is False
        assert "timeout" in out.errors[0]

    def test_no_query(self):
        res = _sql_result(query=None)
        out = validator.validate_sql_result(res)
        assert out.passed is False
        assert any("query" in e.lower() for e in out.errors)

    def test_empty_query_string(self):
        res = _sql_result(query="")
        out = validator.validate_sql_result(res)
        assert out.passed is False

    def test_no_results_object(self):
        res = _sql_result(has_results=False)
        out = validator.validate_sql_result(res)
        assert out.passed is False
        assert any("results" in e.lower() for e in out.errors)

    def test_execution_error(self):
        res = _sql_result(qr_error="relation does not exist")
        out = validator.validate_sql_result(res)
        assert out.passed is False
        assert any("relation" in e for e in out.errors)

    def test_zero_rows_warning(self):
        res = _sql_result(row_count=0)
        out = validator.validate_sql_result(res)
        assert out.passed is True
        assert any("zero rows" in w.lower() for w in out.warnings)

    def test_slow_query_warning(self):
        res = _sql_result(execution_time_ms=45_000)
        out = validator.validate_sql_result(res)
        assert out.passed is True
        assert any("45000" in w for w in out.warnings)

    def test_success(self):
        res = _sql_result()
        out = validator.validate_sql_result(res)
        assert out.passed is True
        assert out.warnings == []
        assert out.errors == []


# ==================================================================
# validate_viz_result
# ==================================================================


class TestValidateVizResult:
    def test_invalid_viz_type(self):
        res = _viz_result(viz_type="hologram")
        out = validator.validate_viz_result(res)
        assert out.passed is False
        assert any("hologram" in e for e in out.errors)

    @patch("app.agents.validation.settings")
    def test_pie_chart_too_many_slices(self, mock_settings):
        mock_settings.max_pie_categories = 20
        res = _viz_result(viz_type="pie_chart")
        out = validator.validate_viz_result(res, row_count=50)
        assert out.passed is True
        assert any("pie" in w.lower() for w in out.warnings)

    @patch("app.agents.validation.settings")
    def test_pie_chart_within_limit(self, mock_settings):
        mock_settings.max_pie_categories = 20
        res = _viz_result(viz_type="pie_chart")
        out = validator.validate_viz_result(res, row_count=10)
        assert out.passed is True
        assert out.warnings == []

    def test_bar_chart_single_column(self):
        res = _viz_result(viz_type="bar_chart")
        out = validator.validate_viz_result(res, column_count=1)
        assert out.passed is True
        assert any("2 columns" in w for w in out.warnings)

    def test_line_chart_single_column(self):
        res = _viz_result(viz_type="line_chart")
        out = validator.validate_viz_result(res, column_count=1)
        assert any("2 columns" in w for w in out.warnings)

    def test_scatter_single_column(self):
        res = _viz_result(viz_type="scatter")
        out = validator.validate_viz_result(res, column_count=0)
        assert any("2 columns" in w for w in out.warnings)

    @patch("app.agents.validation.settings")
    def test_success(self, mock_settings):
        mock_settings.max_pie_categories = 20
        res = _viz_result(viz_type="bar_chart")
        out = validator.validate_viz_result(res, row_count=10, column_count=3)
        assert out.passed is True
        assert out.warnings == []
        assert out.errors == []


# ==================================================================
# validate_knowledge_result
# ==================================================================


class TestValidateKnowledgeResult:
    def test_error_status(self):
        res = _knowledge_result(status="error", error="retrieval failed")
        out = validator.validate_knowledge_result(res)
        assert out.passed is False
        assert "retrieval failed" in out.errors[0]

    def test_empty_answer_warning(self):
        res = _knowledge_result(answer="")
        out = validator.validate_knowledge_result(res)
        assert out.passed is True
        assert any("empty" in w.lower() for w in out.warnings)

    def test_no_sources_warning(self):
        res = _knowledge_result(sources=[])
        out = validator.validate_knowledge_result(res)
        assert out.passed is True
        assert any("source" in w.lower() for w in out.warnings)

    def test_success(self):
        res = _knowledge_result()
        out = validator.validate_knowledge_result(res)
        assert out.passed is True
        assert out.warnings == []
        assert out.errors == []

    def test_error_status_default_message(self):
        res = _knowledge_result(status="error", error=None)
        out = validator.validate_knowledge_result(res)
        assert out.passed is False
        assert any("error" in e.lower() for e in out.errors)
