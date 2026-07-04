"""Validation lock: cosine distance→similarity floor semantics (RET-R5).

Pins the near-zero relevance floor: ChromaDB with hnsw:space=cosine stores
distance = 1 - cosine_similarity.  The current rag_relevance_threshold = 0.8 therefore
admits any chunk with cosine_similarity >= 0.2 — an extremely permissive (near-zero) floor
that allows near-random matches through.

Also pins that hybrid_min_score=0.01 is below the RRF contribution of a rank-30 hit
(1/(60+30) ≈ 0.0111), meaning rank-30 results are NOT filtered out by the min-score gate.

Wave 2 will tighten rag_relevance_threshold (lower distance = higher similarity required)
and raise hybrid_min_score.  When that happens these assertions should be updated.
"""

from __future__ import annotations

import pytest

from app.config import settings


def test_distance_threshold_is_a_weak_floor_ret_r5() -> None:
    # ChromaDB cosine: distance = 1 - cosine_similarity.
    # A max-distance of 0.8 admits everything with similarity >= 0.2 -> near-zero floor.
    max_distance = settings.rag_relevance_threshold  # 0.8 today
    implied_min_similarity = 1.0 - max_distance
    assert max_distance == pytest.approx(0.8)
    assert implied_min_similarity == pytest.approx(0.2)  # <-- documents RET-R5 (too permissive)


def test_hybrid_min_score_below_rank30_contribution_ret_r5() -> None:
    # RRF contribution of a rank-30 hit is 1/(60+30) ~= 0.011; hybrid_min_score=0.01 is below it,
    # so rank-30 results are not filtered out by the hybrid min-score gate.
    rank30_contribution = 1.0 / (60 + 30)
    assert settings.hybrid_min_score < rank30_contribution
