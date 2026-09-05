"""SQL text scrubbing: comments and literals, per dialect, in one place.

This scanner was written for `core/safety.py` on 2026-09-02, after
``SELECT '/*' AS a; DROP TABLE users; SELECT '*/' AS b`` was checked as
``SELECT ' ' AS b`` and returned ``is_safe=True`` in read-only mode. It finds
comment fences with one left-to-right scan that also knows the quoting forms, and
it is dialect-aware: ``#`` opens a comment on MySQL and ClickHouse but is an
operator character on PostgreSQL, MySQL's ``--`` needs following whitespace, and
dollar quoting is PostgreSQL-only.

It lives here because three modules were doing this one job and only this
implementation was right. `core/sql_parser.py` had two quoting-blind regexes, and
`core/required_filter_guard.py` had nothing at all — it searched raw SQL, so a
required predicate was satisfied by the same text sitting in a comment or a
string literal.

**Where a dialect is ambiguous the scan keeps text rather than dropping it**, for
the safety guard's reason: leftover text can only cause a refusal, missing text
causes an execution. The one deliberate exception is MySQL's double quote, which
is a string literal by default there and an identifier only under
``ANSI_QUOTES`` — see :func:`strip_sql_comments_and_literals`.
"""

from __future__ import annotations

import re

_SQL_DIALECT_BY_DB_TYPE = {
    "postgres": "postgres",
    "postgresql": "postgres",
    "mysql": "mysql",
    "mariadb": "mysql",
    "clickhouse": "clickhouse",
}

# Quoting forms, per dialect. ``dollar`` is PostgreSQL-only on purpose: MySQL and
# SQLite allow ``$`` inside identifiers and placeholders, so reading ``$x$…$x$``
# as a literal there would hide whatever sits between the two markers.
_QUOTE_BRANCHES = {
    "postgres": [
        r"(?P<sq>'(?:[^']|'')*')",
        r"(?P<dq>\"(?:[^\"]|\"\")*\")",
        r"(?P<dollar>\$(?P<tag>[A-Za-z_][A-Za-z0-9_]*|)\$.*?\$(?P=tag)\$)",
    ],
    "mysql": [
        r"(?P<sq>'(?:[^']|'')*')",
        r"(?P<dq>\"(?:[^\"]|\"\")*\")",
        r"(?P<bq>`(?:[^`]|``)*`)",
    ],
    "clickhouse": [
        r"(?P<sq>'(?:[^']|'')*')",
        r"(?P<dq>\"(?:[^\"]|\"\")*\")",
        r"(?P<bq>`(?:[^`]|``)*`)",
    ],
    "default": [
        r"(?P<sq>'(?:[^']|'')*')",
        r"(?P<dq>\"(?:[^\"]|\"\")*\")",
        r"(?P<bq>`(?:[^`]|``)*`)",
    ],
}

# Line-comment forms, per dialect. A form the engine honours and we do not is an
# evasion (``DROP#\nTABLE`` on MySQL); a form we strip and the engine executes is
# a blind spot (``SELECT 1--2; DROP TABLE t`` on MySQL, where ``--2`` is
# arithmetic, and ``#`` on PostgreSQL, where it is an operator character).
_LINE_COMMENT_FORMS = {
    "postgres": [r"--[^\n]*"],
    "mysql": [r"--(?![^\s\x00-\x1f])[^\n]*", r"\#[^\n]*"],
    "clickhouse": [r"--[^\n]*", r"\#[^\n]*", r"//[^\n]*"],
    "default": [r"--[^\n]*"],
}


def _build_scanner(dialect: str) -> re.Pattern[str]:
    line = "|".join(_LINE_COMMENT_FORMS[dialect])
    branches = [r"(?P<block>/\*.*?\*/)", f"(?P<line>{line})"]
    branches.extend(_QUOTE_BRANCHES[dialect])
    return re.compile("|".join(branches), re.DOTALL)


