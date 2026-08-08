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


class TestSuppliedErrorType:
    """A connector that knows what went wrong should not have to spell it in prose.

    `asyncio.wait_for` raises a builtin `TimeoutError` carrying no message, so each
    connector hand-writes "Query timed out after Ns". The TIMEOUT regexes below match
    only *vendor* wording, so that self-written string fell through to UNKNOWN with
    is_retryable=True — and the validation loop then paid an LLM to "repair" a query
    that was never broken.
    """

    def setup_method(self):
        self.clf = ErrorClassifier()

    # The exact strings the four connectors produce today.
    CONNECTOR_STRINGS = [
        ("mysql", "Query timed out after 30s"),
        ("postgresql", "Query timed out after 30s"),
        ("clickhouse", "Query timed out after 30s"),
        ("mongodb", "Query timed out after 30s"),
    ]

    def test_supplied_type_wins_over_the_regex_ladder(self):
        for db_type, raw in self.CONNECTOR_STRINGS:
            err = self.clf.classify(raw, db_type, error_type=QueryErrorType.TIMEOUT)
            assert err.error_type == QueryErrorType.TIMEOUT, db_type
            assert err.is_retryable, db_type
            assert err.raw_error == raw, db_type

    def test_without_a_type_the_apps_own_string_is_still_unclassified(self):
        """Deliberate: the fix is to stop *reading* this string, not to regex it.

        Adding a pattern for it would paper over the real defect — a connector that
        forgets to set the type would keep silently working, and the next
        hand-written message would need another pattern.
        """
        for db_type, raw in self.CONNECTOR_STRINGS:
            err = self.clf.classify(raw, db_type)
            assert err.error_type == QueryErrorType.UNKNOWN, db_type

    def test_vendor_worded_timeouts_still_classify_without_a_type(self):
        """Regression: the regex ladder is untouched for errors the vendor words."""
        cases = [
            ("postgresql", "canceling statement due to statement timeout"),
            ("mysql", "Lock wait timeout exceeded; try restarting transaction"),
            ("clickhouse", "Code: 159. TIMEOUT_EXCEEDED"),
            ("mongodb", "operation exceeded time limit"),
        ]
        for db_type, raw in cases:
            err = self.clf.classify(raw, db_type)
            assert err.error_type == QueryErrorType.TIMEOUT, (db_type, raw)

    def test_permission_denied_type_stays_non_retryable(self):
        err = self.clf.classify("nope", "postgresql", error_type=QueryErrorType.PERMISSION_DENIED)
        assert err.error_type == QueryErrorType.PERMISSION_DENIED
        assert not err.is_retryable


class TestTypeReachesTheClassifierFromAQueryResult:
    """Wiring, not vocabulary: the type must survive the trip from connector to loop.

    A timeout does not raise — `execute_query` *returns* a QueryResult whose `error`
    is set, so the classification happens in `post_validator`, and the EXPLAIN dry-run
    has its own copy of the same call. Wiring only one of them leaves the typed path
    half-connected, with tests that still look green.
    """

    def test_post_validator_forwards_the_type(self):
        from app.connectors.base import QueryResult, SchemaInfo
        from app.core.post_validator import PostValidator
        from app.core.query_validation import ValidationConfig

        result = QueryResult(
            error="Query timed out after 30s",
            error_type=QueryErrorType.TIMEOUT,
        )
        verdict = PostValidator().validate(
            result, "SELECT 1", SchemaInfo(db_type="postgresql"), ValidationConfig()
        )

        assert not verdict.is_valid
        assert verdict.error is not None
        assert verdict.error.error_type == QueryErrorType.TIMEOUT

    async def test_explain_validator_forwards_the_type(self):
        """The EXPLAIN dry-run holds its own copy of the same call.

        It is the second of the two places a QueryResult is classified. Wiring only
        `post_validator` would leave a timeout during EXPLAIN misread as a query
        defect — the exact failure this change exists to remove, surviving in the
        one path nobody thought to look at.
        """
        from app.connectors.base import QueryResult
        from app.core.explain_validator import ExplainValidator

        class _Connector:
            async def execute_query(self, _query: str) -> QueryResult:
                return QueryResult(
                    error="Query timed out after 30s",
                    error_type=QueryErrorType.TIMEOUT,
                )

        verdict = await ExplainValidator().validate(_Connector(), "SELECT 1", "postgresql")

        assert not verdict.is_valid
        assert verdict.error is not None
        assert verdict.error.error_type == QueryErrorType.TIMEOUT
