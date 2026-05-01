"""Lightweight application metrics endpoint (no external dependencies)."""

import re
import time
from collections import defaultdict
from threading import Lock

from fastapi import APIRouter, Depends, Response

from app.api.deps import require_admin
from app.core.metrics import get_metrics_collector

router = APIRouter()

_metrics_lock = Lock()
_request_counts: dict[str, int] = defaultdict(int)
_request_latencies: dict[str, list[float]] = defaultdict(list)
_error_counts: dict[str, int] = defaultdict(int)
_MAX_PATHS = 500

_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


def _normalize_path(path: str) -> str:
    return _UUID_RE.sub(":id", path)


def record_request(path: str, latency_ms: float, is_error: bool = False) -> None:
    path = _normalize_path(path)
    with _metrics_lock:
        if path not in _request_counts and len(_request_counts) >= _MAX_PATHS:
            return
        _request_counts[path] += 1
        _request_latencies[path].append(latency_ms)
        if len(_request_latencies[path]) > 1000:
            _request_latencies[path] = _request_latencies[path][-500:]
        if is_error:
            _error_counts[path] += 1


@router.get("/metrics")
async def get_metrics(_user: dict = Depends(require_admin)):
    """Return application metrics. Admin-only."""
    from app.core.workflow_tracker import tracker

    active_workflows = tracker.get_active()

    with _metrics_lock:
        path_stats = {}
        for path, count in _request_counts.items():
            latencies = _request_latencies.get(path, [])
            avg_latency = sum(latencies) / len(latencies) if latencies else 0
            path_stats[path] = {
                "count": count,
                "errors": _error_counts.get(path, 0),
                "avg_latency_ms": round(avg_latency, 1),
            }

    orchestrator_recent = [
        {
            "route": m.route,
            "complexity": m.complexity,
            "response_type": m.response_type,
            "wall_clock_seconds": round(m.wall_clock_seconds, 2),
            "iterations": m.iterations,
            "sql_calls": m.sql_calls,
            "replan_count": m.replan_count,
            "retry_count": m.retry_count,
            "error": m.error,
        }
        for m in get_metrics_collector().snapshot_recent(50)
    ]

    return {
        "active_workflows": len(active_workflows),
        "request_stats": path_stats,
        "uptime_seconds": round(time.monotonic(), 1),
        "orchestrator_recent": orchestrator_recent,
    }


@router.get("/metrics/prometheus", response_class=Response)
async def get_prometheus(_user: dict = Depends(require_admin)) -> Response:
    """Render orchestrator counters in Prometheus text-exposition format. Admin-only."""
    body = get_metrics_collector().render_prometheus()
    return Response(content=body, media_type="text/plain; version=0.0.4")
