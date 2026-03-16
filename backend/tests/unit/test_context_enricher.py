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
            {"document": "users table has username column"},
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
