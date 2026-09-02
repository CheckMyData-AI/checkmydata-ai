"""The comment stripper must know where a string literal begins and ends.

``SafetyGuard`` checks a *stripped* copy of the query while the connector executes
the **original**. Any character the stripper removes that the database would have
executed is a hole in vision.md §7 #1 (read-only by default). Two regexes that do
not know about quoting removed exactly that: a query could open a block comment
inside a string literal, close it inside another, and everything between the two —
including a whole stacked ``DROP TABLE`` — vanished before a single check ran.

Dialect facts pinned here come from the vendors' own lexical references:
PostgreSQL "SQL Syntax / Lexical Structure" (doubled-quote escape, dollar quoting,
``--`` needs no following space), MySQL 8.4 "Comment Syntax" (``#`` to end of line;
``--`` requires a following whitespace/control character), ClickHouse "Syntax"
(``--``, ``#``, ``#!`` and ``//`` line comments).
"""

import pytest

from app.core.safety import SafetyGuard, SafetyLevel, is_read_only_statement

RO = SafetyGuard(SafetyLevel.READ_ONLY)
DML = SafetyGuard(SafetyLevel.ALLOW_DML)


# --------------------------------------------------------------------------
# The reported defect, verbatim.
# --------------------------------------------------------------------------


SMUGGLED = "SELECT '/*' AS a; DROP TABLE users; SELECT '*/' AS b"


def test_a_comment_fence_inside_string_literals_hides_nothing_read_only():
    assert RO.validate(SMUGGLED, "postgres").is_safe is False


def test_a_comment_fence_inside_string_literals_hides_nothing_allow_dml():
    # ALLOW_DML still refuses DDL — the denylist runs before the level check.
    assert DML.validate(SMUGGLED, "postgres").is_safe is False


def test_the_smuggled_statement_is_not_classified_repeatable():
    # ssh_exec re-sends a command it believes is read-only after a lost
    # connection (F-SSH-07). A mutating statement must never earn that verdict.
    assert is_read_only_statement(SMUGGLED, "postgres") is False


@pytest.mark.parametrize(
    "query",
    [
        # single-quoted literals, both fences
        "SELECT '/*' AS a; DROP TABLE users; SELECT '*/' AS b",
        "SELECT '--' AS a; DROP TABLE users",
        # a doubled quote inside the literal must not end it early
        "SELECT 'it''s /*' AS a; TRUNCATE users; SELECT '*/' AS b",
        # delimited identifier (PostgreSQL) carrying a fence
        'SELECT 1 AS "/*"; DROP TABLE users; SELECT 2 AS "*/"',
        # dollar-quoted string (PostgreSQL)
        "SELECT $$/*$$ AS a; DROP TABLE users; SELECT $$*/$$ AS b",
        "SELECT $tag$/*$tag$ AS a; DROP TABLE users; SELECT $tag$*/$tag$ AS b",
    ],
)
def test_no_quoting_form_can_swallow_a_statement(query):
    assert RO.validate(query, "postgres").is_safe is False


@pytest.mark.parametrize("db_type", ["mysql", "clickhouse"])
def test_backtick_identifiers_cannot_swallow_a_statement(db_type):
    # A backtick is an identifier quote for MySQL and ClickHouse, so ``/*`` inside
    # one is text rather than a comment opener. (On PostgreSQL a backtick is not a
    # quote at all and ``/*`` there really does open a comment — matching the
    # engine is the point, not stripping less everywhere.)
    query = "SELECT 1 AS `/*`; DROP TABLE users; SELECT 2 AS `*/`"
    assert RO.validate(query, db_type).is_safe is False


# --------------------------------------------------------------------------
# What the stripper still has to do: real comments must not split keywords.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        "DELETE/**/FROM users",
        "DROP/**/TABLE users",
        "SELECT 1 -- harmless\n; DROP TABLE users",
        "/* lead-in */ DROP TABLE users",
    ],
)
def test_real_comments_are_still_stripped(query):
    assert RO.validate(query, "postgres").is_safe is False


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM users WHERE note = 'a -- b'",
        "SELECT * FROM users WHERE note = 'a /* b */ c'",
        "SELECT 'unterminated fence /*' AS a FROM t",
        "SELECT $$body with /* fence $$ AS a FROM t",
    ],
)
def test_legitimate_queries_carrying_fences_are_allowed(query):
    assert RO.validate(query, "postgres").is_safe is True


def test_dollar_quoted_do_block_is_still_blocked():
    # The DO pattern keys on the statement-initial keyword, not on the body.
    assert RO.validate("DO $$ BEGIN PERFORM 1; END $$", "postgres").is_safe is False


# --------------------------------------------------------------------------
# Dialects. A comment form the engine honours and the guard does not is an
# evasion; a form the guard strips and the engine executes is a blind spot.
# --------------------------------------------------------------------------


def test_mysql_hash_comment_cannot_split_a_keyword():
    assert RO.validate("DROP#\nTABLE users", "mysql").is_safe is False
    assert DML.validate("DROP#\nTABLE users", "mysql").is_safe is False


def test_mysql_double_dash_needs_whitespace_so_nothing_hides_behind_it():
    # MySQL reads ``--2`` as arithmetic, not a comment: the DROP after it runs.
    assert RO.validate("SELECT 1--2; DROP TABLE users", "mysql").is_safe is False


def test_postgres_double_dash_needs_no_whitespace():
    # PostgreSQL ends the line at ``--`` regardless of what follows.
    assert RO.validate("SELECT 1--2\nFROM t", "postgres").is_safe is True


@pytest.mark.parametrize("fence", ["#", "#!", "//"])
def test_clickhouse_line_comments_cannot_split_a_keyword(fence):
    assert RO.validate(f"DROP{fence}\nTABLE users", "clickhouse").is_safe is False


def test_hash_is_not_a_comment_on_postgres():
    # ``#`` is an operator character in PostgreSQL, so stripping to end of line
    # would hide the stacked statement that follows on the same line.
    assert RO.validate("SELECT 1 # 2; DROP TABLE users", "postgres").is_safe is False
