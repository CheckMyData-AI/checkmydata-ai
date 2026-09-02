import json
import logging
import re
from dataclasses import dataclass
from enum import StrEnum

logger = logging.getLogger(__name__)


class SafetyLevel(StrEnum):
    READ_ONLY = "read_only"
    ALLOW_DML = "allow_dml"
    UNRESTRICTED = "unrestricted"


DANGEROUS_PATTERNS_SQL = [
    re.compile(r"\b(DROP)\s+(TABLE|DATABASE|SCHEMA|INDEX|VIEW)\b", re.IGNORECASE),
    re.compile(r"\b(TRUNCATE)\s+", re.IGNORECASE),
    re.compile(r"\b(ALTER)\s+(TABLE|DATABASE|SCHEMA)\b", re.IGNORECASE),
    re.compile(r"\b(GRANT|REVOKE)\s+", re.IGNORECASE),
    re.compile(r"\b(CREATE)\s+(TABLE|DATABASE|SCHEMA|INDEX|VIEW|USER|ROLE)\b", re.IGNORECASE),
    # Server-side filesystem / command execution — blocked even when DML is allowed.
    # COPY/DO are statement-initial keywords so an identifier named "copy" is safe.
    re.compile(r"(^|;)\s*COPY\b", re.IGNORECASE | re.MULTILINE),
    re.compile(r"\bINTO\s+(OUTFILE|DUMPFILE)\b", re.IGNORECASE),
    re.compile(r"\bLOAD\s+DATA\b", re.IGNORECASE),
    re.compile(r"(^|;)\s*DO\s+(\$|LANGUAGE\b|')", re.IGNORECASE | re.MULTILINE),
]

DML_PATTERNS_SQL = [
    re.compile(r"\b(INSERT)\s+INTO\b", re.IGNORECASE),
    re.compile(r"\b(UPDATE)\s+[\w.\"'`]+(\s*\.\s*[\w\"'`]+)*\s+SET\b", re.IGNORECASE),
    re.compile(r"\b(DELETE)\s+FROM\b", re.IGNORECASE),
    re.compile(r"\b(MERGE)\s+INTO\b", re.IGNORECASE),
    re.compile(r"\b(UPSERT)\s+INTO\b", re.IGNORECASE),
    re.compile(r"\b(REPLACE)\s+INTO\b", re.IGNORECASE),
    re.compile(r"(^|;)\s*CALL\b", re.IGNORECASE | re.MULTILINE),
]

# Statement-initial allow-list (read-only mode only). A read-only query must
# *start* with one of these tokens; anything else (CREATE OR REPLACE VIEW,
# ALTER ROLE, SET, VACUUM, REFRESH, COMMENT ON, …) is rejected even though it
# never trips the denylist above. This closes the regex-evasion class
# (F-SQL-08 / F-CONN-02). Defense-in-depth: the denylists still run first.
_READ_ONLY_LEADING = frozenset(
    {"SELECT", "WITH", "SHOW", "EXPLAIN", "DESCRIBE", "DESC", "TABLE", "VALUES", "EXISTS"}
)

# Splits off the first token: leading whitespace and an opening paren are both
# valid statement starts (e.g. ``(SELECT 1)``), so they delimit the token too.
_LEADING_TOKEN = re.compile(r"^[\s(]*([A-Za-z]+)")

# --------------------------------------------------------------------------
# Comment stripping, and why it has to lex rather than match
# --------------------------------------------------------------------------
#
# Every check below runs against a copy of the query with comments removed,
# while the connector executes the ORIGINAL. Stripping is therefore only safe in
# one direction: removing something the database ignores (a comment) is fine;
# removing something it would have executed is a hole in vision.md §7 #1.
#
# Two bare regexes could not tell the difference. ``/\*.*?\*/`` matched from a
# ``/*`` inside a string literal to a ``*/`` inside another one, so
# ``SELECT '/*' AS a; DROP TABLE users; SELECT '*/' AS b`` was checked as
# ``SELECT ' ' AS b`` and passed in READ_ONLY. So the comment fences are found by
# a single left-to-right scan that also knows the quoting forms — only the comment
# branches are replaced, every literal is handed back untouched.
#
# Where a dialect is ambiguous the scan errs toward keeping text, because leftover
# text can only cause a refusal while missing text causes an execution.
# Consequences of that rule, all deliberate:
#   * block comments are NOT treated as nesting, though PostgreSQL and ClickHouse
#     nest them: ``/* /* */ DROP TABLE t */`` is one comment to those engines and
#     a visible DROP to us — a false refusal, never a false pass;
#   * backslash escapes inside string literals are NOT honoured, so MySQL's
#     ``'a\''`` ends the literal early and the rest of the statement stays visible;
#   * an unterminated literal matches nothing and is scanned as ordinary text.
#
# Dialect facts are the vendors': PostgreSQL "Lexical Structure" (doubled-quote
# escape, dollar quoting, ``--`` needs no following space), MySQL 8.4 "Comment
# Syntax" (``#`` to end of line; ``--`` requires a following whitespace or control
# character), ClickHouse "Syntax" (``--``, ``#``, ``#!``, ``//``).

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


def _strip_sql_comments(query: str, db_type: str = "") -> str:
    """Replace SQL comments with a space so they cannot be used as token
    separators to evade keyword detection (e.g. ``DELETE/**/FROM``), without
    ever reaching inside a string literal or a quoted identifier to do it."""
    return _SCANNERS[sql_dialect_for(db_type)].sub(_blank_comment, query)


