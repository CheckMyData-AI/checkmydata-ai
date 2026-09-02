"""Validation lock: cosine distance→similarity floor semantics (RET-R5).

Wave 2 T10 tightened the relevance floor:
  - ``rag_relevance_threshold``: 0.8 → 0.45  (distance ≤ 0.45 ⟺ similarity ≥ 0.55)
  - ``hybrid_min_score``: 0.01 → 0.03         (meant to be above a rank-30 RRF
    contribution of ~0.011, and reverted on 2026-09-02 — see below)

These tests verify the fix is in place and document the expected semantics so
any accidental regression back to the near-zero floor is caught immediately.

The ``hybrid_min_score`` half of T10 did not do what it was written to do, and
this file pinned it. A scalar floor is compared against the SUM of ``1/(rrf_k +
rank)`` over the legs that found a document, so a value above a rank-30
contribution (0.0111) is also above a rank-1 single-leg contribution (0.0164):
the floor filtered rank-30 tail noise by filtering **every** single-leg hit, and
left two-leg documents alive only to about rank 6. Measured over ranks 1..40:
0/40 single-leg documents and 82/1600 rank pairs survived. The rank cut-off T10
wanted is now ``hybrid_max_rank``, which is a rank cut-off, and the assertion
below tests that instead of the value that could not deliver it.
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


def test_rank30_tail_noise_is_filtered_by_a_rank_cutoff_ret_r5() -> None:
    # T10's goal, kept; T10's mechanism, replaced. A rank-30 hit is dropped
    # because it is ranked 31st or worse, not because a scalar floor happens to
    # sit above the number RRF assigns it.
    assert settings.hybrid_max_rank == 30, (
        f"hybrid_max_rank={settings.hybrid_max_rank}; expected 30 — RET-R5 regression"
    )


def test_the_fused_floor_does_not_secretly_require_both_legs_ret_r5() -> None:
    # The most a document found by ONE leg can score. A floor at or above it
    # discards every single-leg hit, which is an AND-gate, not a relevance bar.
    best_single_leg = 1.0 / (settings.hybrid_rrf_k + 1)
    assert settings.hybrid_min_score < best_single_leg, (
        f"hybrid_min_score={settings.hybrid_min_score:.5f} ≥ {best_single_leg:.5f} — "
        "single-leg hits are unreachable at this value"
    )
