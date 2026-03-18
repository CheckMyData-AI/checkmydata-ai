"""Unit tests for LearningAnalyzer heuristic extractors."""


from app.core.query_validation import QueryAttempt, QueryError, QueryErrorType
from app.knowledge.learning_analyzer import LearningAnalyzer, _extract_tables


class TestExtractTables:
    def test_simple_select(self):
        assert _extract_tables("SELECT * FROM orders") == ["orders"]

    def test_join(self):
        tables = _extract_tables("SELECT * FROM orders JOIN users ON orders.user_id = users.id")
        assert "orders" in tables
        assert "users" in tables

    def test_schema_prefixed(self):
        tables = _extract_tables('SELECT * FROM public."orders_v2"')
        assert "orders_v2" in tables

    def test_case_insensitive(self):
        tables = _extract_tables("select * from Orders")
        assert tables == ["orders"]


class TestTablePreference:
    def test_detects_table_switch(self):
        analyzer = LearningAnalyzer()
        attempts = [
            QueryAttempt(
                attempt_number=1,
                query="SELECT * FROM orders_legacy",
                explanation="Using legacy orders",
                error=QueryError(
                    error_type=QueryErrorType.EMPTY_RESULT,
                    message="No rows returned",
                    raw_error="Empty result",
                ),
                results=None,
            ),
            QueryAttempt(
                attempt_number=2,
                query="SELECT * FROM orders_v2",
                explanation="Trying v2",
                error=None,
                results=_mock_result(),
            ),
        ]
        lessons = analyzer._detect_table_preference(attempts, "Show me revenue")
        assert len(lessons) >= 1
        assert lessons[0].category == "table_preference"
        assert "orders_v2" in lessons[0].lesson
        assert "orders_legacy" in lessons[0].lesson

    def test_no_switch_detected(self):
        analyzer = LearningAnalyzer()
        attempts = [
            QueryAttempt(
                attempt_number=1,
                query="SELECT * FROM orders",
                explanation="",
                error=None,
                results=_mock_result(),
            ),
        ]
        lessons = analyzer._detect_table_preference(attempts, "test")
        assert lessons == []


class TestColumnCorrection:
    def test_detects_column_fix(self):
        analyzer = LearningAnalyzer()
        attempts = [
            QueryAttempt(
                attempt_number=1,
                query="SELECT amount_total FROM orders",
                explanation="",
                error=QueryError(
                    error_type=QueryErrorType.COLUMN_NOT_FOUND,
                    message="column 'amount_total' not found",
                    raw_error="",
                    suggested_columns=["total_amount"],
                ),
            ),
            QueryAttempt(
                attempt_number=2,
                query="SELECT total_amount FROM orders",
                explanation="",
                error=None,
                results=_mock_result(),
            ),
        ]
        lessons = analyzer._detect_column_correction(attempts)
        assert len(lessons) >= 1
        assert lessons[0].category == "column_usage"
        assert "amount_total" in lessons[0].lesson
        assert "total_amount" in lessons[0].lesson


class TestFormatDiscovery:
    def test_detects_cents_division(self):
        analyzer = LearningAnalyzer()
        attempts = [
            QueryAttempt(
                attempt_number=1,
                query="SELECT amount FROM orders",
                explanation="",
                error=QueryError(
                    error_type=QueryErrorType.EMPTY_RESULT,
                    message="Values look wrong",
                    raw_error="",
                ),
            ),
            QueryAttempt(
                attempt_number=2,
                query="SELECT amount / 100 FROM orders",
                explanation="",
                error=None,
                results=_mock_result(),
            ),
        ]
        lessons = analyzer._detect_format_discovery(attempts)
        assert len(lessons) >= 1
        assert lessons[0].category == "data_format"
        assert "cents" in lessons[0].lesson.lower() or "100" in lessons[0].lesson


class TestSchemaGotcha:
    def test_detects_soft_delete(self):
        analyzer = LearningAnalyzer()
        attempts = [
            QueryAttempt(
                attempt_number=1,
                query="SELECT * FROM users",
                explanation="",
                error=QueryError(
                    error_type=QueryErrorType.EMPTY_RESULT,
                    message="Includes deleted records",
                    raw_error="",
                ),
            ),
            QueryAttempt(
                attempt_number=2,
                query="SELECT * FROM users WHERE deleted_at IS NULL",
                explanation="",
                error=None,
                results=_mock_result(),
            ),
        ]
        lessons = analyzer._detect_schema_gotcha(attempts)
        assert len(lessons) >= 1
        assert lessons[0].category == "schema_gotcha"
        assert "soft-delete" in lessons[0].lesson.lower() or "deleted_at" in lessons[0].lesson


class TestPerformanceHint:
    def test_detects_timeout_fix(self):
        analyzer = LearningAnalyzer()
        attempts = [
            QueryAttempt(
                attempt_number=1,
                query="SELECT * FROM events",
                explanation="",
                error=QueryError(
                    error_type=QueryErrorType.TIMEOUT,
                    message="Query timeout",
                    raw_error="",
                ),
            ),
            QueryAttempt(
                attempt_number=2,
                query="SELECT * FROM events WHERE created_at > '2025-01-01' LIMIT 1000",
                explanation="",
                error=None,
                results=_mock_result(),
            ),
        ]
        lessons = analyzer._detect_performance_hint(attempts)
        assert len(lessons) >= 1
        assert lessons[0].category == "performance_hint"
        assert "timeout" in lessons[0].lesson.lower()


def _mock_result():
    """Create a minimal non-None mock for QueryResult."""
    from unittest.mock import MagicMock

    from app.connectors.base import QueryResult

    result = MagicMock(spec=QueryResult)
    result.columns = ["col1"]
    result.rows = [[1]]
    result.total_rows = 1
    return result
