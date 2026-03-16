"""Dialect-aware classification of database error messages."""

from __future__ import annotations

import logging
import re
from typing import NamedTuple

from app.core.query_validation import (
    NON_RETRYABLE_ERRORS,
    QueryError,
    QueryErrorType,
)

logger = logging.getLogger(__name__)


class _Pattern(NamedTuple):
    regex: re.Pattern[str]
    error_type: QueryErrorType
    entity_group: int | None  # capture group index for the problematic entity


POSTGRES_PATTERNS: list[_Pattern] = [
    _Pattern(
        re.compile(r'column "(\w+)" does not exist', re.I),
        QueryErrorType.COLUMN_NOT_FOUND, 1,
    ),
    _Pattern(
        re.compile(r'relation "(\w+)" does not exist', re.I),
        QueryErrorType.TABLE_NOT_FOUND, 1,
    ),
    _Pattern(
        re.compile(r"syntax error at or near", re.I),
        QueryErrorType.SYNTAX_ERROR, None,
    ),
    _Pattern(
        re.compile(r'column "(\w+)" is ambiguous', re.I),
        QueryErrorType.AMBIGUOUS_COLUMN, 1,
    ),
    _Pattern(
        re.compile(
            r"invalid input syntax for type (\w+)",
            re.I,
        ),
        QueryErrorType.TYPE_MISMATCH, 1,
    ),
    _Pattern(
        re.compile(r"permission denied", re.I),
        QueryErrorType.PERMISSION_DENIED, None,
    ),
    _Pattern(
        re.compile(r"canceling statement due to statement timeout", re.I),
        QueryErrorType.TIMEOUT, None,
    ),
    _Pattern(
        re.compile(r"could not connect|connection refused|connection reset", re.I),
        QueryErrorType.CONNECTION_ERROR, None,
    ),
]

MYSQL_PATTERNS: list[_Pattern] = [
    _Pattern(
        re.compile(r"Unknown column '([^']+)'", re.I),
        QueryErrorType.COLUMN_NOT_FOUND, 1,
    ),
    _Pattern(
        re.compile(r"Table '(?:[\w.]*\.)?(\w+)' doesn't exist", re.I),
        QueryErrorType.TABLE_NOT_FOUND, 1,
    ),
    _Pattern(
        re.compile(r"You have an error in your SQL syntax", re.I),
        QueryErrorType.SYNTAX_ERROR, None,
    ),
    _Pattern(
        re.compile(r"Column '(\w+)' in .+ is ambiguous", re.I),
        QueryErrorType.AMBIGUOUS_COLUMN, 1,
    ),
    _Pattern(
        re.compile(r"Incorrect \w+ value:", re.I),
        QueryErrorType.TYPE_MISMATCH, None,
    ),
    _Pattern(
        re.compile(r"Access denied|command denied", re.I),
        QueryErrorType.PERMISSION_DENIED, None,
    ),
    _Pattern(
        re.compile(r"Lock wait timeout|Query execution was interrupted", re.I),
        QueryErrorType.TIMEOUT, None,
    ),
    _Pattern(
        re.compile(r"Can't connect|Lost connection", re.I),
        QueryErrorType.CONNECTION_ERROR, None,
    ),
]

CLICKHOUSE_PATTERNS: list[_Pattern] = [
    _Pattern(
        re.compile(r"Missing columns?: '(\w+)'", re.I),
        QueryErrorType.COLUMN_NOT_FOUND, 1,
    ),
    _Pattern(
        re.compile(r"Unknown table expression identifier '(\w+)'", re.I),
        QueryErrorType.TABLE_NOT_FOUND, 1,
    ),
    _Pattern(
        re.compile(r"Table (\w+) does not exist", re.I),
        QueryErrorType.TABLE_NOT_FOUND, 1,
    ),
    _Pattern(
        re.compile(r"Syntax error", re.I),
        QueryErrorType.SYNTAX_ERROR, None,
    ),
    _Pattern(
        re.compile(r"Illegal type", re.I),
        QueryErrorType.TYPE_MISMATCH, None,
    ),
    _Pattern(
        re.compile(r"ACCESS_DENIED|Not enough privileges", re.I),
        QueryErrorType.PERMISSION_DENIED, None,
    ),
    _Pattern(
        re.compile(r"TIMEOUT_EXCEEDED|Timeout exceeded", re.I),
        QueryErrorType.TIMEOUT, None,
    ),
    _Pattern(
        re.compile(r"Connection refused|Network is unreachable", re.I),
        QueryErrorType.CONNECTION_ERROR, None,
    ),
]

