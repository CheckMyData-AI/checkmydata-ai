"""TDD gate for RET-R5: tightened relevance floor (Wave 2 T10).

Verifies that:
  - ``chroma_max_distance=0.45`` drops noisy hits (distance 0.60) and keeps
    relevant ones (distance 0.30).
  - ``config.rag_relevance_threshold`` and ``config.hybrid_min_score`` are set
    to the tightened values (sim floor ≥ 0.55, min-score above rank-30 RRF).
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
    assert settings.hybrid_min_score == pytest.approx(0.03), (
        f"hybrid_min_score should be 0.03 (above rank-30 RRF contribution ~0.011), "
        f"got {settings.hybrid_min_score}"
    )


def test_config_floor_implies_meaningful_similarity() -> None:
    """rag_relevance_threshold=0.45 ⟺ cosine similarity ≥ 0.55 — a meaningful floor."""
    from app.config import settings

    implied_sim = 1.0 - settings.rag_relevance_threshold
    # Must be at least 0.55 (well above the near-zero 0.2 of the old floor).
    assert implied_sim >= 0.55, (
        f"Implied similarity floor {implied_sim:.3f} < 0.55; threshold is too loose"
    )


def test_hybrid_min_score_above_rank30_contribution() -> None:
    """hybrid_min_score must be above a rank-30 RRF contribution (1/90 ≈ 0.0111)."""
    from app.config import settings

    rank30_contribution = 1.0 / (60 + 30)  # 0.0111…
    assert settings.hybrid_min_score > rank30_contribution, (
        f"hybrid_min_score={settings.hybrid_min_score:.4f} ≤ rank-30 contribution "
        f"{rank30_contribution:.4f}; rank-30 hits are not filtered"
    )
