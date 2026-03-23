"""Lightweight application metrics endpoint (no external dependencies)."""

import re
import time
from collections import defaultdict
from threading import Lock

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user

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
async def get_metrics(_user: dict = Depends(get_current_user)):
    """Return application metrics. Requires authentication."""
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

    return {
        "active_workflows": len(active_workflows),
        "request_stats": path_stats,
        "uptime_seconds": round(time.monotonic(), 1),
    }
