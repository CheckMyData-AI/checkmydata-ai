"""Anomaly Intelligence Engine — upgrades DataSanityChecker with root cause
analysis, severity scoring, and context enrichment.

Instead of just "something changed", this module explains:
- WHY (root cause hypothesis)
- WHERE (specific metrics/rows affected)
- HOW CRITICAL (business impact severity)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.core.data_sanity_checker import DataSanityChecker, SanityWarning

logger = logging.getLogger(__name__)


@dataclass
class AnomalyReport:
    """Enriched anomaly with root cause, severity, and recommended action."""

    check_type: str
    title: str
    description: str
    severity: str
    business_impact: str
    root_cause_hypothesis: str
    affected_metrics: list[str] = field(default_factory=list)
    affected_rows: int = 0
    confidence: float = 0.5
    recommended_action: str = ""
    expected_impact: str = ""
    related_anomalies: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_type": self.check_type,
            "title": self.title,
            "description": self.description,
            "severity": self.severity,
            "business_impact": self.business_impact,
            "root_cause_hypothesis": self.root_cause_hypothesis,
            "affected_metrics": self.affected_metrics,
            "affected_rows": self.affected_rows,
            "confidence": round(self.confidence, 2),
            "recommended_action": self.recommended_action,
            "expected_impact": self.expected_impact,
            "related_anomalies": self.related_anomalies,
        }


class AnomalyIntelligenceEngine:
    """Wraps DataSanityChecker and enriches warnings into full anomaly reports."""

    def __init__(self) -> None:
        self._checker = DataSanityChecker()

    def analyze(
        self,
        rows: list[dict[str, Any]],
        columns: list[str],
        query: str = "",
        question: str = "",
    ) -> list[AnomalyReport]:
        """Run sanity checks and enrich each warning into a full anomaly report."""
        warnings = self._checker.check(rows, columns, query, question)
        if not warnings:
            return []

        reports: list[AnomalyReport] = []
        for warning in warnings:
            report = self._enrich_warning(warning, rows, columns)
            reports.append(report)

        self._link_related_anomalies(reports)
        reports.sort(key=lambda r: self._severity_rank(r.severity), reverse=True)
        return reports

    def _enrich_warning(
        self,
        warning: SanityWarning,
        rows: list[dict[str, Any]],
        columns: list[str],
    ) -> AnomalyReport:
        """Convert a SanityWarning into a rich AnomalyReport."""
        severity = self._compute_severity(warning, rows, columns)
        business_impact = self._estimate_business_impact(warning, rows, columns)
        root_cause = self._hypothesize_root_cause(warning, rows, columns)
        action = self._suggest_action(warning, root_cause)
        affected_rows = self._count_affected_rows(warning, rows)
        affected_metrics = [warning.column] if warning.column else []

        return AnomalyReport(
            check_type=warning.check_type,
            title=self._format_title(warning),
            description=warning.message,
            severity=severity,
            business_impact=business_impact,
            root_cause_hypothesis=root_cause,
            affected_metrics=affected_metrics,
            affected_rows=affected_rows,
            confidence=self._compute_confidence(warning, rows),
            recommended_action=action,
            expected_impact=self._estimate_fix_impact(warning, severity),
        )

    def _compute_severity(
        self,
        warning: SanityWarning,
        rows: list[dict[str, Any]],
        columns: list[str],
    ) -> str:
        if warning.level == "critical":
            return "critical"

        if warning.check_type == "all_null" and warning.column:
            return "warning"

        if warning.check_type == "negative_value":
            col = warning.column or ""
            neg_count = sum(
                1 for r in rows if col in r and isinstance(r[col], (int, float)) and r[col] < 0
            )
            if neg_count > len(rows) * 0.1:
                return "warning"

        if warning.check_type == "date_range_mismatch":
            return "warning"

        if warning.check_type == "duplicate_keys":
            return "warning"

        if warning.check_type == "all_zero" and len(rows) > 5:
            return "warning"

        return "info"

    def _estimate_business_impact(
        self,
        warning: SanityWarning,
        rows: list[dict[str, Any]],
        columns: list[str],
    ) -> str:
        """Estimate business impact in plain English."""
        if warning.check_type == "negative_value" and warning.column:
            col = warning.column
            negatives = [
                r[col] for r in rows if col in r and isinstance(r[col], (int, float)) and r[col] < 0
            ]
            if negatives:
                total_neg = sum(negatives)
                return (
                    f"Negative values sum to {total_neg:,.2f} — may indicate refunds, "
                    "data errors, or revenue loss"
                )

        if warning.check_type == "all_null":
            return (
                f"Column '{warning.column}' has no data — reports using this column "
                "will be empty or misleading"
            )

        if warning.check_type == "all_zero":
            return (
                f"Column '{warning.column}' is all zeros — calculations depending on "
                "this column will be incorrect"
            )

        if warning.check_type == "date_range_mismatch":
            return (
                "Results may include data outside the expected time period, "
                "leading to incorrect conclusions"
            )

        if warning.check_type == "duplicate_keys":
            return (
                "Duplicate group keys mean aggregations are double-counting, "
                "inflating reported metrics"
            )

        if warning.check_type == "percentage_sum":
            return "Percentage breakdown doesn't sum correctly — may confuse stakeholders"

        return "Potential data quality issue that may affect analysis accuracy"

    def _hypothesize_root_cause(
        self,
        warning: SanityWarning,
        rows: list[dict[str, Any]],
        columns: list[str],
    ) -> str:
        if warning.check_type == "all_null":
            return (
                f"Column '{warning.column}' may have been recently added and not yet populated, "
                "or the query filters may be too restrictive, or there's a schema migration issue"
            )

        if warning.check_type == "all_zero":
            return (
                f"Column '{warning.column}' may store values in a different unit or format, "
                "or the data pipeline hasn't populated this column yet"
            )

        if warning.check_type == "negative_value":
            return (
                "Negative values typically indicate refunds, corrections, "
                "or accounting adjustments. "
                "If unexpected, this may be a sign of data entry errors or formula issues"
            )

        if warning.check_type == "future_dates":
            return (
                "Future dates often result from timezone conversion errors, "
                "test data that wasn't cleaned, or scheduled/projected records"
            )

        if warning.check_type == "date_range_mismatch":
            return (
                "The query's WHERE clause may not include a date filter, or the filter "
                "references the wrong column"
            )

        if warning.check_type == "duplicate_keys":
            return (
                "The GROUP BY clause may be missing a required dimension, "
                "or the source data has genuine duplicates that need deduplication"
            )

        if warning.check_type == "percentage_sum":
            return (
                "The values may be cumulative rather than a percentage breakdown, "
                "or some categories are missing"
            )

        if warning.check_type == "single_row_for_breakdown":
            return (
                "The query may be missing a GROUP BY clause, or the date/category filter "
                "is too narrow, collapsing all data into a single row"
            )

        return "Further investigation needed to determine root cause"

    def _suggest_action(self, warning: SanityWarning, root_cause: str) -> str:
        actions = {
            "all_null": (
                f"Verify that column '{warning.column}' is populated. "
                "Check data pipeline and ingestion jobs."
            ),
            "all_zero": (
                f"Check if '{warning.column}' uses a different unit. "
                "Try querying related tables for the same metric."
            ),
            "negative_value": (
                "Review negative entries individually. If they are refunds, "
                "consider filtering or flagging them."
            ),
            "future_dates": (
                "Add a date filter (WHERE date <= CURRENT_DATE) or investigate timezone handling."
            ),
            "date_range_mismatch": (
                "Add or fix the date range filter in the query to match the intended time period."
            ),
            "duplicate_keys": (
                "Review the GROUP BY clause. Add missing dimensions or deduplicate source data."
            ),
            "percentage_sum": (
                "Verify this is a percentage breakdown. If cumulative, adjust the presentation."
            ),
            "single_row_for_breakdown": (
                "Add a GROUP BY clause or broaden the date/category filter."
            ),
        }
        return actions.get(
            warning.check_type,
            ("Investigate the data quality issue and verify the query logic."),
        )

    def _count_affected_rows(
        self,
        warning: SanityWarning,
        rows: list[dict[str, Any]],
    ) -> int:
        if not warning.column:
            return len(rows)

        col = warning.column
        if warning.check_type == "all_null":
            return sum(1 for r in rows if r.get(col) is None)
        if warning.check_type == "negative_value":
            return sum(
                1 for r in rows if col in r and isinstance(r[col], (int, float)) and r[col] < 0
            )
        if warning.check_type == "all_zero":
            return sum(
                1 for r in rows if col in r and isinstance(r[col], (int, float)) and r[col] == 0
            )
        return len(rows)

    def _compute_confidence(
        self,
        warning: SanityWarning,
        rows: list[dict[str, Any]],
    ) -> float:
        base = 0.5
        if len(rows) >= 100:
            base += 0.15
        elif len(rows) >= 20:
            base += 0.1
        elif len(rows) >= 5:
            base += 0.05

        if warning.level == "critical":
            base += 0.15
        elif warning.level == "warning":
            base += 0.1

        return min(0.95, base)

    def _estimate_fix_impact(self, warning: SanityWarning, severity: str) -> str:
        if severity == "critical":
            return (
                "Fixing this will significantly improve data accuracy and "
                "prevent misleading reports"
            )
        if severity == "warning":
            return "Addressing this will improve the reliability of analysis involving this metric"
        return "Minor improvement to data quality"

    def _link_related_anomalies(self, reports: list[AnomalyReport]) -> None:
        """Link anomalies that share the same affected columns or check types."""
        for i, r1 in enumerate(reports):
            for j, r2 in enumerate(reports):
                if i == j:
                    continue
                if (
                    set(r1.affected_metrics) & set(r2.affected_metrics)
                    or r1.check_type == r2.check_type
                ):
                    r1.related_anomalies.append(r2.title)

    @staticmethod
    def _severity_rank(severity: str) -> int:
        return {"critical": 4, "warning": 3, "info": 2, "positive": 1}.get(severity, 0)

    @staticmethod
    def _format_title(warning: SanityWarning) -> str:
        titles = {
            "all_null": f"Missing data: {warning.column} is entirely NULL",
            "all_zero": f"Zero values: {warning.column} is all zeros",
            "negative_value": f"Unexpected negatives in {warning.column}",
            "future_dates": f"Future dates detected in {warning.column}",
            "date_range_mismatch": "Data spans a wider date range than expected",
            "duplicate_keys": f"Duplicate keys in {warning.column}",
            "percentage_sum": f"Percentage sum mismatch in {warning.column}",
            "single_row_for_breakdown": "Expected breakdown but got single row",
        }
        return titles.get(warning.check_type, warning.message[:80])

    def format_report(self, reports: list[AnomalyReport]) -> str:
        """Format anomaly reports as text for chat display."""
        if not reports:
            return ""

        lines = ["\n🔍 ANOMALY INTELLIGENCE REPORT:"]
        for report in reports:
            icon = {"critical": "🔴", "warning": "🟡", "info": "ℹ️"}.get(report.severity, "❓")
            lines.append(f"\n  {icon} **{report.title}**")
            lines.append(f"     {report.description}")
            if report.root_cause_hypothesis:
                lines.append(f"     💡 Root cause: {report.root_cause_hypothesis}")
            if report.business_impact:
                lines.append(f"     📊 Impact: {report.business_impact}")
            if report.recommended_action:
                lines.append(f"     → Action: {report.recommended_action}")
            if report.expected_impact:
                lines.append(f"     ✨ Expected: {report.expected_impact}")
        return "\n".join(lines)
