"""Query-less Exploration Engine.

When the user says "What's wrong?" or "Explore my data", this engine
autonomously investigates by scanning existing insights, running anomaly
checks, detecting patterns, and compiling a structured investigation report.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Finding:
    """A single investigation finding."""

    category: str  # anomaly, opportunity, loss, reconciliation, trend, health
    severity: str  # critical, warning, info, positive
    title: str
    description: str
    evidence: str = ""
    recommended_action: str = ""
    confidence: float = 0.5
    source: str = ""  # insight_memory, anomaly_scan, live_analysis

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class InvestigationReport:
    """Structured report from autonomous exploration."""

    status: str  # issues_found, healthy, partial
    total_findings: int = 0
    critical_count: int = 0
    warning_count: int = 0
    positive_count: int = 0
    findings: list[Finding] = field(default_factory=list)
    summary: str = ""
    investigation_steps: list[str] = field(default_factory=list)
    data_coverage: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "total_findings": self.total_findings,
            "critical_count": self.critical_count,
            "warning_count": self.warning_count,
            "positive_count": self.positive_count,
            "findings": [f.to_dict() for f in self.findings],
            "summary": self.summary,
            "investigation_steps": self.investigation_steps,
            "data_coverage": self.data_coverage,
        }


class ExplorationEngine:
    """Compiles an investigation report from available data.

    Takes pre-gathered insights, anomaly reports, and metadata
    rather than connecting to databases directly.
    """

    def investigate(
        self,
        insights: list[dict[str, Any]],
        anomaly_reports: list[dict[str, Any]] | None = None,
        opportunity_data: list[dict[str, Any]] | None = None,
        loss_data: list[dict[str, Any]] | None = None,
        reconciliation_data: list[dict[str, Any]] | None = None,
        table_health: dict[str, Any] | None = None,
    ) -> InvestigationReport:
        """Run an autonomous investigation from available data."""
        findings: list[Finding] = []
        steps: list[str] = []

        steps.append("Scanning existing insights from Memory Layer")
        findings.extend(self._analyze_insights(insights))

        if anomaly_reports:
            steps.append("Analyzing anomaly intelligence reports")
            findings.extend(self._analyze_anomalies(anomaly_reports))

        if opportunity_data:
            steps.append("Checking for missed growth opportunities")
            findings.extend(self._analyze_opportunities(opportunity_data))

        if loss_data:
            steps.append("Scanning for revenue leaks and inefficiencies")
            findings.extend(self._analyze_losses(loss_data))

        if reconciliation_data:
            steps.append("Checking cross-source data consistency")
            findings.extend(self._analyze_reconciliation(reconciliation_data))

        if table_health:
            steps.append("Evaluating overall data health")
            findings.extend(self._analyze_health(table_health))

        if not findings:
            steps.append("No issues detected — data appears healthy")
            findings.append(
                Finding(
                    category="health",
                    severity="positive",
                    title="All clear",
                    description=(
                        "No significant issues detected across available "
                        "data sources and existing insights."
                    ),
                    confidence=0.6,
                    source="live_analysis",
                )
            )

        sorted_findings = sorted(
            findings,
            key=lambda f: (
                {"critical": 0, "warning": 1, "info": 2, "positive": 3}.get(f.severity, 4),
                -f.confidence,
            ),
        )

        critical = sum(1 for f in sorted_findings if f.severity == "critical")
        warning = sum(1 for f in sorted_findings if f.severity == "warning")
        positive = sum(1 for f in sorted_findings if f.severity == "positive")

        if critical > 0:
            status = "issues_found"
        elif warning > 0:
            status = "issues_found"
        elif positive > 0:
            status = "healthy"
        else:
            status = "partial"

        report = InvestigationReport(
            status=status,
            total_findings=len(sorted_findings),
            critical_count=critical,
            warning_count=warning,
            positive_count=positive,
            findings=sorted_findings,
            investigation_steps=steps,
            data_coverage={
                "insights_scanned": len(insights),
                "anomaly_reports": len(anomaly_reports or []),
                "opportunities_checked": len(opportunity_data or []),
                "losses_checked": len(loss_data or []),
                "reconciliation_checks": len(reconciliation_data or []),
            },
        )
        report.summary = self._build_summary(report)
        return report

    def _analyze_insights(self, insights: list[dict[str, Any]]) -> list[Finding]:
        findings: list[Finding] = []
        for ins in insights:
            severity = ins.get("severity", "info")
            if severity not in ("critical", "warning"):
                continue
            findings.append(
                Finding(
                    category=ins.get("insight_type", "general"),
                    severity=severity,
                    title=ins.get("title", "Untitled insight"),
                    description=ins.get("description", ""),
                    recommended_action=ins.get("recommended_action", ""),
                    confidence=float(ins.get("confidence", 0.5)),
                    source="insight_memory",
                )
            )
        return findings

    def _analyze_anomalies(self, anomalies: list[dict[str, Any]]) -> list[Finding]:
        findings: list[Finding] = []
        for anomaly in anomalies:
            severity = anomaly.get("severity", "info")
            if severity not in ("critical", "warning"):
                continue
            findings.append(
                Finding(
                    category="anomaly",
                    severity=severity,
                    title=anomaly.get("title", "Anomaly detected"),
                    description=anomaly.get("description", ""),
                    evidence=anomaly.get("root_cause", ""),
                    recommended_action=anomaly.get("recommended_action", ""),
                    confidence=float(anomaly.get("confidence", 0.6)),
                    source="anomaly_scan",
                )
            )
        return findings

    def _analyze_opportunities(self, opportunities: list[dict[str, Any]]) -> list[Finding]:
        findings: list[Finding] = []
        for opp in opportunities:
            impact = float(opp.get("impact_estimate_pct", 0))
            if impact < 5:
                continue
            findings.append(
                Finding(
                    category="opportunity",
                    severity="info",
                    title=opp.get("title", "Growth opportunity"),
                    description=opp.get("description", ""),
                    evidence=(f"Estimated impact: {impact:.0f}%" if impact else ""),
                    recommended_action=opp.get("recommended_action", ""),
                    confidence=float(opp.get("confidence", 0.5)),
                    source="live_analysis",
                )
            )
        return findings

    def _analyze_losses(self, losses: list[dict[str, Any]]) -> list[Finding]:
        findings: list[Finding] = []
        for loss in losses:
            severity = loss.get("severity", "warning")
            findings.append(
                Finding(
                    category="loss",
                    severity=severity if severity in ("critical", "warning") else "warning",
                    title=loss.get("title", "Revenue leak detected"),
                    description=loss.get("description", ""),
                    evidence=loss.get("evidence", ""),
                    recommended_action=loss.get("recommended_action", ""),
                    confidence=float(loss.get("confidence", 0.6)),
                    source="live_analysis",
                )
            )
        return findings

    def _analyze_reconciliation(self, discrepancies: list[dict[str, Any]]) -> list[Finding]:
        findings: list[Finding] = []
        for disc in discrepancies:
            severity = disc.get("severity", "info")
            if severity not in ("critical", "warning"):
                continue
            findings.append(
                Finding(
                    category="reconciliation",
                    severity=severity,
                    title=disc.get("title", "Data discrepancy"),
                    description=disc.get("description", ""),
                    evidence=disc.get("likely_cause", ""),
                    recommended_action=disc.get("recommended_action", ""),
                    confidence=0.8 if severity == "critical" else 0.65,
                    source="live_analysis",
                )
            )
        return findings

    def _analyze_health(self, health: dict[str, Any]) -> list[Finding]:
        findings: list[Finding] = []
        empty_tables = health.get("empty_tables", 0)
        orphan_tables = health.get("orphan_tables", 0)
        total_tables = health.get("total_tables", 0)

        if empty_tables > 0 and total_tables > 0:
            pct = empty_tables / total_tables
            if pct > 0.3:
                findings.append(
                    Finding(
                        category="health",
                        severity="warning",
                        title=f"{empty_tables} empty tables ({pct:.0%} of total)",
                        description=(
                            f"Found {empty_tables} empty tables out of "
                            f"{total_tables}. This may indicate migration "
                            f"issues or unused schemas."
                        ),
                        confidence=0.7,
                        source="live_analysis",
                    )
                )

        if orphan_tables > 0:
            findings.append(
                Finding(
                    category="health",
                    severity="info",
                    title=f"{orphan_tables} orphan tables detected",
                    description=(
                        f"Found {orphan_tables} tables without foreign key "
                        f"relationships. These may be utility tables or "
                        f"missing from the schema design."
                    ),
                    confidence=0.5,
                    source="live_analysis",
                )
            )

        return findings

    def _build_summary(self, report: InvestigationReport) -> str:
        if report.status == "healthy":
            return (
                f"Investigation complete: scanned "
                f"{report.data_coverage.get('insights_scanned', 0)} insights "
                f"across {len(report.investigation_steps)} checks. "
                f"No significant issues found."
            )
        parts = [
            f"Investigation found {report.total_findings} finding(s) "
            f"across {len(report.investigation_steps)} checks."
        ]
        if report.critical_count:
            parts.append(f"{report.critical_count} critical issue(s) need immediate attention.")
        if report.warning_count:
            parts.append(f"{report.warning_count} warning(s) to review.")
        if report.positive_count:
            parts.append(f"{report.positive_count} positive indicator(s).")
        return " ".join(parts)