_SCANNERS = {d: _build_scanner(d) for d in _LINE_COMMENT_FORMS}


def _blank_comment(match: re.Match[str]) -> str:
    """A space for a comment, the original text for anything else."""
    if match.group("block") is not None or match.group("line") is not None:
        return " "
    return match.group(0)


def sql_dialect_for(db_type: str) -> str:
    """Map a connection's ``db_type`` onto a lexing dialect."""
    return _SQL_DIALECT_BY_DB_TYPE.get((db_type or "").lower(), "default")


def strip_sql_comments(query: str, db_type: str = "") -> str:
    """Replace SQL comments with a space so they cannot be used as token
    separators to evade keyword detection (e.g. ``DELETE/**/FROM``), without
    ever reaching inside a string literal or a quoted identifier to do it."""
    return _SCANNERS[sql_dialect_for(db_type)].sub(_blank_comment, query)


#: Dialects where a double-quoted run is a string literal rather than an
#: identifier. PostgreSQL is not one: ``"x"`` is always an identifier there, and
#: blanking it would make a correctly-filtered query look unfiltered.
_DQ_IS_A_LITERAL = {"mysql", "clickhouse", "default"}


def strip_sql_comments_and_literals(query: str, db_type: str = "") -> str:
    """Blank comments **and string literals**, keeping quoted identifiers.

    For callers that ask "does this predicate appear in the query" — where the
    same text inside a comment or a literal is not an answer. Identifiers are
    kept because a column written ``"deleted_at"`` is the predicate, and blanking
    it would turn a correctly-filtered query into a false failure.

    MySQL and ClickHouse are the exception: a double-quoted run there is a string
    by default, so it is blanked. The asymmetry decides it — a false failure
    costs an unsatisfiable repair loop, a false pass is the defect this exists to
    stop.
    """
    dialect = sql_dialect_for(db_type)
    literal_groups = ["sq", "dollar"] + (["dq"] if dialect in _DQ_IS_A_LITERAL else [])

    def _blank(match: re.Match[str]) -> str:
        if match.group("block") is not None or match.group("line") is not None:
            return " "
        for name in literal_groups:
            try:
                if match.group(name) is not None:
                    return " "
            except IndexError:
                continue
        return match.group(0)

    return _SCANNERS[dialect].sub(_blank, query)


def masked_spans(query: str, db_type: str = "") -> list[tuple[int, int]]:
    """Half-open ``(start, end)`` ranges covering comments and string literals.

    For callers asking "does this predicate *occur* in the query", where blanking
    is the wrong tool. Blanking literals looked right and broke four existing
    tests immediately: a required predicate usually CONTAINS one —
    ``status = 'active'`` — so erasing literals made every such requirement
    unsatisfiable, which is the exact defect
    `test_every_shape_is_satisfiable_by_some_query` exists to catch.

    The distinction the guard actually needs is positional: a match that *starts*
    inside a literal or a comment is text, not a predicate; a match that starts
    outside one may have a literal as its operand. So the caller keeps the raw
    query and asks where it may not begin.

    Quoted identifiers are **not** masked: ``"deleted_at"`` is the column, and
    treating it as text would turn a correctly filtered query into a false
    failure. MySQL and ClickHouse are the exception their dialect requires — a
    double-quoted run is a string there by default.
    """
    dialect = sql_dialect_for(db_type)
    literal_groups = ["sq", "dollar"] + (["dq"] if dialect in _DQ_IS_A_LITERAL else [])
    spans: list[tuple[int, int]] = []
    for match in _SCANNERS[dialect].finditer(query):
        if match.group("block") is not None or match.group("line") is not None:
            spans.append(match.span())
            continue
        for name in literal_groups:
            try:
                if match.group(name) is not None:
                    spans.append(match.span())
                    break
            except IndexError:
                continue
    return spans


def starts_inside_masked(offset: int, spans: list[tuple[int, int]]) -> bool:
    """True when *offset* falls within a masked span."""
    return any(start <= offset < end for start, end in spans)
