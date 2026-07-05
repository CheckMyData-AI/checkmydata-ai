"""Enforce code-DB / index required filters before executing SQL.

SYNC-L1 (prod incident #1): the guard is now DATA-DRIVEN and SATISFIABLE.

Data-driven: predicates are parsed from ``required_filters_json`` entries
(``col = val`` / ``col IS NULL`` / ``col IS NOT NULL``).  Unknown / unparseable
conditions fall back to a bare column-presence check (advisory, not hard-block).

Satisfiable / degrade-not-die: on the *final* attempt an unsatisfied filter
DEGRADES to a user-facing warning (``ValidationResult.warning``) and the answer
proceeds.  The guard hard-fails on earlier attempts so the repair loop has a
chance to add the missing predicates.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.core.query_validation import QueryError, QueryErrorType, ValidationResult
from app.core.sql_parser import extract_tables

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Predicate compilation
# ---------------------------------------------------------------------------


def _predicate_to_regex(col: str, predicate: str) -> str:
    """Build a regex fragment for a required predicate string.

    Supports:
    - ``'col = val'``          →  col\\s*=\\s*val\\b
    - ``'col IS NULL'``        →  col\\s+IS\\s+NULL\\b
    - ``'col IS NOT NULL'``    →  col\\s+IS\\s+NOT\\s+NULL\\b

    Anything else falls back to a bare ``\\bcol\\b`` presence check (advisory —
    we still fail on non-final attempts to drive repair, but we can't verify the
    exact predicate shape, so we avoid a false-positive block).
    """
    c = re.escape(col)
    p = predicate.strip().upper()
    if p in ("IS NULL", "= NULL"):
        return rf"{c}\s+IS\s+NULL\b"
    if p in ("IS NOT NULL", "!= NULL", "<> NULL"):
        return rf"{c}\s+IS\s+NOT\s+NULL\b"
    m = re.match(r"^=\s*(.+)$", predicate.strip())
    if m:
        val = re.escape(m.group(1).strip())
        return rf"{c}\s*=\s*{val}\b"
    # Unparseable: bare column presence (advisory, not hard-block)
    return rf"\b{c}\b"


def compile_filter_check(col: str, predicate: str) -> re.Pattern[str]:
    """Compile a required predicate (e.g. ``'was_handled = 1'``, ``'deleted_at IS NULL'``)
    into a regex that must appear in the query when the table is referenced."""
    return re.compile(_predicate_to_regex(col, predicate), re.IGNORECASE)


# ---------------------------------------------------------------------------
# Normalisation: accept both legacy set-form and new dict-form
# ---------------------------------------------------------------------------

# Built-in fallback predicates for the two legacy known columns so that
# callers still using the old ``{table: set[str]}`` form continue to work.
_LEGACY_PREDICATES: dict[str, str] = {
    "was_handled": "= 1",
    "deleted_at": "IS NULL",
}


def _normalize_required(
    required_by_table: dict[str, set[str]] | dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    """Accept either ``{table: {col}}`` (legacy) or ``{table: {col: predicate}}``
    (data-driven).

    Legacy set form falls back to the built-in predicate for the 2 known columns
    and a bare-presence check otherwise, so nothing regresses.
    """
    out: dict[str, dict[str, str]] = {}
    for table, cols in required_by_table.items():
        if isinstance(cols, dict):
            out[table.lower()] = dict(cols)
        else:
            out[table.lower()] = {c: _LEGACY_PREDICATES.get(c, "") for c in cols}
    return out


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


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
    required_by_table: dict[str, set[str]] | dict[str, dict[str, str]],
    *,
    attempt: int = 1,
    max_attempts: int = 3,
) -> ValidationResult:
    """Data-driven, satisfiable guard (SYNC-L1, C-F).

    Fails when a referenced table is missing a configured required filter.
    On the *final* attempt an unsatisfied required filter DEGRADES to a valid
    result carrying a user-facing warning (never a hard-fail), and increments
    ``filter_guard_degrade_total``.
    """
    if db_type.lower() in {"mongodb", "mongo"} or not required_by_table:
        return ValidationResult(is_valid=True)

    normalized = _normalize_required(required_by_table)
    tables = {t.lower() for t in extract_tables(query)}
    if not tables:
        return ValidationResult(is_valid=True)

    missing: list[str] = []
    for table in tables:
        preds = normalized.get(table)
        if not preds:
            continue
        for col, predicate in sorted(preds.items()):
            pattern = compile_filter_check(col, predicate or "")
            if not pattern.search(query):
                missing.append(f"{table}.{col}")

    if not missing:
        return ValidationResult(is_valid=True)

    cols_str = ", ".join(missing)

    # Satisfiability: after the final attempt, degrade to a warning instead of a
    # hard fail so we never block a legitimate query to death (prod incident #1).
    if attempt >= max_attempts:
        try:
            from app.core.metrics import get_metrics_collector

            get_metrics_collector().inc("filter_guard_degrade_total", db_type=db_type.lower())
        except Exception:  # pragma: no cover — metrics must never break the guard
            pass
        return ValidationResult(
            is_valid=True,
            warning=(
                f"Could not apply required filter(s) after {max_attempts} attempts: {cols_str}. "
                "The answer is returned WITHOUT them — treat totals as potentially including "
                "invalid/soft-deleted rows and verify against the business definition."
            ),
        )

    return ValidationResult(
        is_valid=False,
        error=QueryError(
            error_type=QueryErrorType.UNKNOWN,
            message=(
                f"Query is missing required filter(s): {cols_str}. Add them to WHERE and retry."
            ),
            raw_error=f"required_filter_guard: missing {cols_str}",
            is_retryable=True,
            schema_hint=(
                "Required filters (from code-DB sync / schema index). Add every "
                "missing predicate to the WHERE clause before aggregating."
            ),
        ),
    )
