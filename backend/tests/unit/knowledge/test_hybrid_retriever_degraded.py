"""Unit tests for RET-R4: retrieval_degraded signal in HybridRetriever.

Verifies that `emit_retrieval_degraded` is called exactly when one leg is empty
and the other is not, and is NOT called when both legs have hits or both are empty.

Stubs both BM25 and Chroma via mocks so tests are independent of tokenisation
or snapshot availability.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.knowledge.bm25_index import BM25Index
from app.knowledge.hybrid_retriever import HybridRetriever

# ---------------------------------------------------------------------------
# Helpers / stubs
# ---------------------------------------------------------------------------

_CHROMA_HITS: list[dict[str, Any]] = [
    {"id": "c1", "document": "analyze query func", "distance": 0.1, "metadata": {"src": "a.py"}},
]

_BM25_HITS: list[dict[str, Any]] = [
    {"id": "b1", "document": "analyze query function body", "metadata": {"src": "a.py"}},
]


class _StubVector:
    """Drop-in VectorStore substitute returning canned results."""

    def __init__(self, results: list[dict[str, Any]] | None = None) -> None:
        self._results = results or []

    def query(self, project_id: str, query_text: str, n_results: int, where=None):  # noqa: ARG002
        return list(self._results)


def _make_bm25(results: list[dict[str, Any]]) -> MagicMock:
    """Return a BM25Index mock that returns `results` from .query()."""
    mock = MagicMock(spec=BM25Index)
    mock.query = MagicMock(return_value=list(results))
    return mock


# ---------------------------------------------------------------------------
# RET-R4: degradation signal tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bm25_empty_chroma_hits_emits_degraded_bm25_leg():
    """When BM25 returns [] but Chroma has hits → emit leg='bm25'."""
    bm25 = _make_bm25([])
    chroma = _StubVector(results=_CHROMA_HITS)
    retr = HybridRetriever(bm25=bm25, vector_store=chroma)

    with patch(
        "app.knowledge.hybrid_retriever.emit_retrieval_degraded",
        new_callable=AsyncMock,
    ) as mock_emit:
        out = await retr.query("p", "analyze query")

    # Chroma results should still come through
    assert len(out) > 0
    assert any(r.doc_id == "c1" for r in out)

    mock_emit.assert_awaited_once()
    _, kwargs = mock_emit.call_args
    assert kwargs["leg"] == "bm25"
    assert kwargs["reason"]  # non-empty reason string


@pytest.mark.asyncio
async def test_chroma_empty_bm25_hits_emits_degraded_dense_leg():
    """When Chroma returns [] but BM25 has hits → emit leg='dense'."""
    bm25 = _make_bm25(_BM25_HITS)
    chroma = _StubVector(results=[])
    retr = HybridRetriever(bm25=bm25, vector_store=chroma)

    with patch(
        "app.knowledge.hybrid_retriever.emit_retrieval_degraded",
        new_callable=AsyncMock,
    ) as mock_emit:
        out = await retr.query("p", "analyze query")

    # BM25 results should still come through
    assert len(out) > 0
    assert any(r.doc_id == "b1" for r in out)

    mock_emit.assert_awaited_once()
    _, kwargs = mock_emit.call_args
    assert kwargs["leg"] == "dense"
    assert kwargs["reason"]


@pytest.mark.asyncio
async def test_both_legs_have_hits_no_emit():
    """When both BM25 and Chroma return hits → no degraded event."""
    bm25 = _make_bm25(_BM25_HITS)
    chroma = _StubVector(results=_CHROMA_HITS)
    retr = HybridRetriever(bm25=bm25, vector_store=chroma)

    with patch(
        "app.knowledge.hybrid_retriever.emit_retrieval_degraded",
        new_callable=AsyncMock,
    ) as mock_emit:
        out = await retr.query("p", "analyze query")

    assert len(out) > 0
    mock_emit.assert_not_awaited()


@pytest.mark.asyncio
async def test_both_legs_empty_no_emit():
    """When both legs return [] → no degraded event (degenerate/no-results case)."""
    bm25 = _make_bm25([])
    chroma = _StubVector(results=[])
    retr = HybridRetriever(bm25=bm25, vector_store=chroma)

    with patch(
        "app.knowledge.hybrid_retriever.emit_retrieval_degraded",
        new_callable=AsyncMock,
    ) as mock_emit:
        out = await retr.query("p", "analyze query")

    assert out == []
    mock_emit.assert_not_awaited()


@pytest.mark.asyncio
async def test_tracker_and_workflow_id_forwarded_to_emit():
    """tracker and wf_id positional args are forwarded correctly to emit_retrieval_degraded."""
    bm25 = _make_bm25([])
    chroma = _StubVector(results=_CHROMA_HITS)
    tracker = MagicMock()
    wf_id = "wf-test-123"
    retr = HybridRetriever(
        bm25=bm25,
        vector_store=chroma,
        tracker=tracker,
        workflow_id=wf_id,
    )

    with patch(
        "app.knowledge.hybrid_retriever.emit_retrieval_degraded",
        new_callable=AsyncMock,
    ) as mock_emit:
        await retr.query("p", "analyze query")

    mock_emit.assert_awaited_once()
    args, kwargs = mock_emit.call_args
    # First two positional args are tracker, workflow_id
    assert args[0] is tracker
    assert args[1] == wf_id
    assert kwargs["leg"] == "bm25"


@pytest.mark.asyncio
async def test_no_tracker_still_fires_metric():
    """When no tracker is injected, emit is still called with tracker=None (metric fires)."""
    bm25 = _make_bm25([])
    chroma = _StubVector(results=_CHROMA_HITS)
    # No tracker / workflow_id passed (defaults)
    retr = HybridRetriever(bm25=bm25, vector_store=chroma)

    with patch(
        "app.knowledge.hybrid_retriever.emit_retrieval_degraded",
        new_callable=AsyncMock,
    ) as mock_emit:
        await retr.query("p", "analyze query")

    mock_emit.assert_awaited_once()
    args, _ = mock_emit.call_args
    # First positional arg (tracker) must be None when not injected
    assert args[0] is None
