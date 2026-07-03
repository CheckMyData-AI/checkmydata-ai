"""Characterization tests for OrchestratorAgent._record_request_metrics (W0 / ORCH-A04)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.agents.orchestrator import OrchestratorAgent


def test_record_request_metrics_forwards_to_collector():
    orch = OrchestratorAgent.__new__(OrchestratorAgent)  # no __init__ side effects
    with patch("app.core.metrics.get_metrics_collector") as gmc:
        collector = MagicMock()
        gmc.return_value = collector
        orch._record_request_metrics(
            route="unified",
            complexity="moderate",
            response_type="sql_result",
            sql_calls=3,
            iterations=2,
            wall_clock_seconds=1.5,
            error=False,
        )
    assert collector.record_request.called
    rm = collector.record_request.call_args.args[0]
    assert rm.route == "unified"
    assert rm.complexity == "moderate"
    assert rm.response_type == "sql_result"
    assert rm.sql_calls == 3
    assert rm.error is False


def test_record_request_metrics_never_raises():
    orch = OrchestratorAgent.__new__(OrchestratorAgent)
    with patch("app.core.metrics.get_metrics_collector", side_effect=RuntimeError("boom")):
        # must swallow — metrics never break a request
        orch._record_request_metrics(
            route="unified",
            complexity="x",
            response_type="text",
            sql_calls=0,
            iterations=1,
            wall_clock_seconds=0.0,
            error=True,
        )


def test_record_request_metrics_passes_all_fields():
    """All kwargs land in the RequestMetrics row forwarded to the collector."""
    orch = OrchestratorAgent.__new__(OrchestratorAgent)
    with patch("app.core.metrics.get_metrics_collector") as gmc:
        collector = MagicMock()
        gmc.return_value = collector
        orch._record_request_metrics(
            route="direct",
            complexity="simple",
            response_type="text",
            sql_calls=0,
            iterations=1,
            wall_clock_seconds=0.42,
            error=True,
        )
    rm = collector.record_request.call_args.args[0]
    assert rm.route == "direct"
    assert rm.complexity == "simple"
    assert rm.response_type == "text"
    assert rm.sql_calls == 0
    assert rm.iterations == 1
    assert abs(rm.wall_clock_seconds - 0.42) < 1e-9
    assert rm.error is True
