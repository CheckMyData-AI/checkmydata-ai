"""Tests for the Loss Detector."""

from app.core.loss_detector import LossDetector, LossReport


class TestLossDetector:
    def setup_method(self):
        self.detector = LossDetector()

    def test_empty_data_returns_empty(self):
        assert self.detector.analyze([], []) == []
        assert self.detector.analyze([{"a": 1}], []) == []

    def test_detect_funnel_drop(self):
        rows = [
            {"step": "visit", "users": 10000},
            {"step": "signup", "users": 3000},
            {"step": "activate", "users": 1000},
            {"step": "purchase", "users": 200},
        ]
        columns = ["step", "users"]
        losses = self.detector.analyze(rows, columns)
        funnel = [x for x in losses if x.loss_type == "funnel_drop"]
        assert len(funnel) >= 1
        assert any("visit" in x.title or "signup" in x.title for x in funnel)

    def test_detect_spend_inefficiency(self):
        rows = [
            {"channel": "Google", "spend": 10000, "revenue": 50000},
            {"channel": "Facebook", "spend": 8000, "revenue": 40000},
            {"channel": "TikTok", "spend": 5000, "revenue": 500},
        ]
        columns = ["channel", "spend", "revenue"]
        losses = self.detector.analyze(rows, columns)
        inefficient = [x for x in losses if x.loss_type == "spend_inefficiency"]
        assert len(inefficient) >= 1
        assert any("TikTok" in x.title for x in inefficient)

    def test_detect_revenue_regression(self):
        rows = [
            {"month": "Jan", "revenue": 100000},
            {"month": "Feb", "revenue": 95000},
            {"month": "Mar", "revenue": 90000},
            {"month": "Apr", "revenue": 60000},
            {"month": "May", "revenue": 55000},
            {"month": "Jun", "revenue": 50000},
        ]
        columns = ["month", "revenue"]
        losses = self.detector.analyze(rows, columns)
        regression = [x for x in losses if x.loss_type == "revenue_regression"]
        assert len(regression) >= 1

    def test_detect_high_churn_segments(self):
        rows = [
            {"plan": "basic", "churn_rate": 5},
            {"plan": "pro", "churn_rate": 3},
            {"plan": "enterprise", "churn_rate": 1},
            {"plan": "trial", "churn_rate": 25},
        ]
        columns = ["plan", "churn_rate"]
        losses = self.detector.analyze(rows, columns)
        churn = [x for x in losses if x.loss_type == "high_churn"]
        assert len(churn) >= 1
        assert any("trial" in x.title for x in churn)

    def test_loss_report_to_dict(self):
        report = LossReport(
            loss_type="funnel_drop",
            title="Checkout drop",
            description="50% drop at checkout",
            metric="users",
            current_value=500,
            expected_value=1000,
            loss_amount=500,
            loss_pct=50.0,
            estimated_monthly_impact="~500 users lost",
            suggested_fix="Simplify checkout",
            confidence=0.75,
            evidence=["fact1"],
        )
        d = report.to_dict()
        assert d["loss_type"] == "funnel_drop"
        assert d["loss_pct"] == 50.0
        assert d["confidence"] == 0.75

    def test_format_losses_empty(self):
        assert self.detector.format_losses([]) == ""

    def test_format_losses_with_data(self):
        losses = [
            LossReport(
                loss_type="funnel_drop",
                title="Signup to activation drop",
                description="70% drop",
                metric="users",
                current_value=300,
                expected_value=1000,
                loss_amount=700,
                loss_pct=70.0,
                estimated_monthly_impact="~700 users lost",
                suggested_fix="Fix activation flow",
            )
        ]
        text = self.detector.format_losses(losses)
        assert "LOSS REPORT" in text
        assert "Signup to activation drop" in text

    def test_no_false_positives_stable_data(self):
        rows = [{"month": str(i), "revenue": 10000} for i in range(6)]
        columns = ["month", "revenue"]
        losses = self.detector.analyze(rows, columns)
        regression = [x for x in losses if x.loss_type == "revenue_regression"]
        assert len(regression) == 0

    def test_confidence_increases_with_data(self):
        low = LossDetector._calc_confidence(3, 10)
        high = LossDetector._calc_confidence(200, 60)
        assert high > low

    def test_handles_missing_values(self):
        rows = [
            {"step": "A", "users": None},
            {"step": "B", "users": 100},
        ]
        columns = ["step", "users"]
        losses = self.detector.analyze(rows, columns)
        assert isinstance(losses, list)
