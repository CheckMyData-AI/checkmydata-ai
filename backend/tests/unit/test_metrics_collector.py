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

    def test_inc_records_counter_with_labels(self):
        """M6: generic ``inc`` API tuples kwargs into Prometheus labels."""
        c = MetricsCollector()
        c.inc("code_graph_symbols_total", 42, project="abc12345")
        c.inc("code_graph_symbols_total", 8, project="abc12345")
        body = c.render_prometheus()
        assert 'code_graph_symbols_total{project="abc12345"} 50' in body

    def test_inc_ignores_empty_name(self):
        c = MetricsCollector()
        c.inc("", 1)  # should not raise
        assert "code_graph_symbols_total" not in c.render_prometheus()

    def test_add_records_sum_and_count(self):
        c = MetricsCollector()
        c.add("code_graph_build_duration_seconds", 1.5, project="p1")
        c.add("code_graph_build_duration_seconds", 2.5, project="p1")
        body = c.render_prometheus()
        assert 'code_graph_build_duration_seconds{project="p1"} 4.0' in body
        assert 'code_graph_build_duration_seconds_count{project="p1"} 2' in body
