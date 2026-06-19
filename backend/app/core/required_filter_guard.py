"""Enforce code-DB / index required filters before executing SQL."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.core.query_validation import QueryError, QueryErrorType, ValidationResult
from app.core.sql_parser import extract_tables

if TYPE_CHECKING:
    pass

# Column name -> regex that must appear somewhere in the query WHEN the table is used.
_FILTER_CHECKS: dict[str, re.Pattern[str]] = {
    "was_handled": re.compile(r"was_handled\s*=\s*1\b", re.IGNORECASE),
    "deleted_at": re.compile(r"deleted_at\s+IS\s+NULL\b", re.IGNORECASE),
}


def parse_required_columns_from_hint(hint: str) -> set[str]:
    """Extract required filter column names mentioned in db_index query_hints."""
    if not hint:
        return set()
    lower = hint.lower()
    required: set[str] = set()
    if "was_handled" in lower:
        required.add("was_handled")
    if "deleted_at" in lower and "null" in lower:
        required.add("deleted_at")
    return required


def merge_required_filters(
    sync_filters: dict[str, dict[str, str]],
    index_hints: dict[str, str],
) -> dict[str, set[str]]:
    """Merge code_db_sync required_filters_json with db_index query_hints per table."""
    merged: dict[str, set[str]] = {}
    for table, filters in sync_filters.items():
        cols = set(filters.keys())
        cols |= parse_required_columns_from_hint(index_hints.get(table, ""))
        if cols:
            merged[table.lower()] = cols
    for table, hint in index_hints.items():
        cols = parse_required_columns_from_hint(hint)
        if cols:
            merged.setdefault(table.lower(), set()).update(cols)
    return merged


def check_required_filters(
    query: str,
    db_type: str,
    required_by_table: dict[str, set[str]],
) -> ValidationResult:
    """Fail when a referenced table is missing a configured required filter."""
    if db_type.lower() in {"mongodb", "mongo"} or not required_by_table:
        return ValidationResult(is_valid=True)

    tables = {t.lower() for t in extract_tables(query)}
    if not tables:
        return ValidationResult(is_valid=True)

    missing: list[str] = []
    for table in tables:
        required_cols = required_by_table.get(table)
        if not required_cols:
            continue
        for col in sorted(required_cols):
            pattern = _FILTER_CHECKS.get(col)
            if pattern is None:
                continue
            if not pattern.search(query):
                missing.append(f"{table}.{col}")

    if not missing:
        return ValidationResult(is_valid=True)

    cols_str = ", ".join(missing)
    return ValidationResult(
        is_valid=False,
        error=QueryError(
            error_type=QueryErrorType.UNKNOWN,
            message=(
                f"Query is missing required filter(s) for revenue/transaction data: {cols_str}. "
                "These filters are mandatory for this database — add them to WHERE and retry."
            ),
            raw_error=f"required_filter_guard: missing {cols_str}",
            is_retryable=True,
            schema_hint=(
                "Required filters (from code-DB sync / schema index):\n"
                "- purchases: was_handled = 1 AND deleted_at IS NULL for completed transactions\n"
                "Add every missing predicate to the WHERE clause before aggregating revenue."
            ),
        ),
    )
