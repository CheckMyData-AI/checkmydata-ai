"""Tests for W0 MetricsCollector counter helpers (C-G / RET-R4 / SYNC-L1)."""

from __future__ import annotations

from app.core.metrics import MetricsCollector


def test_retrieval_degraded_counter():
    """Test record_retrieval_degraded records a counter with leg and reason labels."""
    c = MetricsCollector()
    c.record_retrieval_degraded(leg="bm25", reason="snapshot_missing")
    snap = c.snapshot_counters("retrieval_degraded_total")
    assert snap["retrieval_degraded_total"] == 1
    prom = c.render_prometheus()
    assert "retrieval_degraded_total" in prom
    assert 'leg="bm25"' in prom and 'reason="snapshot_missing"' in prom


def test_datagate_block_counter():
    """Test record_datagate_block records a counter with optional check label."""
    c = MetricsCollector()
    c.record_datagate_block(check="percent")
    assert c.snapshot_counters("datagate_block_total")["datagate_block_total"] == 1


def test_filter_guard_degrade_counter():
    """Test record_filter_guard_degrade records a counter (no labels)."""
    c = MetricsCollector()
    c.record_filter_guard_degrade()
    c.record_filter_guard_degrade()
    assert c.snapshot_counters("filter_guard_degrade_total")["filter_guard_degrade_total"] == 2
