"""Unit tests for InsightGenerator."""

import pytest

from app.core.insight_generator import InsightGenerator


class TestAnalyzeMinimumRows:
    def test_returns_empty_for_fewer_than_3_rows(self):
        rows = [[1, 2], [3, 4]]
        assert InsightGenerator.analyze(rows, ["a", "b"]) == []

    def test_returns_empty_for_empty_columns(self):
        rows = [[1], [2], [3]]
        assert InsightGenerator.analyze(rows, []) == []


class TestDetectTrends:
    def test_upward_trend_detected(self):
        rows = [[100, "2024-01"], [110, "2024-02"], [130, "2024-03"], [150, "2024-04"]]
        insights = InsightGenerator.analyze(rows, ["revenue", "month"])
        trend_insights = [i for i in insights if i["type"] == "trend_up"]
        assert len(trend_insights) == 1
        assert "increased" in trend_insights[0]["description"]

    def test_downward_trend_detected(self):
        rows = [[200, "2024-01"], [160, "2024-02"], [120, "2024-03"], [80, "2024-04"]]
        insights = InsightGenerator.analyze(rows, ["revenue", "date"])
        trend_insights = [i for i in insights if i["type"] == "trend_down"]
        assert len(trend_insights) == 1
        assert "decreased" in trend_insights[0]["description"]

    def test_no_trend_below_threshold(self):
        rows = [[100, "2024-01"], [102, "2024-02"], [101, "2024-03"], [103, "2024-04"]]
        insights = InsightGenerator.analyze(rows, ["revenue", "month"])
        trend_insights = [i for i in insights if i["type"].startswith("trend_")]
        assert len(trend_insights) == 0

    def test_no_trend_without_temporal_column(self):
        rows = [[100, "a"], [200, "b"], [300, "c"]]
        insights = InsightGenerator.analyze(rows, ["revenue", "category"])
        trend_insights = [i for i in insights if i["type"].startswith("trend_")]
        assert len(trend_insights) == 0


class TestDetectOutliers:
    def test_outlier_detected(self):
        rows = [[10], [12], [11], [13], [11], [100]]
        insights = InsightGenerator.analyze(rows, ["value"])
        outlier_insights = [i for i in insights if i["type"] == "outlier"]
        assert len(outlier_insights) >= 1
        assert "100" in outlier_insights[0]["description"]

    def test_no_outlier_in_uniform_data(self):
        rows = [[10], [11], [10], [11], [10]]
        insights = InsightGenerator.analyze(rows, ["value"])
        outlier_insights = [i for i in insights if i["type"] == "outlier"]
        assert len(outlier_insights) == 0


class TestDetectConcentration:
    def test_high_concentration_detected(self):
        rows = [[100], [90], [80], [5], [4], [3], [2], [1]]
        insights = InsightGenerator.analyze(rows, ["sales"])
        conc_insights = [i for i in insights if i["type"] == "concentration"]
        assert len(conc_insights) == 1
        assert "Top 3" in conc_insights[0]["description"]

    def test_no_concentration_when_spread_is_even(self):
        rows = [[10], [10], [10], [10], [10], [10], [10], [10], [10], [10]]
        insights = InsightGenerator.analyze(rows, ["value"])
        conc_insights = [i for i in insights if i["type"] == "concentration"]
        assert len(conc_insights) == 0


class TestSummarizeTotals:
    def test_single_row_summary(self):
        rows = [[42]]
        result = InsightGenerator._summarize_totals(rows, ["total_count"])
        assert len(result) == 1
        assert result[0]["type"] == "summary"
        assert "42" in result[0]["title"]

    def test_multi_row_no_summary(self):
        rows = [[10], [20], [30]]
        result = InsightGenerator._summarize_totals(rows, ["value"])
        assert len(result) == 0


class TestDictInput:
    def test_accepts_dict_rows(self):
        rows = [
            {"revenue": 100, "month": "2024-01"},
            {"revenue": 200, "month": "2024-02"},
            {"revenue": 400, "month": "2024-03"},
        ]
        insights = InsightGenerator.analyze(rows, ["revenue", "month"])
        assert len(insights) > 0
