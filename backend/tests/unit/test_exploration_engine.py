"""Unit tests for ExplorationEngine."""

from __future__ import annotations

import unittest

from app.core.exploration_engine import ExplorationEngine, Finding


class TestExplorationEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = ExplorationEngine()

    def test_empty_investigation_returns_healthy(self) -> None:
        report = self.engine.investigate(insights=[])
        assert report.status == "healthy"
        assert report.positive_count == 1
        assert "All clear" in report.findings[0].title

    def test_critical_insight_found(self) -> None:
        insights = [
            {
                "insight_type": "anomaly",
                "severity": "critical",
                "title": "Revenue dropped 40%",
                "description": "Major drop in daily revenue",
                "confidence": 0.9,
                "recommended_action": "Investigate payment pipeline",
            }
        ]
        report = self.engine.investigate(insights=insights)
        assert report.status == "issues_found"
        assert report.critical_count == 1
        assert report.findings[0].severity == "critical"
        assert report.findings[0].source == "insight_memory"

    def test_warning_insight_found(self) -> None:
        insights = [
            {
                "insight_type": "anomaly",
                "severity": "warning",
                "title": "Slight dip",
                "description": "Minor change",
                "confidence": 0.6,
            }
        ]
        report = self.engine.investigate(insights=insights)
        assert report.status == "issues_found"
        assert report.warning_count == 1

    def test_info_insights_skipped(self) -> None:
        insights = [
            {
                "insight_type": "general",
                "severity": "info",
                "title": "No issue",
                "description": "Just informational",
                "confidence": 0.3,
            }
        ]
        report = self.engine.investigate(insights=insights)
        assert report.status == "healthy"
        assert report.critical_count == 0
        assert report.warning_count == 0

    def test_anomaly_reports_analyzed(self) -> None:
        anomalies = [
            {
                "severity": "critical",
                "title": "Null spike in orders table",
                "description": "50% of rows have null email",
                "root_cause": "Migration error",
                "recommended_action": "Backfill data",
                "confidence": 0.85,
            }
        ]
        report = self.engine.investigate(insights=[], anomaly_reports=anomalies)
        assert report.status == "issues_found"
        assert report.critical_count == 1
        assert report.findings[0].category == "anomaly"

    def test_opportunities_with_high_impact(self) -> None:
        opps = [
            {
                "title": "Brazil segment underserved",
                "description": "2x conversion but low traffic",
                "impact_estimate_pct": 15.0,
                "confidence": 0.7,
            }
        ]
        report = self.engine.investigate(insights=[], opportunity_data=opps)
        assert report.total_findings >= 1
        opp_findings = [f for f in report.findings if f.category == "opportunity"]
        assert len(opp_findings) == 1

    def test_opportunities_low_impact_filtered(self) -> None:
        opps = [
            {
                "title": "Tiny improvement",
                "description": "Marginal gain",
                "impact_estimate_pct": 2.0,
                "confidence": 0.3,
            }
        ]
        report = self.engine.investigate(insights=[], opportunity_data=opps)
        opp_findings = [f for f in report.findings if f.category == "opportunity"]
        assert len(opp_findings) == 0

    def test_losses_analyzed(self) -> None:
        losses = [
            {
                "severity": "critical",
                "title": "$12k/mo lost at checkout",
                "description": "Checkout step 3 drops 40%",
                "confidence": 0.8,
            }
        ]
        report = self.engine.investigate(insights=[], loss_data=losses)
        assert report.critical_count == 1

    def test_reconciliation_discrepancies(self) -> None:
        discs = [
            {
                "severity": "warning",
                "title": "Row count diff in users",
                "description": "DB has 1000, Stripe has 950",
                "likely_cause": "Sync lag",
                "recommended_action": "Check replication",
            }
        ]
        report = self.engine.investigate(insights=[], reconciliation_data=discs)
        assert report.warning_count == 1
        assert report.findings[0].category == "reconciliation"

    def test_health_empty_tables_warning(self) -> None:
        health = {
            "total_tables": 10,
            "active_tables": 6,
            "empty_tables": 4,
            "orphan_tables": 2,
        }
        report = self.engine.investigate(insights=[], table_health=health)
        health_findings = [f for f in report.findings if f.category == "health"]
        assert len(health_findings) >= 1
        assert any("empty tables" in f.title for f in health_findings)

    def test_combined_investigation(self) -> None:
        insights = [
            {
                "insight_type": "anomaly",
                "severity": "critical",
                "title": "Revenue crash",
                "description": "Big problem",
                "confidence": 0.9,
            }
        ]
        losses = [
            {
                "severity": "warning",
                "title": "Checkout leak",
                "description": "Drop at step 3",
                "confidence": 0.7,
            }
        ]
        report = self.engine.investigate(insights=insights, loss_data=losses)
        assert report.total_findings == 2
        assert report.critical_count == 1
        assert report.warning_count == 1
        assert report.findings[0].severity == "critical"

    def test_findings_sorted_by_severity(self) -> None:
        insights = [
            {
                "insight_type": "a",
                "severity": "warning",
                "title": "W1",
                "description": "",
                "confidence": 0.5,
            },
            {
                "insight_type": "b",
                "severity": "critical",
                "title": "C1",
                "description": "",
                "confidence": 0.9,
            },
        ]
        report = self.engine.investigate(insights=insights)
        assert report.findings[0].severity == "critical"
        assert report.findings[1].severity == "warning"

    def test_investigation_steps_tracked(self) -> None:
        report = self.engine.investigate(
            insights=[],
            anomaly_reports=[{"severity": "info"}],
            opportunity_data=[{"impact_estimate_pct": 1}],
            loss_data=[{"severity": "info"}],
            reconciliation_data=[{"severity": "info"}],
            table_health={"total_tables": 5},
        )
        assert len(report.investigation_steps) >= 5

    def test_report_to_dict(self) -> None:
        report = self.engine.investigate(insights=[])
        d = report.to_dict()
        assert "status" in d
        assert "findings" in d
        assert "investigation_steps" in d
        assert "data_coverage" in d

    def test_finding_to_dict(self) -> None:
        f = Finding(
            category="anomaly",
            severity="critical",
            title="Test",
            description="Desc",
            confidence=0.9,
        )
        d = f.to_dict()
        assert d["category"] == "anomaly"
        assert d["confidence"] == 0.9

    def test_summary_healthy(self) -> None:
        report = self.engine.investigate(insights=[])
        assert "No significant issues" in report.summary

    def test_summary_issues_found(self) -> None:
        insights = [
            {
                "insight_type": "a",
                "severity": "critical",
                "title": "X",
                "description": "",
                "confidence": 0.9,
            }
        ]
        report = self.engine.investigate(insights=insights)
        assert "critical" in report.summary.lower()

    def test_data_coverage_tracked(self) -> None:
        report = self.engine.investigate(
            insights=[
                {
                    "severity": "info",
                    "title": "x",
                    "description": "y",
                    "confidence": 0.1,
                    "insight_type": "g",
                }
            ],
            anomaly_reports=[{"severity": "info"}],
        )
        assert report.data_coverage["insights_scanned"] == 1
        assert report.data_coverage["anomaly_reports"] == 1


if __name__ == "__main__":
    unittest.main()
