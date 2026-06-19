"""Detect when multiple SQL results reconcile and guard against false self-correction."""

from __future__ import annotations

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
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(Decimal(text))
    except (InvalidOperation, ValueError):
        return None


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
    all_sql_results: list[SQLAgentResult | None],
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


def sql_results_reconcile(all_sql_results: list[SQLAgentResult | None]) -> bool:
    """Return True when at least two SQL results share the same grand total.

    Mixed workflows (e.g. gross revenue + refund totals in one turn) may produce
    several different grand totals; we only require a reconciled *pair*, not that
    every query agrees.
    """
    snapshots = collect_sql_totals_snapshots(all_sql_results)
    if len(snapshots) < 2:
        return False
    counts: dict[float, int] = {}
    for snap in snapshots:
        counts[snap.grand_total] = counts.get(snap.grand_total, 0) + 1
    return any(n >= 2 for n in counts.values())


def build_reconciliation_note(all_sql_results: list[SQLAgentResult | None]) -> str | None:
    """Prompt note when aggregate and detail queries produce the same total."""
    snapshots = collect_sql_totals_snapshots(all_sql_results)
    if len(snapshots) < 2:
        return None

    by_total: dict[float, list[SqlTotalsSnapshot]] = {}
    for snap in snapshots:
        by_total.setdefault(snap.grand_total, []).append(snap)

    for total, group in by_total.items():
        if len(group) < 2:
            continue
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
