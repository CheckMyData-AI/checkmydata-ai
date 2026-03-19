"""Extended tests for LearningAnalyzer: full pipeline, edge cases, and untested patterns."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.connectors.base import QueryResult
from app.core.query_validation import QueryAttempt, QueryError, QueryErrorType
from app.knowledge.learning_analyzer import LearningAnalyzer, LLMAnalyzer


def _mock_result(rows=None):
    result = MagicMock(spec=QueryResult)
    result.columns = ["col1"]
    result.rows = rows or [[1]]
    result.row_count = len(result.rows)
    result.total_rows = len(result.rows)
    return result


class TestAnalyzeFullPipeline:
    @pytest.mark.asyncio
    async def test_analyze_fires_extractors_and_stores(self):
        """End-to-end: heuristic extractors fire, lessons stored via service."""
        attempts = [
            QueryAttempt(
                attempt_number=1,
                query="SELECT * FROM orders_legacy",
                explanation="",
                error=QueryError(
                    error_type=QueryErrorType.EMPTY_RESULT,
                    message="No rows",
                    raw_error="",
                ),
            ),
            QueryAttempt(
                attempt_number=2,
                query="SELECT * FROM orders_v2",
                explanation="",
                error=None,
                results=_mock_result(),
            ),
        ]

        mock_svc = MagicMock()
        mock_svc.create_learning = AsyncMock(return_value=MagicMock())

        session = AsyncMock()

        with patch(
            "app.services.agent_learning_service.AgentLearningService",
            return_value=mock_svc,
        ):
            analyzer = LearningAnalyzer()
            lessons = await analyzer.analyze(
                session=session,
                connection_id="conn-1",
                question="Show revenue",
                attempts=attempts,
                success=True,
            )

        assert len(lessons) >= 1
        assert mock_svc.create_learning.call_count >= 1
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_analyze_single_attempt_no_lessons(self):
        attempts = [
            QueryAttempt(
                attempt_number=1,
                query="SELECT * FROM orders",
                explanation="",
                error=None,
                results=_mock_result(),
            ),
        ]
        analyzer = LearningAnalyzer()
        lessons = await analyzer.analyze(
            session=AsyncMock(),
            connection_id="conn-1",
            question="test",
            attempts=attempts,
            success=True,
        )
        assert lessons == []

    @pytest.mark.asyncio
    async def test_analyze_all_failed_attempts(self):
        attempts = [
            QueryAttempt(
                attempt_number=1,
                query="SELECT * FROM bad_table",
                explanation="",
                error=QueryError(
                    error_type=QueryErrorType.TABLE_NOT_FOUND,
                    message="Table not found",
                    raw_error="",
                ),
            ),
            QueryAttempt(
                attempt_number=2,
                query="SELECT * FROM another_bad",
                explanation="",
                error=QueryError(
                    error_type=QueryErrorType.TABLE_NOT_FOUND,
                    message="Table not found",
                    raw_error="",
                ),
            ),
        ]
        analyzer = LearningAnalyzer()
        lessons = await analyzer.analyze(
            session=AsyncMock(),
            connection_id="conn-1",
            question="test",
            attempts=attempts,
            success=False,
        )
        assert isinstance(lessons, list)

    @pytest.mark.asyncio
    async def test_analyze_empty_connection_id(self):
        analyzer = LearningAnalyzer()
        lessons = await analyzer.analyze(
            session=AsyncMock(),
            connection_id="",
            question="test",
            attempts=[],
            success=False,
        )
        assert lessons == []


class TestAnalyzeNegativeFeedback:
    @pytest.mark.asyncio
    async def test_creates_learning_from_feedback(self):
        mock_svc = MagicMock()
        mock_svc.create_learning = AsyncMock(return_value=MagicMock())

        session = AsyncMock()

        with patch(
            "app.services.agent_learning_service.AgentLearningService",
            return_value=mock_svc,
        ):
            analyzer = LearningAnalyzer()
            lessons = await analyzer.analyze_negative_feedback(
                session=session,
                connection_id="conn-1",
                query="SELECT * FROM orders",
                question="Show me revenue",
                error_detail="Wrong data returned",
            )

        assert len(lessons) == 1
        assert lessons[0].category == "query_pattern"
        mock_svc.create_learning.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_query_returns_empty(self):
        analyzer = LearningAnalyzer()
        lessons = await analyzer.analyze_negative_feedback(
            session=AsyncMock(),
            connection_id="conn-1",
            query=None,
            question="test",
        )
        assert lessons == []

    @pytest.mark.asyncio
    async def test_no_error_detail_returns_empty(self):
        analyzer = LearningAnalyzer()
        lessons = await analyzer.analyze_negative_feedback(
            session=AsyncMock(),
            connection_id="conn-1",
            query="SELECT 1",
            question="test",
            error_detail=None,
        )
        assert lessons == []


class TestFormatDiscoveryExtended:
    def test_thousands_division(self):
        analyzer = LearningAnalyzer()
        attempts = [
            QueryAttempt(
                attempt_number=1,
                query="SELECT price FROM products",
                explanation="",
                error=QueryError(
                    error_type=QueryErrorType.EMPTY_RESULT,
                    message="Values look wrong",
                    raw_error="",
                ),
            ),
            QueryAttempt(
                attempt_number=2,
                query="SELECT price / 1000 FROM products",
                explanation="",
                error=None,
                results=_mock_result(),
            ),
        ]
        lessons = analyzer._detect_format_discovery(attempts)
        assert len(lessons) >= 1
        assert lessons[0].category == "data_format"
        lesson_texts = " ".join(ls.lesson for ls in lessons)
        assert "1000" in lesson_texts or "100" in lesson_texts

    def test_text_cast(self):
        analyzer = LearningAnalyzer()
        attempts = [
            QueryAttempt(
                attempt_number=1,
                query="SELECT status FROM orders WHERE status = 'active'",
                explanation="",
                error=QueryError(
                    error_type=QueryErrorType.SYNTAX_ERROR,
                    message="type mismatch",
                    raw_error="",
                ),
            ),
            QueryAttempt(
                attempt_number=2,
                query="SELECT status::text FROM orders WHERE status::text = 'active'",
                explanation="",
                error=None,
                results=_mock_result(),
            ),
        ]
        lessons = analyzer._detect_format_discovery(attempts)
        assert len(lessons) >= 1
        assert "::text" in lessons[0].lesson


class TestSchemaGotchaExtended:
    def test_is_deleted_pattern(self):
        analyzer = LearningAnalyzer()
        attempts = [
            QueryAttempt(
                attempt_number=1,
                query="SELECT * FROM users",
                explanation="",
                error=QueryError(
                    error_type=QueryErrorType.EMPTY_RESULT,
                    message="Includes deleted",
                    raw_error="",
                ),
            ),
            QueryAttempt(
                attempt_number=2,
                query="SELECT * FROM users WHERE is_deleted = 0",
                explanation="",
                error=None,
                results=_mock_result(),
            ),
        ]
        lessons = analyzer._detect_schema_gotcha(attempts)
        assert len(lessons) >= 1
        assert "is_deleted" in lessons[0].lesson

    def test_schema_prefix_pattern(self):
        analyzer = LearningAnalyzer()
        attempts = [
            QueryAttempt(
                attempt_number=1,
                query="SELECT * FROM orders",
                explanation="",
                error=QueryError(
                    error_type=QueryErrorType.SYNTAX_ERROR,
                    message="Schema 'public' not found for table",
                    raw_error="",
                ),
            ),
            QueryAttempt(
                attempt_number=2,
                query="SELECT * FROM public.orders",
                explanation="",
                error=None,
                results=_mock_result(),
            ),
        ]
        lessons = analyzer._detect_schema_gotcha(attempts)
        assert len(lessons) >= 1
        assert "schema" in lessons[0].lesson.lower() or "public" in lessons[0].lesson


class TestColumnCorrectionEdgeCases:
    def test_no_suggested_columns(self):
        analyzer = LearningAnalyzer()
        attempts = [
            QueryAttempt(
                attempt_number=1,
                query="SELECT bad_col FROM orders",
                explanation="",
                error=QueryError(
                    error_type=QueryErrorType.COLUMN_NOT_FOUND,
                    message="column 'bad_col' not found",
                    raw_error="",
                    suggested_columns=None,
                ),
            ),
            QueryAttempt(
                attempt_number=2,
                query="SELECT good_col FROM orders",
                explanation="",
                error=None,
                results=_mock_result(),
            ),
        ]
        lessons = analyzer._detect_column_correction(attempts)
        assert lessons == []


class TestLLMAnalyzer:
    def test_should_run_first_time(self):
        assert LLMAnalyzer.should_run("brand-new-conn") is True

    def test_cooldown_prevents_rerun(self):
        LLMAnalyzer._mark_run("cooldown-test")
        assert LLMAnalyzer.should_run("cooldown-test") is False

    def test_format_attempts(self):
        attempts = [
            QueryAttempt(
                attempt_number=1,
                query="SELECT * FROM orders",
                explanation="",
                error=QueryError(
                    error_type=QueryErrorType.TIMEOUT,
                    message="Query timed out",
                    raw_error="",
                ),
            ),
            QueryAttempt(
                attempt_number=2,
                query="SELECT * FROM orders LIMIT 100",
                explanation="",
                error=None,
                results=_mock_result(),
            ),
        ]
        text = LLMAnalyzer._format_attempts(attempts)
        assert "Attempt 1 (FAILED)" in text
        assert "Attempt 2 (SUCCESS)" in text
        assert "timed out" in text
