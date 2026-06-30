"""T5: diagnostics self-observability counter on MetricsCollector."""

from __future__ import annotations

from app.core.metrics import MetricsCollector, record_diagnostics_persist_failure


def test_counter_increments_and_surfaces():
    c = MetricsCollector()
    assert c.snapshot_counters(prefix="diagnostics_").get("diagnostics_persist_failures") is None
    c.record_diagnostics_persist_failure()
    c.record_diagnostics_persist_failure()
    snap = c.snapshot_counters(prefix="diagnostics_")
    assert snap["diagnostics_persist_failures"] == 2


def test_module_helper_is_best_effort():
    # Must never raise even if the singleton is in a weird state.
    record_diagnostics_persist_failure()
