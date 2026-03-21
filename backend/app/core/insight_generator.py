"""Pure-Python insight generation from query results.

Detects trends, outliers, concentration, and summarizes totals — no LLM
calls.  Each insight is a dict with ``type``, ``title``, ``description``,
and ``confidence`` (0.0–1.0).
"""

from __future__ import annotations

import math
import statistics
from typing import Any

_TEMPORAL_HINTS = frozenset(
    {"date", "month", "year", "day", "week", "time", "created", "updated", "timestamp"}
)

_TREND_THRESHOLD_PCT = 10


class InsightGenerator:
    """Stateless helper — all methods are static / classmethod."""

    @staticmethod
    def analyze(
        rows: list[list[Any]] | list[dict[str, Any]],
        columns: list[str],
        query: str = "",  # noqa: ARG004
        question: str = "",  # noqa: ARG004
    ) -> list[dict[str, Any]]:
        if len(rows) < 3 or not columns:
            return []

        normalised: list[list[Any]]
        if rows and isinstance(rows[0], dict):
            normalised = [[r.get(c) for c in columns] for r in rows]  # type: ignore[union-attr]
        else:
            normalised = rows  # type: ignore[assignment]

        insights: list[dict[str, Any]] = []
        insights.extend(InsightGenerator._detect_trends(normalised, columns))
        insights.extend(InsightGenerator._detect_outliers(normalised, columns))
        insights.extend(InsightGenerator._detect_concentration(normalised, columns))
        insights.extend(InsightGenerator._summarize_totals(normalised, columns))
        return insights

    # ------------------------------------------------------------------
    # Trend detection
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_trends(
        rows: list[list[Any]],
        columns: list[str],
    ) -> list[dict[str, Any]]:
        temporal_idx: int | None = None
        for i, col in enumerate(columns):
            if any(hint in col.lower() for hint in _TEMPORAL_HINTS):
                temporal_idx = i
                break

        if temporal_idx is None:
            return []

        insights: list[dict[str, Any]] = []
        for i, col in enumerate(columns):
            if i == temporal_idx:
                continue
            values = _numeric_values(rows, i)
            if len(values) < 3:
                continue

            first_val = values[0]
            last_val = values[-1]
            if first_val == 0:
                continue

            change_pct = ((last_val - first_val) / abs(first_val)) * 100

            if abs(change_pct) < _TREND_THRESHOLD_PCT:
                continue

            direction = "Upward" if change_pct > 0 else "Downward"
            arrow = "up" if change_pct > 0 else "down"
            insights.append(
                {
                    "type": f"trend_{arrow}",
                    "title": f"{direction} trend in {col}",
                    "description": (
                        f"{col} {'increased' if change_pct > 0 else 'decreased'} "
                        f"by {abs(change_pct):.1f}% over the period "
                        f"(from {_fmt(first_val)} to {_fmt(last_val)})"
                    ),
                    "confidence": min(0.9, 0.6 + len(values) * 0.02),
                    "column": col,
                }
            )

        return insights

    # ------------------------------------------------------------------
    # Outlier detection
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_outliers(
        rows: list[list[Any]],
        columns: list[str],
    ) -> list[dict[str, Any]]:
        insights: list[dict[str, Any]] = []

        for i, col in enumerate(columns):
            values = _numeric_values(rows, i)
            if len(values) < 5:
                continue

            mean = statistics.mean(values)
            std = statistics.stdev(values)
            if std == 0:
                continue

            for row_idx, val in enumerate(values):
                z = (val - mean) / std
                if abs(z) <= 2:
                    continue
                direction = "higher" if z > 0 else "lower"
                insights.append(
                    {
                        "type": "outlier",
                        "title": f"Outlier in {col}",
                        "description": (
                            f"{_fmt(val)} in {col} (row {row_idx + 1}) is significantly "
                            f"{direction} than the average ({_fmt(mean)})"
                        ),
                        "confidence": min(0.95, 0.5 + abs(z) * 0.1),
                        "column": col,
                    }
                )

            if len(insights) > 5:
                break

        return insights[:5]

    # ------------------------------------------------------------------
    # Concentration detection
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_concentration(
        rows: list[list[Any]],
        columns: list[str],
    ) -> list[dict[str, Any]]:
        num_idx: int | None = None
        for i, col in enumerate(columns):
            vals = _numeric_values(rows, i)
            if vals:
                num_idx = i
                break

        if num_idx is None:
            return []

        col = columns[num_idx]
        values = _numeric_values(rows, num_idx)
        if len(values) < 4:
            return []

        total = sum(abs(v) for v in values)
        if total == 0:
            return []

        sorted_vals = sorted(values, reverse=True)
        top3_sum = sum(sorted_vals[:3])
        pct = (top3_sum / total) * 100

        if pct <= 50:
            return []

        return [
            {
                "type": "concentration",
                "title": f"High concentration in {col}",
                "description": (f"Top 3 entries account for {pct:.1f}% of total {col}"),
                "confidence": min(0.9, 0.5 + (pct - 50) * 0.01),
                "column": col,
            }
        ]

    # ------------------------------------------------------------------
    # Totals summary
    # ------------------------------------------------------------------

    @staticmethod
    def _summarize_totals(
        rows: list[list[Any]],
        columns: list[str],
    ) -> list[dict[str, Any]]:
        if len(rows) != 1:
            return []

        insights: list[dict[str, Any]] = []
        for i, col in enumerate(columns):
            val = rows[0][i]
            if not isinstance(val, (int, float)):
                continue
            if isinstance(val, float) and math.isnan(val):
                continue
            insights.append(
                {
                    "type": "summary",
                    "title": f"{col}: {_fmt(val)}",
                    "description": f"The query returned a single value for {col}: {_fmt(val)}",
                    "confidence": 0.95,
                    "column": col,
                }
            )

        return insights[:3]


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _numeric_values(rows: list[list[Any]], col_idx: int) -> list[float]:
    result: list[float] = []
    for row in rows:
        if col_idx >= len(row):
            continue
        val = row[col_idx]
        if isinstance(val, (int, float)) and not (isinstance(val, float) and math.isnan(val)):
            result.append(float(val))
    return result


def _fmt(val: float) -> str:
    if abs(val) >= 1_000_000:
        return f"{val:,.0f}"
    if abs(val) >= 1_000:
        return f"{val:,.1f}"
    if val == int(val):
        return str(int(val))
    return f"{val:.2f}"
