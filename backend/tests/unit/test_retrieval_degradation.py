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
