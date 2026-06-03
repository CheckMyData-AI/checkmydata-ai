"""Unit tests for :class:`HybridRetriever` (M3).

Uses an in-memory :class:`BM25Index` and a stub vector store so we exercise
the fusion logic in isolation from ChromaDB.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.knowledge.bm25_index import BM25Index
from app.knowledge.hybrid_retriever import HybridRetriever


class _StubVector:
    """Drop-in :class:`VectorStore` substitute returning canned results."""

    def __init__(self, results: list[dict[str, Any]] | Exception | None = None) -> None:
        self._results = results

    def query(self, project_id: str, query_text: str, n_results: int, where=None):  # noqa: ARG002
        if isinstance(self._results, Exception):
            raise self._results
        if self._results is None:
            return []
        return self._results


@pytest.fixture
def bm25(tmp_path) -> BM25Index:
    idx = BM25Index(tmp_path / "bm25")
    docs = [
        ("c1", "analyze_query function with rich docstring about queries", {"source_path": "a.py"}),
        ("c2", "UserService class managing users", {"source_path": "b.py"}),
        ("c3", "validate email format", {"source_path": "c.py"}),
    ]
    idx.build("p", indexed_sha="sha", documents=docs)
    return idx


# ---------------------------------------------------------------------------
# RRF fusion semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chroma_max_distance_filters_low_relevance(bm25):
    """Dense hits beyond the distance threshold are dropped before fusion."""
    chroma = _StubVector(
        results=[
            {
                "id": "c2",
                "document": "UserService class",
                "distance": 0.2,  # within threshold
                "metadata": {"source_path": "b.py"},
            },
            {
                "id": "zz",
                "document": "irrelevant semantic match",
                "distance": 0.95,  # beyond threshold -> dropped
                "metadata": {"source_path": "z.py"},
            },
        ]
    )
    retr = HybridRetriever(bm25=bm25, vector_store=chroma, rrf_k=60, chroma_max_distance=0.8)
    out = await retr.query("p", "users service")
    ids = {r.doc_id for r in out}
    # The far hit must not appear via the dense leg.
    far = next((r for r in out if r.doc_id == "zz"), None)
    assert far is None or far.chroma_rank is None
    assert "zz" not in ids


@pytest.mark.asyncio
async def test_rrf_combines_overlapping_results(bm25):
    chroma = _StubVector(
        results=[
            {
                "id": "c1",
                "document": "analyze_query function",
                "distance": 0.1,
                "metadata": {"source_path": "a.py"},
            },
            {
                "id": "c4",
                "document": "totally unrelated text",
                "distance": 0.2,
                "metadata": {"source_path": "z.py"},
            },
        ]
    )
    retr = HybridRetriever(bm25=bm25, vector_store=chroma, rrf_k=60)
    out = await retr.query("p", "analyze query")
    # Both retrievers should rank c1 high; it must appear first with both ranks set.
    assert out[0].doc_id == "c1"
    assert out[0].bm25_rank is not None
    assert out[0].chroma_rank is not None
    # c4 was only in chroma; should still appear with only chroma_rank.
    c4 = next(r for r in out if r.doc_id == "c4")
    assert c4.bm25_rank is None
    assert c4.chroma_rank == 2


@pytest.mark.asyncio
async def test_rrf_score_is_sum_of_reciprocals(bm25):
    chroma = _StubVector(
        results=[
            {"id": "c2", "document": "UserService", "distance": 0.0, "metadata": {}},
        ]
    )
    retr = HybridRetriever(bm25=bm25, vector_store=chroma, rrf_k=10)
    out = await retr.query("p", "user service")
    target = next((r for r in out if r.doc_id == "c2"), None)
    assert target is not None
    # c2 is rank 1 in bm25 (for "user service") and rank 1 in chroma.
    expected = 1.0 / (10 + 1) + 1.0 / (10 + 1)
    assert abs(target.rrf_score - expected) < 1e-6


@pytest.mark.asyncio
async def test_min_score_filter(bm25):
    chroma = _StubVector(results=[])
    retr = HybridRetriever(bm25=bm25, vector_store=chroma, rrf_k=60, min_score=1.0)
    # Even though BM25 will return hits, the min_score=1.0 filter wipes them
    # out (max possible RRF from a single retriever is ~1/61).
    out = await retr.query("p", "analyze query")
    assert out == []


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chroma_error_falls_back_to_bm25_only(bm25):
    chroma = _StubVector(results=RuntimeError("boom"))
    retr = HybridRetriever(bm25=bm25, vector_store=chroma)
    out = await retr.query("p", "analyze query")
    assert any(r.doc_id == "c1" for r in out)
    # Chroma errored, so chroma_rank stays None for everything.
    assert all(r.chroma_rank is None for r in out)


@pytest.mark.asyncio
async def test_bm25_error_falls_back_to_chroma_only(tmp_path):
    failing_bm25 = MagicMock(spec=BM25Index)
    failing_bm25.query = MagicMock(side_effect=RuntimeError("boom"))
    chroma = _StubVector(
        results=[
            {"id": "x", "document": "only chroma", "distance": 0.1, "metadata": {}},
        ]
    )
    retr = HybridRetriever(bm25=failing_bm25, vector_store=chroma)
    out = await retr.query("p", "query")
    assert len(out) == 1
    assert out[0].doc_id == "x"
    assert out[0].bm25_rank is None


@pytest.mark.asyncio
async def test_both_retrievers_fail_returns_empty(tmp_path):
    failing_bm25 = MagicMock(spec=BM25Index)
    failing_bm25.query = MagicMock(side_effect=RuntimeError("boom"))
    chroma = _StubVector(results=RuntimeError("boom"))
    retr = HybridRetriever(bm25=failing_bm25, vector_store=chroma)
    out = await retr.query("p", "query")
    assert out == []


@pytest.mark.asyncio
async def test_timeout_in_one_leg_does_not_block_other(bm25):
    class _SlowVector:
        def query(self, *_a, **_kw):
            import time

            time.sleep(2.0)
            return []

    retr = HybridRetriever(
        bm25=bm25,
        vector_store=_SlowVector(),
        rrf_k=60,
        retriever_timeout_sec=0.2,
    )
    # Should return quickly (well under 2s) thanks to the timeout.
    start = asyncio.get_event_loop().time()
    out = await retr.query("p", "analyze")
    elapsed = asyncio.get_event_loop().time() - start
    assert elapsed < 1.0
    # BM25 results survive.
    assert any(r.doc_id == "c1" for r in out)


@pytest.mark.asyncio
async def test_empty_query_returns_empty(bm25):
    chroma = _StubVector(results=[])
    retr = HybridRetriever(bm25=bm25, vector_store=chroma)
    assert await retr.query("p", "") == []
    assert await retr.query("p", "   ") == []
