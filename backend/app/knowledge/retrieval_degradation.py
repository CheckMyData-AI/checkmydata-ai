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
            # AUD-0819-03: `leg` and `reason` ride as structured `extra` so the
            # client can name what was missing instead of re-parsing the prose.
            # Until this, the signal reached the metrics and the event stream and
            # stopped there — nothing rendered it, so an answer retrieved from one
            # leg of two looked exactly like an answer retrieved from both. In
            # production that is the normal case, not the exception: the BM25
            # snapshot lives on the dyno's ephemeral disk (F-KNOW-07).
            await tracker.emit(
                workflow_id,
                "retrieval_degraded",
                "in_progress",
                f"retrieval leg '{leg}' degraded: {reason}",
                leg=leg,
                reason=reason,
            )
    except Exception:
        logger.debug("retrieval_degraded event emit failed", exc_info=True)
