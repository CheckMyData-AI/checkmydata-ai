"""Automated sanity checks on query results before presenting to users."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SanityWarning:
    level: str  # "info" | "warning" | "critical"
    check_type: str
    message: str
    column: str | None = None
    suggestion: str = ""


@dataclass
class BenchmarkComparison:
    metric_key: str
    benchmark_value: float
    actual_value: float
    deviation_pct: float
    level: str  # "ok" | "warning" | "critical"


class DataSanityChecker:
    """Run automatic sanity checks on query result rows."""

    def check(
        self,
        rows: list[dict[str, Any]],
        columns: list[str],
        query: str = "",
        question: str = "",
    ) -> list[SanityWarning]:
        warnings: list[SanityWarning] = []
        if not rows:
            return warnings

        warnings.extend(self._check_all_zero_null(rows, columns))
        warnings.extend(self._check_temporal_anomalies(rows, columns))
        warnings.extend(self._check_aggregation_sanity(rows, columns, query))
        warnings.extend(self._check_negative_values(rows, columns))
        warnings.extend(self._check_duplicate_keys(rows, columns, query))
        warnings.extend(self._check_single_row_anomaly(rows, question))
        warnings.extend(self._check_date_range_mismatch(rows, columns, question))
        return warnings

    def check_against_benchmark(
        self,
        rows: list[dict[str, Any]],
        columns: list[str],
        benchmark_value: float,
        metric_key: str,
    ) -> BenchmarkComparison | None:
        """Compare the first numeric aggregate in *rows* against a known benchmark."""
        actual = self._extract_first_numeric(rows, columns)
        if actual is None or benchmark_value == 0:
            return None

        deviation = abs(actual - benchmark_value) / abs(benchmark_value) * 100

        if deviation > 100:
            level = "critical"
        elif deviation > 30:
            level = "warning"
        else:
            level = "ok"

        return BenchmarkComparison(
            metric_key=metric_key,
            benchmark_value=benchmark_value,
            actual_value=actual,
            deviation_pct=round(deviation, 1),
            level=level,
        )

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_all_zero_null(
        self,
        rows: list[dict[str, Any]],
        columns: list[str],
    ) -> list[SanityWarning]:
        warnings: list[SanityWarning] = []
        for col in columns:
            values = [r.get(col) for r in rows]
            numeric_values = [
                v for v in values if isinstance(v, (int, float)) and not math.isnan(v)
            ]
            if not numeric_values:
                non_none = [v for v in values if v is not None]
                if not non_none and len(rows) > 1:
                    warnings.append(
                        SanityWarning(
                            level="warning",
                            check_type="all_null",
                            message=f"Column '{col}' is entirely NULL ({len(rows)} rows).",
                            column=col,
                            suggestion=(
                                "Verify this column is populated and the query filters are correct."
                            ),
                        )
                    )
                continue

            if all(v == 0 for v in numeric_values) and len(numeric_values) > 1:
                warnings.append(
                    SanityWarning(
                        level="warning",
                        check_type="all_zero",
                        message=f"Column '{col}' is all zeros ({len(numeric_values)} rows).",
                        column=col,
                        suggestion=(
                            "Check if this column stores data in a different"
                            " unit or requires a different filter."
                        ),
                    )
                )
        return warnings

    def _check_temporal_anomalies(
        self,
        rows: list[dict[str, Any]],
        columns: list[str],
    ) -> list[SanityWarning]:
        warnings: list[SanityWarning] = []
        now_utc = datetime.now(UTC)
        now_naive = now_utc.replace(tzinfo=None)

        for col in columns:
            dates: list[datetime] = []
            for r in rows:
                val = r.get(col)
                if isinstance(val, datetime):
                    dates.append(val)
                elif isinstance(val, str):
                    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
                        try:
                            dates.append(datetime.strptime(val, fmt))
                            break
                        except ValueError:
                            continue

            if not dates:
                continue

            future = [d for d in dates if d > (now_utc if d.tzinfo else now_naive)]
            if future:
                warnings.append(
                    SanityWarning(
                        level="warning",
                        check_type="future_dates",
                        message=(
                            f"Column '{col}' has {len(future)} future date(s). "
                            "This may indicate a timezone or data quality issue."
                        ),
                        column=col,
                        suggestion="Check timezone handling and data entry.",
                    )
                )
        return warnings

    def _check_aggregation_sanity(
        self,
        rows: list[dict[str, Any]],
        columns: list[str],
        query: str,
    ) -> list[SanityWarning]:
        """Detect when percentages don't sum to ~100 or parts don't match total."""
        warnings: list[SanityWarning] = []

        pct_cols = [
            c
            for c in columns
            if "percent" in c.lower() or "pct" in c.lower() or "rate" in c.lower()
        ]

        for col in pct_cols:
            values: list[float] = [
                float(r[col]) for r in rows if col in r and isinstance(r[col], (int, float))
            ]
            if len(values) >= 2:
                total = sum(values)
                if 0 < total < 80 or total > 120:
                    warnings.append(
                        SanityWarning(
                            level="info",
                            check_type="percentage_sum",
                            message=(
                                f"Column '{col}' values sum to {total:.1f}% "
                                "(expected ~100% for percentage breakdowns)."
                            ),
                            column=col,
                            suggestion="Verify this is a percentage breakdown and not cumulative.",
                        )
                    )
        return warnings

    def _check_negative_values(
        self,
        rows: list[dict[str, Any]],
        columns: list[str],
    ) -> list[SanityWarning]:
        """Flag negative values in typically-positive columns."""
        warnings: list[SanityWarning] = []
        positive_hints = (
            "revenue", "sales", "count", "total", "amount", "price",
            "cost", "quantity", "profit", "sum", "balance", "fee",
        )
        for col in columns:
            col_lower = col.lower()
            if not any(h in col_lower for h in positive_hints):
                continue
            negatives = [
                r[col] for r in rows
                if col in r
                and isinstance(r[col], (int, float))
                and not math.isnan(r[col])
                and r[col] < 0
            ]
            if negatives:
                warnings.append(SanityWarning(
                    level="warning",
                    check_type="negative_value",
                    message=(
                        f"Column '{col}' has {len(negatives)} negative "
                        f"value(s) (min={min(negatives)}), which is unusual "
                        f"for a {col_lower}-type metric."
                    ),
                    column=col,
                    suggestion=(
                        "Verify the sign convention. Negative values may "
                        "indicate refunds, corrections, or a filter issue."
                    ),
                ))
        return warnings

    def _check_duplicate_keys(
        self,
        rows: list[dict[str, Any]],
        columns: list[str],
        query: str,
    ) -> list[SanityWarning]:
        """Detect duplicate key values when GROUP BY is present."""
        warnings: list[SanityWarning] = []
        if "group by" not in query.lower() or len(rows) < 2:
            return warnings

        first_col = columns[0]
        values = [r.get(first_col) for r in rows]
        unique_count = len(set(values))
        if unique_count < len(values):
            dup_count = len(values) - unique_count
            warnings.append(SanityWarning(
                level="warning",
                check_type="duplicate_keys",
                message=(
                    f"GROUP BY result has {dup_count} duplicate key(s) "
                    f"in column '{first_col}' ({len(values)} rows, "
                    f"{unique_count} unique)."
                ),
                column=first_col,
                suggestion="Check if the GROUP BY clause is correct.",
            ))
        return warnings

    def _check_single_row_anomaly(
        self,
        rows: list[dict[str, Any]],
        question: str,
    ) -> list[SanityWarning]:
        """Warn when a single row is returned but the question implies multiple."""
        warnings: list[SanityWarning] = []
        if len(rows) != 1 or not question:
            return warnings

        plural_hints = (
            "breakdown", "by category", "by month", "by year",
            "by week", "by day", "per ", "each ", "group by",
            "top ", "compare", "distribution", "by region",
            "by country", "by type", "by status",
        )
        q_lower = question.lower()
        if any(h in q_lower for h in plural_hints):
            warnings.append(SanityWarning(
                level="info",
                check_type="single_row_for_breakdown",
                message=(
                    "Only 1 row returned, but the question seems to "
                    "ask for a breakdown or comparison."
                ),
                suggestion=(
                    "The query may be missing a GROUP BY clause or "
                    "the filter is too restrictive."
                ),
            ))
        return warnings

    def _check_date_range_mismatch(
        self,
        rows: list[dict[str, Any]],
        columns: list[str],
        question: str,
    ) -> list[SanityWarning]:
        """Warn when date range in results doesn't match the question."""
        import re

        warnings: list[SanityWarning] = []
        if not question or not rows:
            return warnings

        q_lower = question.lower()
        period_map = {
            "last week": 7, "past week": 7,
            "last month": 31, "past month": 31,
            "last quarter": 92, "past quarter": 92,
            "last year": 366, "past year": 366,
            "yesterday": 1, "today": 1,
        }

        expected_days: int | None = None
        for phrase, days in period_map.items():
            if phrase in q_lower:
                expected_days = days
                break

        if expected_days is None:
            return warnings

        all_dates: list[datetime] = []
        for col in columns:
            for r in rows:
                val = r.get(col)
                if isinstance(val, datetime):
                    all_dates.append(val)
                elif isinstance(val, str):
                    m = re.match(r"\d{4}-\d{2}-\d{2}", val)
                    if m:
                        try:
                            all_dates.append(
                                datetime.strptime(m.group(), "%Y-%m-%d")
                            )
                        except ValueError:
                            continue

        if len(all_dates) < 2:
            return warnings

        actual_span = (max(all_dates) - min(all_dates)).days
        if actual_span > expected_days * 3:
            warnings.append(SanityWarning(
                level="warning",
                check_type="date_range_mismatch",
                message=(
                    f"Data spans {actual_span} days but the question "
                    f"implies ~{expected_days} days."
                ),
                suggestion=(
                    "The date filter may be missing or too broad."
                ),
            ))
        return warnings

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_first_numeric(
        rows: list[dict[str, Any]],
        columns: list[str],
    ) -> float | None:
        """Return the first numeric value found (typically the aggregate)."""
        for r in rows:
            for col in columns:
                val = r.get(col)
                if isinstance(val, (int, float)) and not math.isnan(val):
                    return float(val)
        return None

    def format_warnings(self, warnings: list[SanityWarning]) -> str:
        if not warnings:
            return ""
        lines = ["\n⚠️ DATA SANITY WARNINGS:"]
        for w in warnings:
            icon = {"critical": "🔴", "warning": "🟡", "info": "ℹ️"}.get(w.level, "❓")
            lines.append(f"  {icon} [{w.check_type}] {w.message}")
            if w.suggestion:
                lines.append(f"     → {w.suggestion}")
        return "\n".join(lines)
