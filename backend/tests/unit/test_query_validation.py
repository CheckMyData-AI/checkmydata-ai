"""Tests for query_validation data models."""

from app.connectors.base import QueryResult
from app.core.query_validation import (
    NON_RETRYABLE_ERRORS,
    QueryAttempt,
    QueryError,
    QueryErrorType,
    ValidationConfig,
    ValidationLoopResult,
    ValidationResult,
)


class TestQueryErrorType:
    def test_values(self):
        assert QueryErrorType.COLUMN_NOT_FOUND == "column_not_found"
        assert QueryErrorType.TABLE_NOT_FOUND == "table_not_found"
        assert QueryErrorType.UNKNOWN == "unknown"

    def test_non_retryable(self):
        assert QueryErrorType.PERMISSION_DENIED in NON_RETRYABLE_ERRORS
        assert QueryErrorType.CONNECTION_ERROR in NON_RETRYABLE_ERRORS
        assert QueryErrorType.COLUMN_NOT_FOUND not in NON_RETRYABLE_ERRORS


class TestQueryError:
    def test_to_dict(self):
        err = QueryError(
            error_type=QueryErrorType.COLUMN_NOT_FOUND,
            message="Column 'user_name' not found",
            raw_error="column user_name does not exist",
            suggested_columns=["username"],
        )
        d = err.to_dict()
        assert d["error_type"] == "column_not_found"
        assert d["suggested_columns"] == ["username"]


class TestQueryAttempt:
    def test_to_dict_with_error(self):
        att = QueryAttempt(
            attempt_number=1,
            query="SELECT user_name FROM users",
            explanation="Get user names",
            error=QueryError(
                error_type=QueryErrorType.COLUMN_NOT_FOUND,
                message="Column not found",
                raw_error="err",
            ),
            elapsed_ms=123.456,
        )
        d = att.to_dict()
        assert d["attempt"] == 1
        assert d["error"] == "Column not found"
        assert d["error_type"] == "column_not_found"
        assert d["elapsed_ms"] == 123.5

    def test_to_dict_success(self):
        att = QueryAttempt(
            attempt_number=1,
            query="SELECT username FROM users",
            explanation="ok",
        )
        d = att.to_dict()
        assert d["error"] is None
        assert d["error_type"] is None


class TestValidationResult:
    def test_valid(self):
        r = ValidationResult(is_valid=True)
        assert r.is_valid
        assert r.error is None
        assert r.warnings == []

    def test_invalid_with_error(self):
        r = ValidationResult(
            is_valid=False,
            error=QueryError(
                error_type=QueryErrorType.SYNTAX_ERROR,
                message="bad sql",
                raw_error="err",
            ),
        )
        assert not r.is_valid
        assert r.error is not None


class TestValidationLoopResult:
    def test_success(self):
        r = ValidationLoopResult(
            success=True,
            query="SELECT 1",
            explanation="test",
            results=QueryResult(columns=["1"], rows=[[1]], row_count=1),
            total_attempts=1,
        )
        assert r.success
        assert r.total_attempts == 1


class TestValidationConfig:
    def test_defaults(self):
        cfg = ValidationConfig()
        assert cfg.max_retries == 3
        assert cfg.enable_explain is True
        assert cfg.empty_result_retry is False
