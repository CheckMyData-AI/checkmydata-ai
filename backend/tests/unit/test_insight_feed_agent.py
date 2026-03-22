"""Tests for the Insight Feed Agent."""

from app.agents.insight_feed_agent import InsightFeedAgent


class TestInsightFeedAgent:
    def test_map_insight_type_trend(self):
        assert InsightFeedAgent._map_insight_type("trend_up") == "trend"
        assert InsightFeedAgent._map_insight_type("trend_down") == "trend"

    def test_map_insight_type_outlier(self):
        assert InsightFeedAgent._map_insight_type("outlier") == "anomaly"

    def test_map_insight_type_concentration(self):
        assert InsightFeedAgent._map_insight_type("concentration") == "pattern"

    def test_map_insight_type_summary(self):
        assert InsightFeedAgent._map_insight_type("summary") == "observation"

    def test_map_insight_type_unknown(self):
        assert InsightFeedAgent._map_insight_type("something_else") == "observation"

    def test_map_severity_outlier_high_confidence(self):
        assert InsightFeedAgent._map_severity("outlier", 0.8) == "warning"

    def test_map_severity_outlier_low_confidence(self):
        assert InsightFeedAgent._map_severity("outlier", 0.5) == "info"

    def test_map_severity_trend_high_confidence(self):
        assert InsightFeedAgent._map_severity("trend_up", 0.85) == "warning"

    def test_map_severity_default(self):
        assert InsightFeedAgent._map_severity("summary", 0.9) == "info"
