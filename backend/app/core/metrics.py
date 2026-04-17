"""Lightweight per-request metrics collector for orchestrator observability.

Records counters and histograms in-process so we can answer questions like:

- Distribution of ``response_type`` over the last N requests.
- 95th-percentile wall-clock per route (``direct`` / ``complex`` / ``unified``).
- Average ``replan_count`` and ``retry_count`` per pipeline run.

The ``record_request`` API is a single non-blocking call from the orchestrator
at the end of every request. Counters are exposed via :func:`render_prometheus`
which formats them in Prometheus text-exposition format so a future
``/metrics`` endpoint can scrape them. We deliberately keep the implementation
dependency-free (no ``prometheus_client``) to avoid pulling extra packages
into the runtime; if/when we add Prometheus, swap the backing store and keep
the public API the same.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RequestMetrics:
    """One row recorded by :meth:`MetricsCollector.record_request`."""

    route: str = "unknown"
    complexity: str = "unknown"
    response_type: str = "unknown"
    replan_count: int = 0
    retry_count: int = 0
    sql_calls: int = 0
    iterations: int = 0
    tokens_prompt: int = 0
    tokens_completion: int = 0
    wall_clock_seconds: float = 0.0
    error: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


class MetricsCollector:
    """Thread-safe in-memory counter/histogram store with Prometheus export."""

    def __init__(self, *, history: int = 1000) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], int] = defaultdict(int)
        self._sums: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._history: deque[RequestMetrics] = deque(maxlen=history)

    def record_request(self, metrics: RequestMetrics) -> None:
        """Update counters and store the row for percentile reporting."""
        try:
            labels: tuple[tuple[str, str], ...] = (
                ("route", metrics.route),
                ("complexity", metrics.complexity),
                ("response_type", metrics.response_type),
                ("error", "true" if metrics.error else "false"),
            )
            with self._lock:
                self._counters[("orchestrator_requests_total", labels)] += 1
                self._sums[("orchestrator_wall_clock_seconds_sum", labels)] += (
                    metrics.wall_clock_seconds
                )
                self._counters[("orchestrator_wall_clock_seconds_count", labels)] += 1
                self._counters[("orchestrator_replans_total", labels)] += max(
                    0, metrics.replan_count
                )
                self._counters[("orchestrator_retries_total", labels)] += max(
                    0, metrics.retry_count
                )
                self._counters[("orchestrator_sql_calls_total", labels)] += max(
                    0, metrics.sql_calls
                )
                self._counters[("orchestrator_tokens_prompt_total", labels)] += max(
                    0, metrics.tokens_prompt
                )
                self._counters[("orchestrator_tokens_completion_total", labels)] += max(
                    0, metrics.tokens_completion
                )
                self._history.append(metrics)
        except Exception:  # never break a request because of metrics
            logger.debug("MetricsCollector.record_request failed", exc_info=True)

    def snapshot_recent(self, limit: int = 100) -> list[RequestMetrics]:
        """Return the most recent ``limit`` request rows for debugging."""
        with self._lock:
            return list(self._history)[-limit:]

    def render_prometheus(self) -> str:
        """Format current counters as Prometheus text exposition."""
        lines: list[str] = []
        with self._lock:
            counters = dict(self._counters)
            sums = dict(self._sums)
        seen_metrics: set[str] = set()

        def _emit(name: str, value: float, labels: tuple[tuple[str, str], ...]) -> None:
            if name not in seen_metrics:
                lines.append(f"# TYPE {name} counter")
                seen_metrics.add(name)
            label_str = ",".join(f'{k}="{_escape(v)}"' for k, v in labels)
            if label_str:
                lines.append(f"{name}{{{label_str}}} {value}")
            else:
                lines.append(f"{name} {value}")

        for (name, labels), int_value in counters.items():
            _emit(name, float(int_value), labels)
        for (name, labels), float_value in sums.items():
            _emit(name, float_value, labels)
        return "\n".join(lines) + "\n"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


_collector: MetricsCollector | None = None


def get_metrics_collector() -> MetricsCollector:
    """Process-wide singleton accessor."""
    global _collector
    if _collector is None:
        _collector = MetricsCollector()
    return _collector
