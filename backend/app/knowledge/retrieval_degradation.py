"""RET-R4 degradation signal scaffold (contract C-E; wired into HybridRetriever in Wave 2)."""

from __future__ import annotations

import logging
from typing import Any

from app.core.metrics import get_metrics_collector

logger = logging.getLogger(__name__)


async def emit_retrieval_degraded(tracker: Any, workflow_id: str, *, leg: str, reason: str) -> None:
    """Emit a WorkflowTracker 'retrieval_degraded' event + increment the metric.

    Best-effort: a broken tracker or collector must never break retrieval.
    """
    try:
        get_metrics_collector().record_retrieval_degraded(leg=leg, reason=reason)
    except Exception:
        logger.debug("retrieval_degraded metric failed", exc_info=True)
    try:
        if tracker is not None:
            await tracker.emit(
                workflow_id,
                "retrieval_degraded",
                "in_progress",
                f"retrieval leg '{leg}' degraded: {reason}",
            )
    except Exception:
        logger.debug("retrieval_degraded event emit failed", exc_info=True)
