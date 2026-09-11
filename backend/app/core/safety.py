import json
import logging
import re
from dataclasses import dataclass
from enum import StrEnum

from app.core.sql_text import (
    sql_dialect_for,
    strip_sql_comments,
    strip_sql_comments_and_literals,
)

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

# A line whose first non-whitespace character is a backslash. `psql` reads client
# meta-commands from stdin in non-interactive mode exactly as it does interactively —
# `\!` runs a shell command, `\copy … TO PROGRAM` runs one, `\i`/`\o` read and write files —
# and the SSH-exec connector pipes the query to psql's stdin. So the text this guard checks
# and the text that executes are the same string while the EXECUTOR is the client, not the
# engine every other rule here was written against (SQL-01).
#
# Checked against the query with comments **and string literals** blanked, so a Windows path
# in a WHERE clause is not a false refusal. Blocked at every level below UNRESTRICTED,
# because shell execution on the bastion is not a SQL permission question.
#
# **Any** backslash, not only one at the start of a line.** The first draft anchored on
# `^[ \t]*\\` and let `SELECT 1 \copy users TO PROGRAM \'id\'` through — psql takes a
# meta-command after SQL on the same line, which is exactly how the familiar `\g` terminator
# works. Outside a literal, a backslash has no meaning in any dialect this product speaks, so
# refusing all of them costs a quoted identifier containing one and nothing else.
_META_COMMAND_LINE = re.compile(r"\\")

# Functions and table functions that read the server's filesystem or make a network request.
# Every one of them is a SELECT, so the leading-token allow-list passes it and the DML
# denylist never looks (SQL-11). A DB-enforced read-only session does not block a read
# either, so on this class the guard is the only layer that exists.
#
# Scoped by dialect, and an unknown dialect gets all of them: a false refusal is recoverable,
# and this list only ever grows by finding another one the hard way. The trailing `\s*\(`
# is what keeps `SELECT file, url FROM downloads` — ordinary column names — working.
_SERVER_ACCESS_FUNCS: dict[str, tuple[str, ...]] = {
    "postgres": (
        "pg_read_file",
        "pg_read_binary_file",
        "pg_ls_dir",
        "pg_stat_file",
        "pg_ls_logdir",
        "pg_ls_waldir",
        "lo_import",
        "lo_export",
        "dblink",
        "dblink_connect",
    ),
    "mysql": ("load_file",),
    "clickhouse": (
        "file",
        "url",
        "s3",
        "hdfs",
        "remote",
        "remotesecure",
        "jdbc",
        "odbc",
        "mysql",
        "postgresql",
        "mongodb",
        "sqlite",
        "azureblobstorage",
    ),
}


def _server_access_pattern(dialect: str) -> re.Pattern[str]:
    """The file/network function denylist for *dialect*; every list when it is unknown."""
    if dialect in _SERVER_ACCESS_FUNCS:
        names = _SERVER_ACCESS_FUNCS[dialect]
    else:
        names = tuple(n for group in _SERVER_ACCESS_FUNCS.values() for n in group)
    return re.compile(r"\b(" + "|".join(sorted(set(names))) + r")\s*\(", re.IGNORECASE)


# A data-modifying statement in a position the table-name regexes below cannot reach: the
# body of a CTE. `WITH t AS (UPDATE "my table" SET x=1 RETURNING id) SELECT * FROM t` passed
# the read-only guard because `DML_PATTERNS_SQL`'s UPDATE pattern spans the table name and a
# space inside a quoted identifier breaks it (SQL-12). Anchoring on the keyword's POSITION —
# the start of the text, or just after `(` or `;` — needs to know nothing about table names.
#
# `(?!\s*\()` excludes the function forms: MySQL's `REPLACE(str, a, b)` and `INSERT(str, …)`
# are perfectly ordinary inside a SELECT, and both would otherwise sit right after a `(`.
_DML_IN_ANY_POSITION = re.compile(
    r"(?:^|[(;])\s*(UPDATE|DELETE|INSERT|MERGE|UPSERT|REPLACE)\b(?!\s*\()",
    re.IGNORECASE,
)

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

# The dialect-aware comment/literal scanner moved to `core/sql_text.py` on
# 2026-09-05: `core/sql_parser.py` and `core/required_filter_guard.py` needed the
# same lexing, and only this implementation was right. Behaviour here is
# unchanged — the aliases below keep this module's own vocabulary.
_strip_sql_comments = strip_sql_comments


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
        # Literals blanked as well: the three checks added for SQL-01/11/12 look for a
        # character or a call, both of which appear inside ordinary string data.
        scrubbed = strip_sql_comments_and_literals(query, db_type)

        if _META_COMMAND_LINE.search(scrubbed):
            logger.warning("Blocked client meta-command line in SQL")
            return SafetyResult(
                is_safe=False,
                reason=(
                    "Client meta-command (a line starting with '\\') is not allowed: "
                    "the database client executes these itself, outside SQL"
                ),
                query=query,
            )

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

            access = _server_access_pattern(sql_dialect_for(db_type)).search(scrubbed)
            if access:
                logger.warning("Blocked server-side file/network function: %s", access.group(1))
                return SafetyResult(
                    is_safe=False,
                    reason=(
                        f"{access.group(1)}() reads the server's filesystem or the network, "
                        "which is not allowed in read-only mode"
                    ),
                    query=query,
                )

            # Positionally anchored, so a quoted table name with a space cannot hide it.
            cte_dml = _DML_IN_ANY_POSITION.search(scrubbed)
            if cte_dml:
                logger.warning("Blocked DML in read-only mode: %s", cte_dml.group(1))
                return SafetyResult(
                    is_safe=False,
                    reason=f"DML not allowed in read-only mode: {cte_dml.group(1)}",
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
