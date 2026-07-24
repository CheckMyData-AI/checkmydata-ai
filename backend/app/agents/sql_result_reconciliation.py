"""Detect when multiple SQL results reconcile and guard against false self-correction."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.agents.sql_agent import SQLAgentResult

_NUMERIC_HINTS = (
    "revenue",
    "amount",
    "total",
    "gross",
    "net",
    "usd",
    "sum",
    "value",
    "refund",
)

_FALSE_CORRECTION_MARKERS = (
    "first gross query",
    "first query missed",
    "lower totals",
    "reported lower",
    "didn't capture",
    "did not capture",
    "patterns didn't",
    "patterns did not",
    "missed some product",
)


@dataclass(frozen=True)
class SqlTotalsSnapshot:
    query_index: int
    row_count: int
    grand_total: float
    column_name: str


def _parse_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        parsed = float(Decimal(text))
    except (InvalidOperation, ValueError):
        return None
    # ``Decimal("nan")`` / ``Decimal("inf")`` parse without error; a non-finite
    # value is not a usable measure — it poisons the grand-total sum and makes
    # every reconciliation comparison false (NaN != NaN). Treat it as None.
    return parsed if math.isfinite(parsed) else None


def _pick_total_column(columns: list[str], rows: list[list[Any]]) -> str | None:
    """Pick the single numeric measure column to sum for reconciliation."""
    if not columns or not rows:
        return None

    numeric_cols: list[str] = []
    for idx, col in enumerate(columns):
        values = [_parse_number(row[idx] if idx < len(row) else None) for row in rows]
        if values and all(v is not None for v in values):
            numeric_cols.append(col)

    if len(numeric_cols) == 1:
        return numeric_cols[0]

    hinted = [col for col in numeric_cols if any(h in col.lower() for h in _NUMERIC_HINTS)]
    if len(hinted) == 1:
        return hinted[0]
    return None


def collect_sql_totals_snapshots(
    all_sql_results: Sequence[SQLAgentResult],
) -> list[SqlTotalsSnapshot]:
    snapshots: list[SqlTotalsSnapshot] = []
    for idx, sr in enumerate(all_sql_results, start=1):
        if not sr or not sr.results or not sr.results.rows:
            continue
        qr = sr.results
        rows = qr.rows
        columns = list(qr.columns)
        col = _pick_total_column(columns, rows)
        if not col:
            continue
        col_idx = columns.index(col)
        total = 0.0
        for row in rows:
            val = _parse_number(row[col_idx] if col_idx < len(row) else None)
            if val is None:
                total = 0.0
                break
            total += val
        else:
            snapshots.append(
                SqlTotalsSnapshot(
                    query_index=idx,
                    row_count=qr.row_count,
                    grand_total=round(total, 2),
                    column_name=col,
                )
            )
    return snapshots


def sql_results_reconcile(all_sql_results: Sequence[SQLAgentResult]) -> bool:
    """Return True when at least two SQL results share the same grand total.

    Mixed workflows (e.g. gross revenue + refund totals in one turn) may produce
    several different grand totals; we only require a reconciled *pair*, not that
    every query agrees.
    """
    snapshots = collect_sql_totals_snapshots(all_sql_results)
    if len(snapshots) < 2:
        return False
    return any(len(group) >= 2 for group in _group_snapshots_by_total(snapshots))


# AQ-10: float summation order makes independently-computed totals drift by
# sub-cent amounts (and rounding at the 2-decimal boundary can flip a penny,
# e.g. 144693.145 vs 144693.1449999). Exact equality misses those reconciled
# pairs, so comparison uses a relative tolerance (plus an absolute floor for
# near-zero totals).
_RECONCILE_REL_TOL = 1e-6
_RECONCILE_ABS_TOL = 1e-6


def _totals_match(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=_RECONCILE_REL_TOL, abs_tol=_RECONCILE_ABS_TOL)


def _group_snapshots_by_total(
    snapshots: Sequence[SqlTotalsSnapshot],
) -> list[list[SqlTotalsSnapshot]]:
    """Group snapshots whose grand totals match within float tolerance."""
    groups: list[list[SqlTotalsSnapshot]] = []
    for snap in snapshots:
        for group in groups:
            if _totals_match(group[0].grand_total, snap.grand_total):
                group.append(snap)
                break
        else:
            groups.append([snap])
    return groups


def build_reconciliation_note(all_sql_results: Sequence[SQLAgentResult]) -> str | None:
    """Prompt note when aggregate and detail queries produce the same total."""
    snapshots = collect_sql_totals_snapshots(all_sql_results)
    if len(snapshots) < 2:
        return None

    for group in _group_snapshots_by_total(snapshots):
        if len(group) < 2:
            continue
        total = group[0].grand_total
        labels = ", ".join(f"Query {snap.query_index}" for snap in group)
        col = group[0].column_name
        return (
            f"SQL RECONCILIATION (verified): {labels} all sum to {total:,.2f} "
            f"via `{col}`. The queries are numerically consistent — do NOT tell the user "
            "an earlier query was wrong, missed product types, or reported lower totals "
            "unless you can cite a specific numeric mismatch between the result sets."
        )
    return None


def scrub_false_sql_self_correction(text: str, *, reconciled: bool) -> str:
    """Remove a false 'my first query was wrong' lead-in when totals reconcile."""
    if not reconciled or not text.strip():
        return text

    lower = text.lower()
    if not any(marker in lower for marker in _FALSE_CORRECTION_MARKERS):
        return text

    paragraphs = text.split("\n\n")
    kept: list[str] = []
    skipping = True
    for para in paragraphs:
        para_lower = para.lower()
        if skipping and any(marker in para_lower for marker in _FALSE_CORRECTION_MARKERS):
            continue
        if skipping and para_lower.strip().startswith("let me classify properly"):
            continue
        skipping = False
        kept.append(para)

    if not kept:
        return text
    return "\n\n".join(kept).strip()
