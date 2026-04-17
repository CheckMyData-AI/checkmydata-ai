"""Tests for smart retry strategy."""

from app.connectors.base import ColumnInfo, SchemaInfo, TableInfo
from app.core.query_validation import QueryError, QueryErrorType
from app.core.retry_strategy import RetryStrategy


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
        ],
        db_type="postgresql",
    )


def _error(etype: QueryErrorType, retryable: bool = True) -> QueryError:
    return QueryError(
        error_type=etype,
        message="test",
        raw_error="test",
        is_retryable=retryable,
    )


class TestShouldRetry:
    def setup_method(self):
        self.strategy = RetryStrategy()

    def test_column_not_found_retryable(self):
        assert self.strategy.should_retry(_error(QueryErrorType.COLUMN_NOT_FOUND), 1, 3)

    def test_table_not_found_retryable(self):
        assert self.strategy.should_retry(_error(QueryErrorType.TABLE_NOT_FOUND), 1, 3)

    def test_syntax_error_retryable(self):
        assert self.strategy.should_retry(_error(QueryErrorType.SYNTAX_ERROR), 1, 3)

    def test_timeout_retryable(self):
        assert self.strategy.should_retry(_error(QueryErrorType.TIMEOUT), 1, 3)

    def test_permission_denied_not_retryable(self):
        assert not self.strategy.should_retry(
            _error(QueryErrorType.PERMISSION_DENIED, retryable=False),
            1,
            3,
        )

    def test_connection_error_not_retryable(self):
        assert not self.strategy.should_retry(
            _error(QueryErrorType.CONNECTION_ERROR, retryable=False),
            1,
            3,
        )

    def test_max_attempts_exceeded(self):
        assert not self.strategy.should_retry(
            _error(QueryErrorType.COLUMN_NOT_FOUND),
            3,
            3,
        )

    def test_not_retryable_flag(self):
        err = _error(QueryErrorType.COLUMN_NOT_FOUND, retryable=False)
        assert not self.strategy.should_retry(err, 1, 3)


class TestRepairHints:
    def setup_method(self):
        self.strategy = RetryStrategy()
        self.schema = _schema()

    def test_always_includes_error_type_and_message(self):
        err = _error(QueryErrorType.SYNTAX_ERROR)
        hints = self.strategy.get_repair_hints(err, self.schema)
        assert "syntax_error" in hints
        assert "test" in hints
        assert "postgresql" in hints

    def test_column_not_found_includes_similar_columns(self):
        err = _error(QueryErrorType.COLUMN_NOT_FOUND)
        err.suggested_columns = ["user_name"]
        hints = self.strategy.get_repair_hints(err, self.schema)
        assert "username" in hints.lower()
        assert "similarity" in hints.lower()

    def test_table_not_found_includes_similar_tables(self):
        err = _error(QueryErrorType.TABLE_NOT_FOUND)
        err.suggested_tables = ["userz"]
        hints = self.strategy.get_repair_hints(err, self.schema)
        assert "users" in hints.lower()

    def test_collation_mismatch_retryable(self):
        assert self.strategy.should_retry(_error(QueryErrorType.COLLATION_MISMATCH), 1, 3)

    def test_generic_error_returns_raw_context(self):
        err = _error(QueryErrorType.UNKNOWN)
        hints = self.strategy.get_repair_hints(err, self.schema)
        assert "unknown" in hints
        assert "test" in hints
        assert len(hints) > 0
