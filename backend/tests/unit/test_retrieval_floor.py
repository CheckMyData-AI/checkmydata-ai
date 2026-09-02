"""TDD gate for RET-R5: tightened relevance floor (Wave 2 T10).

Verifies that:
  - ``chroma_max_distance=0.45`` drops noisy hits (distance 0.60) and keeps
    relevant ones (distance 0.30).
  - ``config.rag_relevance_threshold`` is set to the tightened value (sim floor
    ≥ 0.55) and the rank-30 tail cut-off is in place as ``hybrid_max_rank``.

``hybrid_min_score`` used to be asserted here at 0.03, "above rank-30 RRF". It
was above every single-leg contribution too (1/61 = 0.0164), so it filtered tail
noise by filtering the whole dense-only and lexical-only case. Corrected
2026-09-02; the cut-off is now a rank cut-off.
"""

from __future__ import annotations

import pytest

from app.knowledge.hybrid_retriever import (  # noqa: E402
    HybridRetriever,
)

# ---------------------------------------------------------------------------
# Minimal stubs
# ---------------------------------------------------------------------------


class _BM25Empty:
    """BM25 stub that returns no results — isolates the Chroma/distance path."""

    def query(self, project_id: str, query: str, n: int) -> list:
        return []


class _Chroma:
    """Chroma stub that returns a fixed hit list."""

    def __init__(self, hits: list) -> None:
        self._hits = hits

    def query(
        self,
        project_id: str,
        query: str,
        n: int,
        where: dict | None = None,
    ) -> list:
        return self._hits


# ---------------------------------------------------------------------------
# Distance floor test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_distance_floor_drops_low_relevance() -> None:
    """Distance-floor filter: distance=0.30 survives; distance=0.60 is dropped."""
    hits = [
        {"id": "relevant", "document": "orders total revenue", "metadata": {}, "distance": 0.30},
        {"id": "noise", "document": "unrelated", "metadata": {}, "distance": 0.60},
    ]
    hr = HybridRetriever(
        bm25=_BM25Empty(),
        vector_store=_Chroma(hits),
        chroma_max_distance=0.45,
    )
    out = await hr.query("p", "revenue", k=10)
    ids = [r.doc_id for r in out]
    assert "relevant" in ids, f"Expected 'relevant' in results, got: {ids}"
    assert "noise" not in ids, f"Expected 'noise' filtered out, got: {ids}"
    # precision@k on the single labelled relevant doc.
    precision = sum(1 for i in ids if i == "relevant") / max(len(ids), 1)
    assert precision >= 0.5, f"Precision {precision:.2f} < 0.5"


# ---------------------------------------------------------------------------
# Config values gate (RET-R5 fix verification)
# ---------------------------------------------------------------------------


def test_config_floor_values() -> None:
    """Tightened floors are present in config (RET-R5 fix)."""
    from app.config import settings

    assert settings.rag_relevance_threshold == pytest.approx(0.45), (
        f"rag_relevance_threshold should be 0.45 (distance ≤ 0.45 ⟺ sim ≥ 0.55), "
        f"got {settings.rag_relevance_threshold}"
    )
    assert settings.hybrid_max_rank == 30, (
        f"hybrid_max_rank should be 30 (the rank-30 tail cut-off RET-R5 asked for), "
        f"got {settings.hybrid_max_rank}"
    )


def test_config_floor_implies_meaningful_similarity() -> None:
    """rag_relevance_threshold=0.45 ⟺ cosine similarity ≥ 0.55 — a meaningful floor."""
    from app.config import settings

    implied_sim = 1.0 - settings.rag_relevance_threshold
    # Must be at least 0.55 (well above the near-zero 0.2 of the old floor).
    assert implied_sim >= 0.55, (
        f"Implied similarity floor {implied_sim:.3f} < 0.55; threshold is too loose"
    )


def test_the_tail_cutoff_survives_a_change_to_rrf_k() -> None:
    """The cut-off is a rank, so it means the same thing at any ``rrf_k``.

    The value it replaced did not: it was chosen against ``rrf_k = 60`` and would
    have silently changed meaning the moment anyone edited that constant.
    """
    from app.config import settings

    assert settings.hybrid_max_rank > 0
    assert settings.hybrid_min_score < 1.0 / (settings.hybrid_rrf_k + 1), (
        f"hybrid_min_score={settings.hybrid_min_score:.5f} is at or above the best "
        "single-leg RRF contribution; single-leg hits would be discarded outright"
    )