@dataclass
class SafetyResult:
    is_safe: bool
    reason: str = ""
    query: str = ""


class SafetyGuard:
    """Validates queries against a configurable safety level."""

    def __init__(self, level: SafetyLevel = SafetyLevel.READ_ONLY):
        self.level = level

    def validate_sql(self, query: str, db_type: str = "") -> SafetyResult:
        stripped = _strip_sql_comments(query, db_type).strip().rstrip(";")

        for pattern in DANGEROUS_PATTERNS_SQL:
            match = pattern.search(stripped)
            if match:
                logger.warning("Blocked dangerous SQL operation: %s", match.group(0))
                return SafetyResult(
                    is_safe=False,
                    reason=f"Blocked dangerous operation: {match.group(0)}",
                    query=query,
                )

        if self.level == SafetyLevel.READ_ONLY:
            # Single-statement: a ``;`` followed by further non-whitespace means
            # a stacked statement (``SELECT 1; DROP TABLE t``) — reject it. A bare
            # trailing ``;`` was already removed by ``.rstrip(";")`` above.
            if ";" in stripped:
                logger.warning("Blocked multi-statement query in read-only mode")
                return SafetyResult(
                    is_safe=False,
                    reason="Multiple statements not allowed in read-only mode",
                    query=query,
                )

            # Positive allow-list: the first token must be a read keyword.
            leading_match = _LEADING_TOKEN.match(stripped)
            leading = leading_match.group(1).upper() if leading_match else ""
            if leading not in _READ_ONLY_LEADING:
                logger.warning("Blocked non-read statement in read-only mode: %s", leading or "?")
                return SafetyResult(
                    is_safe=False,
                    reason=(
                        "Only read-only statements (SELECT/WITH/SHOW/EXPLAIN/…) "
                        "are allowed in read-only mode"
                    ),
                    query=query,
                )

            for pattern in DML_PATTERNS_SQL:
                match = pattern.search(stripped)
                if match:
                    logger.warning("Blocked DML in read-only mode: %s", match.group(0))
                    return SafetyResult(
                        is_safe=False,
                        reason=f"DML not allowed in read-only mode: {match.group(0)}",
                        query=query,
                    )

        return SafetyResult(is_safe=True, query=query)

    def validate_mongo(self, query: str) -> SafetyResult:
        """For MongoDB JSON queries, block write operations.

        B4 (audit): mirrors the connector-level guard
        (``_assert_mongo_read_safe`` in ``app.connectors.mongodb``) so paths
        validated only through SafetyGuard get the same protection —
        aggregation write stages (``$out`` / ``$merge``) and server-side JS
        operators (``$where`` / ``$function`` / ``$accumulator``) are rejected
        here too, not just top-level write operations.
        """
        try:
            spec = json.loads(query)
        except json.JSONDecodeError:
            return SafetyResult(is_safe=False, reason="Invalid JSON query", query=query)

        operation = spec.get("operation", "find")
        write_ops = {
            "insert",
            "update",
            "delete",
            "drop",
            "rename",
            "create_index",
            "drop_index",
            "replace",
        }

        if self.level == SafetyLevel.READ_ONLY:
            if operation in write_ops:
                logger.warning("Blocked MongoDB write operation in read-only mode: %s", operation)
                return SafetyResult(
                    is_safe=False,
                    reason=f"Write operation '{operation}' not allowed in read-only mode",
                    query=query,
                )

            # Serialize the whole spec so JS operators are caught no matter how
            # deeply they are nested (e.g. inside ``$and`` / ``$expr``).
            blob = json.dumps(spec, default=str)
            for js in ("$where", "$function", "$accumulator"):
                if js in blob:
                    logger.warning("Blocked MongoDB server-side JS operator: %s", js)
                    return SafetyResult(
                        is_safe=False,
                        reason=(f"Server-side JS operator '{js}' not allowed in read-only mode"),
                        query=query,
                    )

            if operation == "aggregate":
                for stage in spec.get("pipeline", []):
                    if isinstance(stage, dict):
                        for write_stage in ("$out", "$merge"):
                            if write_stage in stage:
                                logger.warning(
                                    "Blocked MongoDB aggregation write stage: %s", write_stage
                                )
                                return SafetyResult(
                                    is_safe=False,
                                    reason=(
                                        f"Aggregation write stage '{write_stage}' "
                                        "not allowed in read-only mode"
                                    ),
                                    query=query,
                                )

        return SafetyResult(is_safe=True, query=query)

    def validate(self, query: str, db_type: str) -> SafetyResult:
        if self.level == SafetyLevel.UNRESTRICTED:
            return SafetyResult(is_safe=True, query=query)

        if db_type in {"mongodb", "mongo"}:
            return self.validate_mongo(query)
        return self.validate_sql(query, db_type)


def is_read_only_statement(query: str, db_type: str) -> bool:
    """True when *query* is a single statement that cannot change data.

    Delegates to the read-only :class:`SafetyGuard` rather than re-deriving the
    answer: comment stripping, the multi-statement refusal and the leading-keyword
    allow-list are all already there, and a second definition of "read-only" is the
    kind that drifts from the first.

    Used by the SSH-exec connector to decide whether a command interrupted by a lost
    connection may be re-sent (F-SSH-07). A read-only statement is safe to repeat; a
    mutating one is not, and the connector cannot know whether the first attempt
    reached the server.
    """
    return SafetyGuard(SafetyLevel.READ_ONLY).validate(query, db_type).is_safe
