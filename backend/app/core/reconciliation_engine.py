"""Cross-Source Reconciliation Engine.

Compares data across multiple database connections within a project
to find discrepancies: missing records, value mismatches, timing
differences, and schema divergence.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Discrepancy:
    """A single reconciliation discrepancy between two sources."""

    discrepancy_type: str  # missing_records, value_mismatch, schema_diff, count_diff
    severity: str  # critical, warning, info
    title: str
    description: str
    source_a_name: str
    source_b_name: str
    source_a_value: Any = None
    source_b_value: Any = None
    affected_metric: str = ""
    affected_table: str = ""
    difference_pct: float = 0.0
    likely_cause: str = ""
    recommended_action: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReconciliationReport:
    """Full reconciliation report between two sources."""

    source_a_name: str
    source_b_name: str
    source_a_connection_id: str
    source_b_connection_id: str
    status: str  # clean, discrepancies_found, error
    total_checks: int = 0
    discrepancies: list[Discrepancy] = field(default_factory=list)
    summary: str = ""

    @property
    def critical_count(self) -> int:
        return sum(1 for d in self.discrepancies if d.severity == "critical")

    @property
    def warning_count(self) -> int:
        return sum(1 for d in self.discrepancies if d.severity == "warning")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_a_name": self.source_a_name,
            "source_b_name": self.source_b_name,
            "source_a_connection_id": self.source_a_connection_id,
            "source_b_connection_id": self.source_b_connection_id,
            "status": self.status,
            "total_checks": self.total_checks,
            "critical_count": self.critical_count,
            "warning_count": self.warning_count,
            "discrepancies": [d.to_dict() for d in self.discrepancies],
            "summary": self.summary,
        }


class ReconciliationEngine:
    """Compares data between two sources to find discrepancies.

    Accepts pre-fetched table metadata and query results rather than
    connecting to databases directly, keeping the engine pure and testable.
    """

    COUNT_DIFF_WARNING_THRESHOLD = 0.05
    COUNT_DIFF_CRITICAL_THRESHOLD = 0.20
    VALUE_DIFF_WARNING_THRESHOLD = 0.01
    VALUE_DIFF_CRITICAL_THRESHOLD = 0.05

    def reconcile_row_counts(
        self,
        source_a_name: str,
        source_b_name: str,
        counts_a: dict[str, int],
        counts_b: dict[str, int],
    ) -> list[Discrepancy]:
        """Compare row counts for tables present in both sources."""
        discrepancies: list[Discrepancy] = []
        common_tables = set(counts_a.keys()) & set(counts_b.keys())

        for table in sorted(common_tables):
            ca = counts_a[table]
            cb = counts_b[table]
            if ca == cb:
                continue
            denominator = max(ca, cb, 1)
            diff_pct = abs(ca - cb) / denominator

            if diff_pct >= self.COUNT_DIFF_CRITICAL_THRESHOLD:
                severity = "critical"
            elif diff_pct >= self.COUNT_DIFF_WARNING_THRESHOLD:
                severity = "warning"
            else:
                severity = "info"

            discrepancies.append(
                Discrepancy(
                    discrepancy_type="count_diff",
                    severity=severity,
                    title=f"Row count mismatch: {table}",
                    description=(
                        f"{source_a_name} has {ca:,} rows, "
                        f"{source_b_name} has {cb:,} rows "
                        f"({diff_pct:.1%} difference)"
                    ),
                    source_a_name=source_a_name,
                    source_b_name=source_b_name,
                    source_a_value=ca,
                    source_b_value=cb,
                    affected_table=table,
                    difference_pct=round(diff_pct * 100, 2),
                    likely_cause=self._guess_count_cause(ca, cb, diff_pct),
                    recommended_action=(
                        f"Investigate why '{table}' has different row counts "
                        f"across sources. Check replication lag or ETL issues."
                    ),
                )
            )

        only_a = set(counts_a.keys()) - set(counts_b.keys())
        for table in sorted(only_a):
            discrepancies.append(
                Discrepancy(
                    discrepancy_type="missing_records",
                    severity="warning",
                    title=f"Table only in {source_a_name}: {table}",
                    description=(
                        f"'{table}' ({counts_a[table]:,} rows) exists in "
                        f"{source_a_name} but not in {source_b_name}"
                    ),
                    source_a_name=source_a_name,
                    source_b_name=source_b_name,
                    source_a_value=counts_a[table],
                    source_b_value=None,
                    affected_table=table,
                    likely_cause="Table may not be replicated or migrated",
                    recommended_action=(f"Check if '{table}' should exist in {source_b_name}."),
                )
            )

        only_b = set(counts_b.keys()) - set(counts_a.keys())
        for table in sorted(only_b):
            discrepancies.append(
                Discrepancy(
                    discrepancy_type="missing_records",
                    severity="warning",
                    title=f"Table only in {source_b_name}: {table}",
                    description=(
                        f"'{table}' ({counts_b[table]:,} rows) exists in "
                        f"{source_b_name} but not in {source_a_name}"
                    ),
                    source_a_name=source_a_name,
                    source_b_name=source_b_name,
                    source_a_value=None,
                    source_b_value=counts_b[table],
                    affected_table=table,
                    likely_cause="Table may not be replicated or migrated",
                    recommended_action=(f"Check if '{table}' should exist in {source_a_name}."),
                )
            )

        return discrepancies

    def reconcile_aggregate_values(
        self,
        source_a_name: str,
        source_b_name: str,
        aggregates_a: dict[str, float],
        aggregates_b: dict[str, float],
    ) -> list[Discrepancy]:
        """Compare aggregate metric values (SUM, COUNT, AVG) between sources."""
        discrepancies: list[Discrepancy] = []
        common_metrics = set(aggregates_a.keys()) & set(aggregates_b.keys())

        for metric in sorted(common_metrics):
            va = aggregates_a[metric]
            vb = aggregates_b[metric]
            if va == vb:
                continue

            denominator = max(abs(va), abs(vb), 1e-9)
            diff_pct = abs(va - vb) / denominator

            if diff_pct >= self.VALUE_DIFF_CRITICAL_THRESHOLD:
                severity = "critical"
            elif diff_pct >= self.VALUE_DIFF_WARNING_THRESHOLD:
                severity = "warning"
            else:
                severity = "info"

            discrepancies.append(
                Discrepancy(
                    discrepancy_type="value_mismatch",
                    severity=severity,
                    title=f"Value mismatch: {metric}",
                    description=(
                        f"{source_a_name}: {va:,.2f} vs "
                        f"{source_b_name}: {vb:,.2f} "
                        f"({diff_pct:.2%} difference)"
                    ),
                    source_a_name=source_a_name,
                    source_b_name=source_b_name,
                    source_a_value=va,
                    source_b_value=vb,
                    affected_metric=metric,
                    difference_pct=round(diff_pct * 100, 2),
                    likely_cause=self._guess_value_cause(metric, va, vb),
                    recommended_action=(
                        f"Investigate the '{metric}' difference between sources. "
                        f"Check aggregation logic, filters, or timing windows."
                    ),
                )
            )

        return discrepancies

    def reconcile_schemas(
        self,
        source_a_name: str,
        source_b_name: str,
        schema_a: dict[str, list[str]],
        schema_b: dict[str, list[str]],
    ) -> list[Discrepancy]:
        """Compare table schemas (column lists) between sources."""
        discrepancies: list[Discrepancy] = []
        common_tables = set(schema_a.keys()) & set(schema_b.keys())

        for table in sorted(common_tables):
            cols_a = set(schema_a.get(table) or [])
            cols_b = set(schema_b.get(table) or [])

            only_in_a = cols_a - cols_b
            only_in_b = cols_b - cols_a

            if only_in_a:
                discrepancies.append(
                    Discrepancy(
                        discrepancy_type="schema_diff",
                        severity="warning",
                        title=f"Extra columns in {source_a_name}: {table}",
                        description=(
                            f"Columns {sorted(only_in_a)} exist in "
                            f"{source_a_name}.{table} but not in "
                            f"{source_b_name}.{table}"
                        ),
                        source_a_name=source_a_name,
                        source_b_name=source_b_name,
                        source_a_value=sorted(only_in_a),
                        source_b_value=None,
                        affected_table=table,
                        likely_cause=("Schema migration may not have been applied to both sources"),
                        recommended_action=(f"Apply missing columns to {source_b_name}.{table}"),
                    )
                )

            if only_in_b:
                discrepancies.append(
                    Discrepancy(
                        discrepancy_type="schema_diff",
                        severity="warning",
                        title=f"Extra columns in {source_b_name}: {table}",
                        description=(
                            f"Columns {sorted(only_in_b)} exist in "
                            f"{source_b_name}.{table} but not in "
                            f"{source_a_name}.{table}"
                        ),
                        source_a_name=source_a_name,
                        source_b_name=source_b_name,
                        source_a_value=None,
                        source_b_value=sorted(only_in_b),
                        affected_table=table,
                        likely_cause=("Schema migration may not have been applied to both sources"),
                        recommended_action=(f"Apply missing columns to {source_a_name}.{table}"),
                    )
                )

        return discrepancies

    def reconcile_key_overlap(
        self,
        source_a_name: str,
        source_b_name: str,
        keys_a: set[str],
        keys_b: set[str],
        table_name: str,
        key_column: str,
    ) -> list[Discrepancy]:
        """Compare primary/unique key sets to find missing records."""
        discrepancies: list[Discrepancy] = []
        only_a = keys_a - keys_b
        only_b = keys_b - keys_a

        if only_a:
            pct = len(only_a) / max(len(keys_a), 1)
            severity = "critical" if pct > 0.05 else "warning"
            sample = sorted(only_a)[:5]
            discrepancies.append(
                Discrepancy(
                    discrepancy_type="missing_records",
                    severity=severity,
                    title=(
                        f"{len(only_a):,} records in {source_a_name} "
                        f"missing from {source_b_name}: {table_name}"
                    ),
                    description=(
                        f"{len(only_a):,} {key_column} values exist in "
                        f"{source_a_name}.{table_name} but not in "
                        f"{source_b_name}. Sample: {sample}"
                    ),
                    source_a_name=source_a_name,
                    source_b_name=source_b_name,
                    source_a_value=len(only_a),
                    source_b_value=0,
                    affected_table=table_name,
                    difference_pct=round(pct * 100, 2),
                    likely_cause=(
                        "Replication lag, failed ETL, or different data retention policies"
                    ),
                    recommended_action=(
                        f"Check sync pipeline for {table_name}. Verify replication status."
                    ),
                )
            )

        if only_b:
            pct = len(only_b) / max(len(keys_b), 1)
            severity = "critical" if pct > 0.05 else "warning"
            sample = sorted(only_b)[:5]
            discrepancies.append(
                Discrepancy(
                    discrepancy_type="missing_records",
                    severity=severity,
                    title=(
                        f"{len(only_b):,} records in {source_b_name} "
                        f"missing from {source_a_name}: {table_name}"
                    ),
                    description=(
                        f"{len(only_b):,} {key_column} values exist in "
                        f"{source_b_name}.{table_name} but not in "
                        f"{source_a_name}. Sample: {sample}"
                    ),
                    source_a_name=source_a_name,
                    source_b_name=source_b_name,
                    source_a_value=0,
                    source_b_value=len(only_b),
                    affected_table=table_name,
                    difference_pct=round(pct * 100, 2),
                    likely_cause=(
                        "Replication lag, failed ETL, or different data retention policies"
                    ),
                    recommended_action=(
                        f"Check sync pipeline for {table_name}. Verify replication status."
                    ),
                )
            )

        return discrepancies

    def build_report(
        self,
        source_a_name: str,
        source_b_name: str,
        source_a_conn_id: str,
        source_b_conn_id: str,
        all_discrepancies: list[Discrepancy],
        total_checks: int,
    ) -> ReconciliationReport:
        """Assemble a full reconciliation report."""
        status = "discrepancies_found" if all_discrepancies else "clean"

        sorted_disc = sorted(
            all_discrepancies,
            key=lambda d: (
                {"critical": 0, "warning": 1, "info": 2}.get(d.severity, 3),
                d.discrepancy_type,
            ),
        )

        report = ReconciliationReport(
            source_a_name=source_a_name,
            source_b_name=source_b_name,
            source_a_connection_id=source_a_conn_id,
            source_b_connection_id=source_b_conn_id,
            status=status,
            total_checks=total_checks,
            discrepancies=sorted_disc,
        )

        report.summary = self._build_summary(report)
        return report

    def _build_summary(self, report: ReconciliationReport) -> str:
        if report.status == "clean":
            return (
                f"All {report.total_checks} checks passed. "
                f"{report.source_a_name} and {report.source_b_name} "
                f"are in sync."
            )
        parts = [
            f"Found {len(report.discrepancies)} discrepancies "
            f"across {report.total_checks} checks between "
            f"{report.source_a_name} and {report.source_b_name}."
        ]
        if report.critical_count:
            parts.append(f"{report.critical_count} critical issue(s) require immediate attention.")
        if report.warning_count:
            parts.append(f"{report.warning_count} warning(s) to review.")
        return " ".join(parts)

    @staticmethod
    def _guess_count_cause(count_a: int, count_b: int, diff_pct: float) -> str:
        if diff_pct > 0.5:
            return (
                "Large count difference suggests one source is "
                "missing significant data (ETL failure or data loss)"
            )
        if count_a > count_b:
            return (
                "Source A has more rows — possible replication lag "
                "or incomplete migration to source B"
            )
        return "Source B has more rows — possible duplicate inserts or different retention policies"

    @staticmethod
    def _guess_value_cause(metric: str, val_a: float, val_b: float) -> str:
        metric_lower = metric.lower()
        if any(kw in metric_lower for kw in ("revenue", "amount", "total")):
            return (
                "Financial metric mismatch — check currency conversion, "
                "tax inclusion/exclusion, or refund handling"
            )
        if any(kw in metric_lower for kw in ("count", "users", "orders")):
            return (
                "Count metric mismatch — check deduplication logic or filter criteria differences"
            )
        return (
            "Value difference may be due to aggregation timing, "
            "filter logic, or data freshness differences"
        )
