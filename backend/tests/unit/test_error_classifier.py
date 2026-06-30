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
        # A3: a connection error is transient — ValidationLoop re-runs the same
        # query (with backoff) rather than treating it as terminal.
        assert err.is_retryable


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

    def test_collation_mismatch(self):
        err = self.clf.classify(
            "Illegal mix of collations (utf8mb4_unicode_ci,IMPLICIT) and "
            "(utf8mb4_general_ci,IMPLICIT) for operation 'UNION'",
            "mysql",
        )
        assert err.error_type == QueryErrorType.COLLATION_MISMATCH
        assert err.is_retryable


class TestPostgresCollation:
    def setup_method(self):
        self.clf = ErrorClassifier()

    def test_collation_mismatch(self):
        err = self.clf.classify(
            'ERROR: collation mismatch between "en_US.utf8" and "C"',
            "postgresql",
        )
        assert err.error_type == QueryErrorType.COLLATION_MISMATCH
        assert err.is_retryable


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


class TestGroupByViolationClassification:
    """GROUP BY violations must classify across all three SQL dialects (P1)."""

    def setup_method(self):
        self.clf = ErrorClassifier()

    def test_mysql_only_full_group_by(self):
        raw = (
            '(1055, "Expression #4 of SELECT list is not in GROUP BY clause and contains '
            "nonaggregated column 'esim.p.created_at' which is not functionally dependent on "
            'columns in GROUP BY clause; this is incompatible with sql_mode=only_full_group_by")'
        )
        err = self.clf.classify(raw, "mysql")
        assert err.error_type == QueryErrorType.GROUP_BY_VIOLATION
        assert err.is_retryable

    def test_postgres_42803(self):
        raw = (
            'ERROR: column "p.created_at" must appear in the GROUP BY clause '
            "or be used in an aggregate function"
        )
        err = self.clf.classify(raw, "postgresql")
        assert err.error_type == QueryErrorType.GROUP_BY_VIOLATION
        assert err.is_retryable

    def test_clickhouse_not_an_aggregate(self):
        raw = "Column `created_at` is not under aggregate function and not in GROUP BY keys"
        err = self.clf.classify(raw, "clickhouse")
        assert err.error_type == QueryErrorType.GROUP_BY_VIOLATION

    def test_not_misclassified_as_syntax(self):
        # MySQL also raises generic syntax errors; a GROUP BY violation must win.
        raw = "(1055, '... is not in GROUP BY clause ...; sql_mode=only_full_group_by')"
        err = self.clf.classify(raw, "mysql")
        assert err.error_type != QueryErrorType.SYNTAX_ERROR

    def test_cross_dialect_fallback(self):
        # A PG-worded GROUP BY error arriving under the mysql dialect still classifies.
        raw = 'column "x" must appear in the GROUP BY clause or be used in an aggregate function'
        err = self.clf.classify(raw, "mysql")
        assert err.error_type == QueryErrorType.GROUP_BY_VIOLATION


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
