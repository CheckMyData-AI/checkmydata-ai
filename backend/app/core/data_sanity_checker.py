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
