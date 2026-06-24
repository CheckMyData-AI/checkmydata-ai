"""C5 — SafetyGuard statement-initial allow-list (read-only mode).

A read-only query must, after comment stripping:
  * be single-statement (no ``;`` followed by further non-whitespace), and
  * start with an allowed read keyword
    (SELECT/WITH/SHOW/EXPLAIN/DESCRIBE/DESC/TABLE/VALUES/EXISTS).

This closes the regex-evasion class (F-SQL-08 / F-CONN-02): statements like
``CREATE OR REPLACE VIEW v AS SELECT 1`` or ``ALTER ROLE x`` slip past the
denylist today because no ``DROP``/``CREATE TABLE`` token appears, yet they
mutate the database. The allow-list applies ONLY at ``READ_ONLY``;
``ALLOW_DML`` / ``UNRESTRICTED`` are unchanged.
"""

import pytest

from app.core.safety import SafetyGuard, SafetyLevel

RO = SafetyGuard(SafetyLevel.READ_ONLY)
DML = SafetyGuard(SafetyLevel.ALLOW_DML)


class TestReadOnlyAllowList:
    """Read tokens pass, non-read leading tokens / multi-statements fail."""

    @pytest.mark.parametrize(
        "q",
        [
            "SELECT 1",
            "select 1",  # case-insensitive leading token
            "WITH x AS (SELECT 1) SELECT * FROM x",
            "EXPLAIN SELECT 1",
            "EXPLAIN ANALYZE SELECT * FROM users",
            "SHOW TABLES",
            "DESCRIBE users",
            "DESC users",
            "VALUES (1), (2)",
            "  \n  SELECT 1  ",  # leading/trailing whitespace + blank lines
            "SELECT 1;",  # trailing semicolon is still single-statement
            "(SELECT 1)",  # parenthesised leading SELECT
        ],
    )
    def test_read_only_statements_allowed(self, q):
        result = RO.validate_sql(q)
        assert result.is_safe, f"expected safe: {q!r} -> {result.reason}"

    @pytest.mark.parametrize(
        "q",
        [
            "CREATE OR REPLACE VIEW v AS SELECT 1",  # regex misses this today
            "ALTER ROLE x SUPERUSER",  # not a DANGEROUS_PATTERNS hit (ROLE != TABLE/DB/SCHEMA)
            "SET search_path TO public",  # not a read leading token
            "REFRESH MATERIALIZED VIEW mv",
            "VACUUM users",
            "ANALYZE users",
            "COMMENT ON TABLE users IS 'x'",
        ],
    )
    def test_non_read_leading_token_blocked(self, q):
        result = RO.validate_sql(q)
        assert not result.is_safe, f"expected unsafe: {q!r}"
        assert "read-only" in result.reason.lower()

    @pytest.mark.parametrize(
        "q",
        [
            "SELECT 1; DROP TABLE t",  # also caught by denylist, but multi-statement first
            "SELECT 1; SELECT 2",  # both read, still rejected: stacked statements
            "SELECT 1;SELECT 2",  # no whitespace after semicolon
            "SELECT 1 ;\n SELECT 2",
        ],
    )
    def test_multi_statement_blocked(self, q):
        result = RO.validate_sql(q)
        assert not result.is_safe, f"expected unsafe: {q!r}"

    def test_multi_statement_reason_mentions_multiple(self):
        result = RO.validate_sql("SELECT 1; SELECT 2")
        assert "multiple statements" in result.reason.lower()

    def test_empty_query_blocked(self):
        result = RO.validate_sql("   ")
        assert not result.is_safe

    def test_comment_only_query_blocked(self):
        result = RO.validate_sql("-- just a comment")
        assert not result.is_safe


class TestAllowDmlUnaffectedByAllowList:
    """The allow-list is read-only-only: ALLOW_DML keeps allowing DML."""

    def test_insert_still_allowed(self):
        assert DML.validate_sql("INSERT INTO t VALUES (1)").is_safe

    def test_update_still_allowed(self):
        assert DML.validate_sql("UPDATE t SET a = 1 WHERE id = 2").is_safe

    def test_non_read_leading_token_allowed_under_dml(self):
        # CREATE OR REPLACE VIEW is not in the dangerous denylist and the
        # allow-list does not apply at ALLOW_DML, so it passes here.
        assert DML.validate_sql("CREATE OR REPLACE VIEW v AS SELECT 1").is_safe

    def test_drop_still_blocked_under_dml(self):
        # Denylist still runs first at every level.
        assert not DML.validate_sql("DROP TABLE t").is_safe
