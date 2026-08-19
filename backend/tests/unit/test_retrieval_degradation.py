from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from app.knowledge.retrieval_degradation import emit_retrieval_degraded


async def test_emit_records_metric_and_event():
    tracker = MagicMock()
    tracker.emit = AsyncMock()
    with patch("app.knowledge.retrieval_degradation.get_metrics_collector") as gmc:
        collector = MagicMock()
        gmc.return_value = collector
        await emit_retrieval_degraded(tracker, "wf1", leg="bm25", reason="snapshot_missing")
    collector.record_retrieval_degraded.assert_called_once_with(
        leg="bm25", reason="snapshot_missing"
    )
    assert tracker.emit.await_count == 1


async def test_event_carries_leg_and_reason_as_structured_extra():
    """AUD-0819-03: the client must be able to name what was missing.

    The signal used to reach the metrics and the event stream and stop there —
    nothing rendered it, so an answer retrieved from one leg of two looked exactly
    like an answer retrieved from both. In production that is the normal case
    rather than the exception, because the BM25 snapshot lives on the dyno's
    ephemeral disk (F-KNOW-07). Prose in `detail` is not a contract; `extra` is.
    """
    from unittest.mock import AsyncMock, MagicMock, patch

    tracker = MagicMock()
    tracker.emit = AsyncMock()
    with patch("app.knowledge.retrieval_degradation.get_metrics_collector"):
        await emit_retrieval_degraded(tracker, "wf-x", leg="bm25", reason="empty_result")

    kwargs = tracker.emit.await_args.kwargs
    assert kwargs["leg"] == "bm25"
    assert kwargs["reason"] == "empty_result"
    args = tracker.emit.await_args.args
    assert args[1] == "retrieval_degraded"
