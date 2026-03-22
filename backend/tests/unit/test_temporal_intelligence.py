"""Unit tests for TemporalIntelligenceService."""

from __future__ import annotations

import math
import unittest

from app.core.temporal_intelligence import TemporalIntelligenceService


class TestTemporalIntelligence(unittest.TestCase):
    def setUp(self) -> None:
        self.svc = TemporalIntelligenceService()

    def test_upward_trend(self) -> None:
        values = [float(i) for i in range(30)]
        trend = self.svc.detect_trend(values)
        assert trend.direction == "up"
        assert trend.slope > 0
        assert trend.strength > 0.9

    def test_downward_trend(self) -> None:
        values = [100.0 - i for i in range(30)]
        trend = self.svc.detect_trend(values)
        assert trend.direction == "down"
        assert trend.slope < 0
        assert trend.strength > 0.9

    def test_flat_trend(self) -> None:
        values = [50.0] * 30
        trend = self.svc.detect_trend(values)
        assert trend.direction == "flat"

    def test_insufficient_data_for_trend(self) -> None:
        values = [1.0, 2.0]
        trend = self.svc.detect_trend(values)
        assert trend.direction == "flat"
        assert "Insufficient" in trend.description

    def test_volatile_series(self) -> None:
        import random

        random.seed(42)
        values = [random.uniform(0, 100) for _ in range(30)]
        trend = self.svc.detect_trend(values)
        assert trend.strength < 0.5

    def test_seasonality_weekly(self) -> None:
        values = []
        for i in range(56):
            base = 100 + i * 0.1
            seasonal = 20 * math.sin(2 * math.pi * i / 7)
            values.append(base + seasonal)
        result = self.svc.detect_seasonality(values)
        assert result.detected
        assert result.period == 7

    def test_no_seasonality(self) -> None:
        values = [float(i) for i in range(30)]
        result = self.svc.detect_seasonality(values)
        assert not result.detected

    def test_insufficient_data_for_seasonality(self) -> None:
        values = [1.0] * 10
        result = self.svc.detect_seasonality(values)
        assert not result.detected
        assert "Insufficient" in result.description

    def test_temporal_anomalies_detected(self) -> None:
        values = [10.0] * 20
        values[10] = 100.0
        anomalies = self.svc.detect_temporal_anomalies(values)
        assert len(anomalies) >= 1
        assert anomalies[0]["position"] == 10
        assert anomalies[0]["direction"] == "spike"

    def test_no_anomalies_in_clean_data(self) -> None:
        values = [float(i) for i in range(30)]
        trend = self.svc.detect_trend(values)
        anomalies = self.svc.detect_temporal_anomalies(values, trend)
        assert len(anomalies) == 0

    def test_lag_detection_positive(self) -> None:
        a = [math.sin(2 * math.pi * i / 10) for i in range(50)]
        b = [math.sin(2 * math.pi * (i - 3) / 10) for i in range(50)]
        result = self.svc.detect_lag(a, b, max_lag=10)
        assert result.lag_periods != 0
        assert result.correlation > 0.5

    def test_lag_detection_synchronized(self) -> None:
        values = [float(i) for i in range(30)]
        result = self.svc.detect_lag(values, values)
        assert result.lag_periods == 0
        assert result.correlation > 0.9

    def test_lag_insufficient_data(self) -> None:
        result = self.svc.detect_lag([1.0], [2.0])
        assert result.correlation == 0.0
        assert "Insufficient" in result.description

    def test_full_analysis(self) -> None:
        values = [100 + i * 2.0 for i in range(30)]
        report = self.svc.analyze_series(values, "revenue", "day")
        assert report.metric_name == "revenue"
        assert report.total_points == 30
        assert report.trend is not None
        assert report.trend.direction == "up"

    def test_full_analysis_with_seasonality(self) -> None:
        values = []
        for i in range(56):
            base = 100 + i * 0.5
            seasonal = 15 * math.sin(2 * math.pi * i / 7)
            values.append(base + seasonal)
        report = self.svc.analyze_series(values, "traffic", "day")
        assert report.seasonality is not None
        assert report.seasonality.detected

    def test_full_analysis_insufficient_data(self) -> None:
        values = [1.0, 2.0]
        report = self.svc.analyze_series(values, "x")
        assert "Insufficient" in report.context_note

    def test_report_to_dict(self) -> None:
        values = [float(i) for i in range(30)]
        report = self.svc.analyze_series(values)
        d = report.to_dict()
        assert "trend" in d
        assert "seasonality" in d
        assert "recent_anomalies" in d
        assert "context_note" in d

    def test_trend_result_to_dict(self) -> None:
        values = [float(i) for i in range(30)]
        trend = self.svc.detect_trend(values)
        d = trend.to_dict()
        assert "direction" in d
        assert "slope" in d
        assert "strength" in d

    def test_lag_result_to_dict(self) -> None:
        values = [float(i) for i in range(30)]
        result = self.svc.detect_lag(values, values)
        d = result.to_dict()
        assert "lag_periods" in d
        assert "correlation" in d

    def test_empty_values(self) -> None:
        report = self.svc.analyze_series([])
        assert report.total_points == 0
        assert "Insufficient" in report.context_note

    def test_constant_series_lag(self) -> None:
        a = [5.0] * 30
        b = [5.0] * 30
        result = self.svc.detect_lag(a, b)
        assert result.correlation == 0.0

    def test_period_name_day(self) -> None:
        assert self.svc._period_name(7, "day") == "weekly"
        assert self.svc._period_name(30, "day") == "monthly"
        assert self.svc._period_name(14, "day") == "bi-weekly"

    def test_period_name_month(self) -> None:
        assert self.svc._period_name(12, "month") == "yearly"
        assert self.svc._period_name(4, "month") == "quarterly"


if __name__ == "__main__":
    unittest.main()
