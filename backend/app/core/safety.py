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

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"--[^\n]*")


def _strip_sql_comments(query: str) -> str:
    """Replace SQL comments with a space so they cannot be used as token
    separators to evade keyword detection (e.g. ``DELETE/**/FROM``)."""
    return _LINE_COMMENT.sub(" ", _BLOCK_COMMENT.sub(" ", query))


@dataclass
class SafetyResult:
    is_safe: bool
    reason: str = ""
    query: str = ""


class SafetyGuard:
    """Validates queries against a configurable safety level."""

    def __init__(self, level: SafetyLevel = SafetyLevel.READ_ONLY):
        self.level = level

    def validate_sql(self, query: str) -> SafetyResult:
        stripped = _strip_sql_comments(query).strip().rstrip(";")

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
        """For MongoDB JSON queries, block write operations."""
        try:
            spec = json.loads(query)
        except json.JSONDecodeError:
            return SafetyResult(is_safe=False, reason="Invalid JSON query", query=query)

        operation = spec.get("operation", "find")
        write_ops = {"insert", "update", "delete", "drop", "rename", "create_index", "drop_index"}

        if self.level == SafetyLevel.READ_ONLY and operation in write_ops:
            logger.warning("Blocked MongoDB write operation in read-only mode: %s", operation)
            return SafetyResult(
                is_safe=False,
                reason=f"Write operation '{operation}' not allowed in read-only mode",
                query=query,
            )

        return SafetyResult(is_safe=True, query=query)

    def validate(self, query: str, db_type: str) -> SafetyResult:
        if self.level == SafetyLevel.UNRESTRICTED:
            return SafetyResult(is_safe=True, query=query)

        if db_type in {"mongodb", "mongo"}:
            return self.validate_mongo(query)
        return self.validate_sql(query)
