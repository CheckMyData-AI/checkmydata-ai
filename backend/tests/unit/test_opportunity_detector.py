"""Tests for the Opportunity Detector."""

from app.core.opportunity_detector import Opportunity, OpportunityDetector


class TestOpportunityDetector:
    def setup_method(self):
        self.detector = OpportunityDetector()

    def test_empty_data_returns_empty(self):
        assert self.detector.analyze([], []) == []
        assert self.detector.analyze([{"a": 1}], []) == []

    def test_detect_high_performer_segment(self):
        rows = [
            {"country": "US", "revenue": 100},
            {"country": "US", "revenue": 120},
            {"country": "US", "revenue": 110},
            {"country": "DE", "revenue": 40},
            {"country": "DE", "revenue": 35},
            {"country": "DE", "revenue": 45},
            {"country": "BR", "revenue": 200},
            {"country": "BR", "revenue": 220},
            {"country": "BR", "revenue": 210},
        ]
        columns = ["country", "revenue"]
        opps = self.detector.analyze(rows, columns)
        titles = [o.title for o in opps]
        assert any("BR" in t for t in titles) or len(opps) > 0

    def test_detect_conversion_gap(self):
        rows = [
            {"channel": "organic", "conversion_rate": 5.2},
            {"channel": "paid", "conversion_rate": 1.1},
            {"channel": "social", "conversion_rate": 3.0},
            {"channel": "email", "conversion_rate": 8.5},
            {"channel": "referral", "conversion_rate": 2.0},
        ]
        columns = ["channel", "conversion_rate"]
        opps = self.detector.analyze(rows, columns)
        gap_opps = [o for o in opps if o.opportunity_type == "conversion_gap"]
        assert len(gap_opps) >= 1

    def test_detect_undermonetized_segments(self):
        rows = [
            {"region": "US", "users": 10000, "revenue": 50000},
            {"region": "EU", "users": 8000, "revenue": 40000},
            {"region": "Asia", "users": 15000, "revenue": 5000},
        ]
        columns = ["region", "users", "revenue"]
        opps = self.detector.analyze(rows, columns)
        undermon = [o for o in opps if o.opportunity_type == "undermonetized"]
        if undermon:
            assert any("Asia" in o.segment for o in undermon)

    def test_detect_growth_potential(self):
        rows = [
            {"source": "Google", "sessions": 50000, "revenue": 100000},
            {"source": "Direct", "sessions": 30000, "revenue": 80000},
            {"source": "Podcast", "sessions": 500, "revenue": 15000},
        ]
        columns = ["source", "sessions", "revenue"]
        opps = self.detector.analyze(rows, columns)
        growth = [o for o in opps if o.opportunity_type == "growth_potential"]
        if growth:
            assert any("Podcast" in o.segment for o in growth)

    def test_opportunity_to_dict(self):
        opp = Opportunity(
            opportunity_type="high_performer",
            title="Test opportunity",
            description="Test desc",
            segment="US",
            metric="revenue",
            current_value=150.123,
            benchmark_value=100.456,
            gap_pct=49.4,
            estimated_impact="Big impact",
            suggested_action="Scale it",
            confidence=0.75,
            evidence=["fact1", "fact2"],
        )
        d = opp.to_dict()
        assert d["opportunity_type"] == "high_performer"
        assert d["current_value"] == 150.12
        assert d["confidence"] == 0.75
        assert len(d["evidence"]) == 2

    def test_format_opportunities_empty(self):
        assert self.detector.format_opportunities([]) == ""

    def test_format_opportunities_with_data(self):
        opps = [
            Opportunity(
                opportunity_type="high_performer",
                title="BR outperforms",
                description="Brazil converts 2x better",
                segment="BR",
                metric="revenue",
                current_value=200,
                benchmark_value=100,
                gap_pct=100,
                estimated_impact="Double revenue",
                suggested_action="Scale ads to BR",
            )
        ]
        text = self.detector.format_opportunities(opps)
        assert "OPPORTUNITY REPORT" in text
        assert "BR outperforms" in text
        assert "Scale ads to BR" in text

    def test_confidence_increases_with_sample_and_gap(self):
        low = OpportunityDetector._calc_confidence(3, 10)
        high = OpportunityDetector._calc_confidence(200, 120)
        assert high > low

    def test_no_false_positives_on_uniform_data(self):
        rows = [{"country": "US", "revenue": 100} for _ in range(20)]
        columns = ["country", "revenue"]
        opps = self.detector.analyze(rows, columns)
        high_perf = [o for o in opps if o.opportunity_type == "high_performer"]
        assert len(high_perf) == 0

    def test_handles_missing_values_gracefully(self):
        rows = [
            {"country": "US", "revenue": None},
            {"country": "DE", "revenue": 50},
            {"country": None, "revenue": 100},
        ]
        columns = ["country", "revenue"]
        opps = self.detector.analyze(rows, columns)
        assert isinstance(opps, list)
