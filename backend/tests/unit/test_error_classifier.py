"""Tests for ErrorClassifier — dialect-aware error classification."""

from app.core.error_classifier import ErrorClassifier
from app.core.query_validation import QueryErrorType


class TestPostgresClassification:
    def setup_method(self):
        self.clf = ErrorClassifier()

    def test_column_not_found(self):
        err = self.clf.classify(
            'ERROR: column "user_name" does not exist',
            "postgresql",
        )
        assert err.error_type == QueryErrorType.COLUMN_NOT_FOUND
        assert err.is_retryable
        assert "user_name" in err.suggested_columns

    def test_table_not_found(self):
        err = self.clf.classify(
            'ERROR: relation "userz" does not exist',
            "postgres",
        )
        assert err.error_type == QueryErrorType.TABLE_NOT_FOUND
        assert err.is_retryable
        assert "userz" in err.suggested_tables

    def test_syntax_error(self):
        err = self.clf.classify(
            'ERROR: syntax error at or near "SELCT"',
            "postgresql",
        )
        assert err.error_type == QueryErrorType.SYNTAX_ERROR
        assert err.is_retryable

    def test_permission_denied(self):
        err = self.clf.classify(
            "ERROR: permission denied for table users",
            "postgresql",
        )
        assert err.error_type == QueryErrorType.PERMISSION_DENIED
        assert not err.is_retryable

    def test_timeout(self):
        err = self.clf.classify(
            "ERROR: canceling statement due to statement timeout",
            "postgresql",
        )
        assert err.error_type == QueryErrorType.TIMEOUT
        assert err.is_retryable

    def test_ambiguous_column(self):
        err = self.clf.classify(
            'ERROR: column "id" is ambiguous',
            "postgresql",
        )
        assert err.error_type == QueryErrorType.AMBIGUOUS_COLUMN

    def test_type_mismatch(self):
        err = self.clf.classify(
            "ERROR: invalid input syntax for type integer",
            "postgresql",
        )
        assert err.error_type == QueryErrorType.TYPE_MISMATCH

    def test_connection_error(self):
        err = self.clf.classify(
            "connection refused",
            "postgresql",
        )
        assert err.error_type == QueryErrorType.CONNECTION_ERROR
        assert not err.is_retryable


class TestMySQLClassification:
    def setup_method(self):
        self.clf = ErrorClassifier()

    def test_column_not_found(self):
        err = self.clf.classify(
            "Unknown column 'user_name' in 'field list'",
            "mysql",
        )
        assert err.error_type == QueryErrorType.COLUMN_NOT_FOUND

    def test_table_not_found(self):
        err = self.clf.classify(
            "Table 'mydb.userz' doesn't exist",
            "mysql",
        )
        assert err.error_type == QueryErrorType.TABLE_NOT_FOUND

    def test_syntax_error(self):
        err = self.clf.classify(
            "You have an error in your SQL syntax",
            "mysql",
        )
        assert err.error_type == QueryErrorType.SYNTAX_ERROR

    def test_access_denied(self):
        err = self.clf.classify("Access denied for user 'app'", "mysql")
        assert err.error_type == QueryErrorType.PERMISSION_DENIED
        assert not err.is_retryable


class TestClickHouseClassification:
    def setup_method(self):
        self.clf = ErrorClassifier()

    def test_missing_column(self):
        err = self.clf.classify(
            "Missing columns: 'user_name'",
            "clickhouse",
        )
        assert err.error_type == QueryErrorType.COLUMN_NOT_FOUND

    def test_table_not_found(self):
        err = self.clf.classify(
            "Table userz does not exist",
            "clickhouse",
        )
        assert err.error_type == QueryErrorType.TABLE_NOT_FOUND


class TestMongoClassification:
    def setup_method(self):
        self.clf = ErrorClassifier()

    def test_ns_not_found(self):
        err = self.clf.classify("ns not found", "mongodb")
        assert err.error_type == QueryErrorType.TABLE_NOT_FOUND

    def test_unauthorized(self):
        err = self.clf.classify("not authorized on db", "mongodb")
        assert err.error_type == QueryErrorType.PERMISSION_DENIED
        assert not err.is_retryable


class TestFallbackClassification:
    def setup_method(self):
        self.clf = ErrorClassifier()

    def test_unknown_error(self):
        err = self.clf.classify("some random weird error", "postgresql")
        assert err.error_type == QueryErrorType.UNKNOWN
        assert err.is_retryable

    def test_cross_dialect_fallback(self):
        err = self.clf.classify(
            "Unknown column 'bad_col' in 'field list'",
            "postgresql",
        )
        assert err.error_type == QueryErrorType.COLUMN_NOT_FOUND
