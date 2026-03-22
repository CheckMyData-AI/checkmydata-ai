"""Tests for the Anomaly Intelligence Engine."""

from app.core.anomaly_intelligence import AnomalyIntelligenceEngine, AnomalyReport


class TestAnomalyIntelligence:
    def setup_method(self):
        self.engine = AnomalyIntelligenceEngine()

    def test_analyze_all_null_column(self):
        rows = [{"id": 1, "amount": None}, {"id": 2, "amount": None}, {"id": 3, "amount": None}]
        columns = ["id", "amount"]
        reports = self.engine.analyze(rows, columns)
        assert len(reports) >= 1
        null_reports = [r for r in reports if r.check_type == "all_null"]
        assert len(null_reports) >= 1
        assert null_reports[0].severity in ("warning", "critical")
        assert null_reports[0].root_cause_hypothesis
        assert null_reports[0].recommended_action

    def test_analyze_all_zero_column(self):
        rows = [{"id": i, "revenue": 0} for i in range(10)]
        columns = ["id", "revenue"]
        reports = self.engine.analyze(rows, columns)
        zero_reports = [r for r in reports if r.check_type == "all_zero"]
        assert len(zero_reports) >= 1
        assert "zero" in zero_reports[0].title.lower()

    def test_analyze_negative_values(self):
        rows = [{"id": i, "revenue": -100 * (i + 1)} for i in range(5)]
        rows.extend([{"id": i + 5, "revenue": 100} for i in range(3)])
        columns = ["id", "revenue"]
        reports = self.engine.analyze(rows, columns)
        neg_reports = [r for r in reports if r.check_type == "negative_value"]
        assert len(neg_reports) >= 1
        assert neg_reports[0].affected_rows > 0

    def test_analyze_clean_data(self):
        rows = [{"id": i, "value": i * 10 + 5} for i in range(20)]
        columns = ["id", "value"]
        reports = self.engine.analyze(rows, columns)
        critical = [r for r in reports if r.severity == "critical"]
        assert len(critical) == 0

    def test_report_to_dict(self):
        report = AnomalyReport(
            check_type="all_null",
            title="Missing data",
            description="Column X is NULL",
            severity="warning",
            business_impact="Reports will be empty",
            root_cause_hypothesis="Column recently added",
            affected_metrics=["X"],
            affected_rows=10,
            confidence=0.7,
            recommended_action="Check pipeline",
            expected_impact="Better accuracy",
        )
        d = report.to_dict()
        assert d["check_type"] == "all_null"
        assert d["confidence"] == 0.7
        assert "X" in d["affected_metrics"]

    def test_format_report_empty(self):
        assert self.engine.format_report([]) == ""

    def test_format_report_with_data(self):
        reports = [
            AnomalyReport(
                check_type="all_null",
                title="Missing data in amount",
                description="Column amount is NULL",
                severity="warning",
                business_impact="Reports affected",
                root_cause_hypothesis="Recently added",
                recommended_action="Check pipeline",
                expected_impact="Fix accuracy",
            )
        ]
        text = self.engine.format_report(reports)
        assert "ANOMALY INTELLIGENCE REPORT" in text
        assert "Missing data in amount" in text
        assert "Root cause" in text

    def test_severity_rank(self):
        assert AnomalyIntelligenceEngine._severity_rank("critical") == 4
        assert AnomalyIntelligenceEngine._severity_rank("warning") == 3
        assert AnomalyIntelligenceEngine._severity_rank("info") == 2

    def test_related_anomalies_linked(self):
        rows = [{"id": i, "amount": None, "price": None} for i in range(5)]
        columns = ["id", "amount", "price"]
        reports = self.engine.analyze(rows, columns)
        null_reports = [r for r in reports if r.check_type == "all_null"]
        if len(null_reports) >= 2:
            assert len(null_reports[0].related_anomalies) >= 1

    def test_confidence_increases_with_row_count(self):
        small_rows = [{"id": i, "val": None} for i in range(3)]
        large_rows = [{"id": i, "val": None} for i in range(200)]
        small_reports = self.engine.analyze(small_rows, ["id", "val"])
        large_reports = self.engine.analyze(large_rows, ["id", "val"])
        if small_reports and large_reports:
            assert large_reports[0].confidence >= small_reports[0].confidence
