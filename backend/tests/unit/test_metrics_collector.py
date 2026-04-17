"""Tests for :mod:`app.core.metrics`."""

from __future__ import annotations

from app.core.metrics import (
    MetricsCollector,
    RequestMetrics,
    get_metrics_collector,
)


class TestMetricsCollector:
    def test_record_increments_counters(self):
        c = MetricsCollector()
        c.record_request(
            RequestMetrics(
                route="unified",
                complexity="medium",
                response_type="sql_result",
                wall_clock_seconds=1.5,
                iterations=3,
                sql_calls=1,
                tokens_prompt=100,
                tokens_completion=50,
            )
        )
        body = c.render_prometheus()
        assert "orchestrator_requests_total" in body
        assert "orchestrator_wall_clock_seconds_sum" in body
        assert 'route="unified"' in body
        assert 'response_type="sql_result"' in body

    def test_history_capped(self):
        c = MetricsCollector(history=2)
        for i in range(5):
            c.record_request(RequestMetrics(route=f"r{i}"))
        recent = c.snapshot_recent()
        assert len(recent) == 2
        assert [m.route for m in recent] == ["r3", "r4"]

    def test_singleton(self):
        a = get_metrics_collector()
        b = get_metrics_collector()
        assert a is b

    def test_error_label(self):
        c = MetricsCollector()
        c.record_request(RequestMetrics(error=True))
        body = c.render_prometheus()
        assert 'error="true"' in body