MONGO_PATTERNS: list[_Pattern] = [
    _Pattern(
        re.compile(r"ns not found|Collection (\w+) not found", re.I),
        QueryErrorType.TABLE_NOT_FOUND, 1,
    ),
    _Pattern(
        re.compile(r"unknown top level operator", re.I),
        QueryErrorType.SYNTAX_ERROR, None,
    ),
    _Pattern(
        re.compile(r"not authorized|Unauthorized", re.I),
        QueryErrorType.PERMISSION_DENIED, None,
    ),
    _Pattern(
        re.compile(r"operation exceeded time limit", re.I),
        QueryErrorType.TIMEOUT, None,
    ),
    _Pattern(
        re.compile(r"connection refused|couldn't connect", re.I),
        QueryErrorType.CONNECTION_ERROR, None,
    ),
]

DIALECT_MAP: dict[str, list[_Pattern]] = {
    "postgresql": POSTGRES_PATTERNS,
    "postgres": POSTGRES_PATTERNS,
    "mysql": MYSQL_PATTERNS,
    "clickhouse": CLICKHOUSE_PATTERNS,
    "mongodb": MONGO_PATTERNS,
    "mongo": MONGO_PATTERNS,
}


class ErrorClassifier:
    """Classifies raw DB error strings into structured ``QueryError``."""

    def classify(
        self,
        raw_error: str,
        db_type: str,
    ) -> QueryError:
        patterns = DIALECT_MAP.get(db_type.lower(), [])

        for pat in patterns:
            match = pat.regex.search(raw_error)
            if match:
                entity = (
                    match.group(pat.entity_group)
                    if pat.entity_group and pat.entity_group <= len(match.groups())
                    else None
                )
                is_table = pat.error_type == QueryErrorType.TABLE_NOT_FOUND
                is_col = pat.error_type == QueryErrorType.COLUMN_NOT_FOUND
                return QueryError(
                    error_type=pat.error_type,
                    message=self._build_message(pat.error_type, entity),
                    raw_error=raw_error,
                    is_retryable=pat.error_type not in NON_RETRYABLE_ERRORS,
                    suggested_tables=(
                        [entity] if entity and is_table else []
                    ),
                    suggested_columns=(
                        [entity] if entity and is_col else []
                    ),
                )

        # Fallback: try all dialects if specific dialect didn't match
        if patterns:
            for dialect, other_patterns in DIALECT_MAP.items():
                if other_patterns is patterns:
                    continue
                for pat in other_patterns:
                    match = pat.regex.search(raw_error)
                    if match:
                        entity = (
                            match.group(pat.entity_group)
                            if pat.entity_group and pat.entity_group <= len(match.groups())
                            else None
                        )
                        return QueryError(
                            error_type=pat.error_type,
                            message=self._build_message(pat.error_type, entity),
                            raw_error=raw_error,
                            is_retryable=pat.error_type not in NON_RETRYABLE_ERRORS,
                        )

        logger.warning("Unclassified DB error (%s): %s", db_type, raw_error[:200])
        return QueryError(
            error_type=QueryErrorType.UNKNOWN,
            message=f"Unclassified error: {raw_error[:200]}",
            raw_error=raw_error,
            is_retryable=True,
        )

    @staticmethod
    def _build_message(error_type: QueryErrorType, entity: str | None) -> str:
        prefix = error_type.value.replace("_", " ").title()
        if entity:
            return f"{prefix}: '{entity}'"
        return prefix
