"""Tests for ContextEnricher."""

from unittest.mock import MagicMock

import pytest

from app.connectors.base import ColumnInfo, SchemaInfo, TableInfo
from app.core.context_enricher import ContextEnricher
from app.core.query_validation import QueryAttempt, QueryError, QueryErrorType


def _schema() -> SchemaInfo:
    return SchemaInfo(
        tables=[
            TableInfo(
                name="users",
                columns=[
                    ColumnInfo(name="id", data_type="int"),
                    ColumnInfo(name="username", data_type="varchar"),
                ],
            ),
            TableInfo(
                name="orders",
                columns=[
                    ColumnInfo(name="id", data_type="int"),
                    ColumnInfo(name="user_id", data_type="int"),
                ],
            ),
        ],
        db_type="postgresql",
    )


class TestContextEnricher:
    @pytest.mark.asyncio
    async def test_column_error_enrichment(self):
        enricher = ContextEnricher(_schema())
        err = QueryError(
            error_type=QueryErrorType.COLUMN_NOT_FOUND,
            message="Column 'user_name' not found",
            raw_error="column user_name does not exist",
            suggested_columns=["user_name"],
        )
        ctx = await enricher.build_repair_context(
            error=err,
            original_question="get usernames",
            failed_query="SELECT user_name FROM users",
            attempt_history=[],
        )
        assert "user_name" in ctx
        assert "Original Question" in ctx
        assert "Failed Query" in ctx

    @pytest.mark.asyncio
    async def test_table_error_enrichment(self):
        enricher = ContextEnricher(_schema())
        err = QueryError(
            error_type=QueryErrorType.TABLE_NOT_FOUND,
            message="Table 'userz' not found",
            raw_error="relation userz does not exist",
            suggested_tables=["userz"],
        )
        ctx = await enricher.build_repair_context(
            error=err,
            original_question="get users",
            failed_query="SELECT * FROM userz",
            attempt_history=[],
        )
        assert "users" in ctx.lower()
        assert "orders" in ctx.lower()

    @pytest.mark.asyncio
    async def test_with_rag_results(self):
        mock_vs = MagicMock()
        mock_vs.query.return_value = [
            {"document": "users table has username column", "distance": 0.3},
        ]
        enricher = ContextEnricher(_schema(), vector_store=mock_vs)
        err = QueryError(
            error_type=QueryErrorType.COLUMN_NOT_FOUND,
            message="Column not found",
            raw_error="err",
            suggested_columns=["user_name"],
        )
        ctx = await enricher.build_repair_context(
            error=err,
            original_question="q",
            failed_query="SELECT user_name FROM users",
            attempt_history=[],
            project_id="proj1",
        )
        assert "Documentation" in ctx
        assert "username" in ctx

    @pytest.mark.asyncio
    async def test_rag_filters_low_relevance(self):
        mock_vs = MagicMock()
        mock_vs.query.return_value = [
            {"document": "irrelevant doc about logging", "distance": 0.9},
        ]
        enricher = ContextEnricher(_schema(), vector_store=mock_vs)
        err = QueryError(
            error_type=QueryErrorType.COLUMN_NOT_FOUND,
            message="not found",
            raw_error="err",
            suggested_columns=["user_name"],
        )
        ctx = await enricher.build_repair_context(
            error=err,
            original_question="q",
            failed_query="SELECT user_name FROM users",
            attempt_history=[],
            project_id="proj1",
        )
        assert "Documentation" not in ctx
        assert "irrelevant" not in ctx

    @pytest.mark.asyncio
    async def test_without_rag(self):
        enricher = ContextEnricher(_schema(), vector_store=None)
        err = QueryError(
            error_type=QueryErrorType.SYNTAX_ERROR,
            message="Syntax error",
            raw_error="syntax error near SELCT",
        )
        ctx = await enricher.build_repair_context(
            error=err,
            original_question="q",
            failed_query="SELCT * FROM users",
            attempt_history=[],
        )
        assert "Documentation" not in ctx
        assert "syntax" in ctx.lower()

    @pytest.mark.asyncio
    async def test_with_sync_context(self):
        enricher = ContextEnricher(
            _schema(),
            sync_context="- orders.amount: stored in cents, divide by 100",
        )
        err = QueryError(
            error_type=QueryErrorType.TYPE_MISMATCH,
            message="Type mismatch",
            raw_error="cannot compare",
        )
        ctx = await enricher.build_repair_context(
            error=err,
            original_question="total revenue",
            failed_query="SELECT SUM(amount) FROM orders",
            attempt_history=[],
        )
        assert "Data Format Warnings" in ctx
        assert "stored in cents" in ctx

    @pytest.mark.asyncio
    async def test_with_rules_context(self):
        enricher = ContextEnricher(
            _schema(),
            rules_context="Revenue = SUM(amount) / 100 for orders table",
        )
        err = QueryError(
            error_type=QueryErrorType.SYNTAX_ERROR,
            message="err",
            raw_error="err",
        )
        ctx = await enricher.build_repair_context(
            error=err,
            original_question="total revenue",
            failed_query="SELECT SUM(amount FROM orders",
            attempt_history=[],
        )
        assert "Business Rules" in ctx
        assert "Revenue = SUM(amount) / 100" in ctx

    @pytest.mark.asyncio
    async def test_with_distinct_values(self):
        enricher = ContextEnricher(
            _schema(),
            distinct_values={
                "orders": {"status": ["active", "cancelled", "pending"]},
            },
        )
        err = QueryError(
            error_type=QueryErrorType.EMPTY_RESULT,
            message="empty result",
            raw_error="empty",
        )
        ctx = await enricher.build_repair_context(
            error=err,
            original_question="active orders",
            failed_query="SELECT * FROM orders WHERE status = 'Active'",
            attempt_history=[],
        )
        assert "Column Distinct Values" in ctx
        assert "active" in ctx
        assert "cancelled" in ctx

    @pytest.mark.asyncio
    async def test_always_includes_schema_for_query_tables(self):
        enricher = ContextEnricher(_schema())
        err = QueryError(
            error_type=QueryErrorType.SYNTAX_ERROR,
            message="syntax error",
            raw_error="err",
        )
        ctx = await enricher.build_repair_context(
            error=err,
            original_question="get users",
            failed_query="SELCT * FROM users JOIN orders ON users.id = orders.user_id",
            attempt_history=[],
        )
        assert "Relevant Schema" in ctx
        assert "users" in ctx
        assert "orders" in ctx

    @pytest.mark.asyncio
    async def test_schema_qualified_table_parsed(self):
        """FROM schema.table includes the table in relevant schema."""
        enricher = ContextEnricher(_schema())
        err = QueryError(
            error_type=QueryErrorType.SYNTAX_ERROR,
            message="syntax error",
            raw_error="err",
        )
        ctx = await enricher.build_repair_context(
            error=err,
            original_question="get users",
            failed_query='SELECT * FROM "public"."users"',
            attempt_history=[],
        )
        assert "Relevant Schema" in ctx
        assert "users" in ctx

    @pytest.mark.asyncio
    async def test_column_substring_no_false_positive(self):
        """Column 'id' should not match inside 'invalid'."""
        enricher = ContextEnricher(
            _schema(),
            distinct_values={
                "users": {"id": ["1", "2", "3"]},
            },
        )
        err = QueryError(
            error_type=QueryErrorType.EMPTY_RESULT,
            message="empty",
            raw_error="empty",
        )
        ctx = await enricher.build_repair_context(
            error=err,
            original_question="find invalid users",
            failed_query="SELECT * FROM users WHERE status = 'invalid'",
            attempt_history=[],
        )
        assert "Column Distinct Values" not in ctx

    @pytest.mark.asyncio
    async def test_distinct_values_not_in_query_excluded(self):
        """Columns from tables not in the query should be excluded."""
        enricher = ContextEnricher(
            _schema(),
            distinct_values={
                "orders": {"status": ["active", "cancelled"]},
                "users": {"role": ["admin", "user"]},
            },
        )
        err = QueryError(
            error_type=QueryErrorType.EMPTY_RESULT,
            message="empty",
            raw_error="empty",
        )
        ctx = await enricher.build_repair_context(
            error=err,
            original_question="find active orders",
            failed_query="SELECT * FROM orders WHERE status = 'Active'",
            attempt_history=[],
        )
        assert "active" in ctx
        assert "role" not in ctx

    @pytest.mark.asyncio
    async def test_with_history(self):
        enricher = ContextEnricher(_schema())
        prev = QueryAttempt(
            attempt_number=1,
            query="SELECT user_name FROM users",
            explanation="first try",
            error=QueryError(
                error_type=QueryErrorType.COLUMN_NOT_FOUND,
                message="not found",
                raw_error="err",
            ),
        )
        err = QueryError(
            error_type=QueryErrorType.COLUMN_NOT_FOUND,
            message="still not found",
            raw_error="err2",
        )
        ctx = await enricher.build_repair_context(
            error=err,
            original_question="q",
            failed_query="SELECT user_nm FROM users",
            attempt_history=[prev, QueryAttempt(2, "q2", "e2")],
        )
        assert "Previous Attempts" in ctx
        assert "Attempt 1" in ctx
