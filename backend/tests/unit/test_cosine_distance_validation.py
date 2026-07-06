"""Validation lock: cosine distance→similarity floor semantics (RET-R5).

Wave 2 T10 tightened the relevance floor:
  - ``rag_relevance_threshold``: 0.8 → 0.45  (distance ≤ 0.45 ⟺ similarity ≥ 0.55)
  - ``hybrid_min_score``: 0.01 → 0.03         (now above rank-30 RRF contribution ~0.011)

These tests verify the fix is in place and document the expected semantics so
any accidental regression back to the near-zero floor is caught immediately.
"""

from __future__ import annotations

import pytest

from app.config import settings


def test_distance_threshold_is_a_meaningful_floor_ret_r5() -> None:
    # ChromaDB cosine: distance = 1 - cosine_similarity.
    # The tightened max-distance of 0.45 admits only chunks with similarity >= 0.55
    # — a real semantic relevance bar (fixes RET-R5).
    max_distance = settings.rag_relevance_threshold  # 0.45 after tightening
    implied_min_similarity = 1.0 - max_distance
    assert max_distance == pytest.approx(0.45), (
        f"rag_relevance_threshold regressed to {max_distance}; expected 0.45 (RET-R5 fix)"
    )
    # Implied similarity floor must be meaningfully above zero (≥ 0.55).
    assert implied_min_similarity >= 0.55, (
        f"Implied similarity floor {implied_min_similarity:.3f} < 0.55; "
        "threshold is too permissive — RET-R5 regression"
    )


def test_hybrid_min_score_above_rank30_contribution_ret_r5() -> None:
    # RRF contribution of a rank-30 hit is 1/(60+30) ~= 0.0111.
    # hybrid_min_score=0.03 is above it, so rank-30 tail noise IS filtered (fixes RET-R5).
    rank30_contribution = 1.0 / (60 + 30)
    assert settings.hybrid_min_score > rank30_contribution, (
        f"hybrid_min_score={settings.hybrid_min_score:.4f} ≤ rank-30 contribution "
        f"{rank30_contribution:.4f} — RET-R5 regression"
    )
    assert settings.hybrid_min_score == pytest.approx(0.03), (
        f"hybrid_min_score regressed to {settings.hybrid_min_score}; expected 0.03 (RET-R5 fix)"
    )
