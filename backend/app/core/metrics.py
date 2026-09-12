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
    # ORCH-A03 (C-G): router signal — number of sub-queries the router estimated.
    estimated_queries: int = 0
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

    # ------------------------------------------------------------------
    # M6: generic counter/gauge API for the code-intelligence pipeline.
    # Keeps the public surface small — callers don't pass label dicts,
    # they pass plain (name, **labels) and the collector tuples them.
    # ------------------------------------------------------------------

    def inc(self, name: str, amount: int = 1, **labels: str) -> None:
        """Increment a counter by ``amount``. Safe to call from any thread."""
        if not name:
            return
        try:
            label_tuple = tuple(sorted(labels.items()))
            with self._lock:
                self._counters[(name, label_tuple)] += int(amount)
        except Exception:
            logger.debug("MetricsCollector.inc failed", exc_info=True)

    def add(self, name: str, value: float, **labels: str) -> None:
        """Record a float observation (used for durations, sizes, etc.)."""
        if not name:
            return
        try:
            label_tuple = tuple(sorted(labels.items()))
            with self._lock:
                self._sums[(name, label_tuple)] += float(value)
                self._counters[(f"{name}_count", label_tuple)] += 1
        except Exception:
            logger.debug("MetricsCollector.add failed", exc_info=True)

    def record_diagnostics_persist_failure(self) -> None:
        """Count a failure of the diagnostics persistence layer itself.

        Self-observability: the system that records failures must not fail
        silently. Surfaced via ``/api/metrics`` under ``diagnostics``.
        """
        self.inc("diagnostics_persist_failures")

    def record_retrieval_degraded(self, *, leg: str, reason: str) -> None:
        """A retrieval leg (bm25/dense) returned 0 while another had hits (RET-R4)."""
        self.inc("retrieval_degraded_total", leg=leg, reason=reason)

    def record_datagate_block(self, *, check: str = "") -> None:
        """A DataGate hard check blocked an impossible value (C-G / DATA-06)."""
        if check:
            self.inc("datagate_block_total", check=check)
        else:
            self.inc("datagate_block_total")

    def record_daily_sync_near_ceiling(self) -> None:
        """A nightly sync finished within `BUDGET_WARNING_FRACTION` of its own timeout.

        Measured on production: the longest COMPLETED run took 7 214.9 s against a 7 200 s
        budget. ARQ's timeout does not warn on the way up, it cancels — so without this
        the first symptom of a repository outgrowing the budget is a night that simply did
        not sync, with the run before it looking exactly like a success.
        """
        self.inc("daily_sync_budget_near_ceiling_total")

    def record_db_index_sample_budget_exhausted(self) -> None:
        """`fetch_samples` hit its wall-clock budget and indexed the rest of the tables
        without column statistics (T04).

        Worth a counter rather than only a log line: this is a silent quality reduction
        in what the agent later reasons over, and it is the number that says whether
        `db_index_fetch_samples_budget_seconds` is set too low for a given customer.
        """
        self.inc("db_index_sample_budget_exhausted_total")

    def record_index_over_quota(self) -> None:
        """A project's index passed what its plan sells (T08 / D5 option a).

        A warning, never a refusal — so this counter is the only place the breach becomes
        a number an operator can trend. `plans.max_index_bytes` has been sold since
        2026-08-31 with nothing comparing it to anything.
        """
        self.inc("index_over_quota_total")

    def record_filter_guard_degrade(self) -> None:
        """The required-filter guard degraded to a warning instead of hard-failing (SYNC-L1)."""
        self.inc("filter_guard_degrade_total")

    def snapshot_counters(self, prefix: str | None = None) -> dict[str, int]:
        """Return a name -> summed-value snapshot of integer counters.

        Labels are flattened by summing across them. Used by the JSON
        ``/api/metrics`` endpoint so consumers don't have to parse the
        Prometheus exposition just to read a top-level count. Pass a
        ``prefix`` (e.g. ``"code_graph_"``) to filter; otherwise returns
        every counter. Non-mutating.
        """
        out: dict[str, int] = {}
        with self._lock:
            counters = dict(self._counters)
        for (name, _labels), value in counters.items():
            if prefix and not name.startswith(prefix):
                continue
            out[name] = out.get(name, 0) + int(value)
        return out

    def snapshot_labelled(self) -> dict[tuple[str, tuple[tuple[str, str], ...]], float]:
        """Every counter and sum this process holds, LABELS INTACT (OPS-03).

        Distinct from `snapshot_counters` above, which flattens labels by summing
        across them for the JSON endpoint: a counter stripped of its labels answers a
        different question, and the shared store has to republish what it was given.

        The store publishes from this rather than reaching into the two dicts, so the
        lock stays inside the class and a new backing store changes one method.
        Counters and sums are merged because Prometheus does not distinguish them here
        — `render_prometheus` emits both as `counter` — and a name collides in neither.
        """
        with self._lock:
            merged: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {
                key: float(value) for key, value in self._counters.items()
            }
            for key, value in self._sums.items():
                merged[key] = merged.get(key, 0.0) + float(value)
        return merged

    def render_prometheus_from(
        self, published: list[tuple[str, tuple[tuple[str, str], ...], float]]
    ) -> str:
        """Render values gathered elsewhere — the shared store's sum across processes.

        Same formatting as `render_prometheus`, which is the point: the page must not
        change shape depending on whether a Redis is configured.
        """
        return self._render(
            {(name, labels): value for name, labels, value in published},
            {},
        )

    def render_prometheus(self) -> str:
        """Format current counters as Prometheus text exposition."""
        with self._lock:
            counters = dict(self._counters)
            sums = dict(self._sums)
        return self._render(counters, sums)

    def _render(self, counters: dict, sums: dict) -> str:
        lines: list[str] = []
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


def record_diagnostics_persist_failure() -> None:
    """Best-effort module helper for the diagnostics persistence except-blocks."""
    try:
        get_metrics_collector().record_diagnostics_persist_failure()
    except Exception:
        logger.debug("record_diagnostics_persist_failure failed", exc_info=True)
