"""The fused-score floor could not express the rank cut-off it was written for.

RRF gives a document ``1/(rrf_k + rank)`` **per leg it was found in**, and the
floor is compared against the *sum*. With ``rrf_k = 60`` the most a document
found by one leg alone can ever score is ``1/61 = 0.01639`` — so a floor of
``0.03``, chosen to sit above a rank-30 contribution (``1/90 ≈ 0.0111``), also
sits above every single-leg hit there is, rank 1 included.

The effect is an AND-gate nobody asked for: a document has to be found by BOTH
legs, and by both within about rank 6 (``2/66 = 0.0303`` passes, ``2/67`` does
not). A question with no lexical overlap — the exact case the dense leg exists
for — retrieves nothing however well the embeddings ranked it.

A scalar floor on a sum cannot say "rank ≤ N". A rank cut-off has to be a rank
cut-off, so that is what ``hybrid_max_rank`` is, and the floor stops pretending.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings, settings
from app.knowledge.hybrid_retriever import HybridRetriever


class _Leg:
    """A retriever leg returning a fixed, already-ranked hit list."""

    def __init__(self, ids: list[str]) -> None:
        self._hits = [{"id": i, "document": f"doc {i}", "metadata": {}} for i in ids]

    def query(self, project_id: str, query: str, n: int, where: dict | None = None) -> list:
        return self._hits[:n]

    def query_with_reason(self, project_id: str, query: str, n: int) -> tuple[list, str]:
        hits = self._hits[:n]
        return hits, ("ok" if hits else "no_match")


def _retriever(bm25_ids: list[str], chroma_ids: list[str], **kwargs) -> HybridRetriever:
    return HybridRetriever(bm25=_Leg(bm25_ids), vector_store=_Leg(chroma_ids), **kwargs)


# --------------------------------------------------------------------------
# The arithmetic, stated so a future edit to rrf_k cannot quietly break it.
# --------------------------------------------------------------------------


def test_the_floor_can_never_exceed_a_single_leg_rank_one_contribution() -> None:
    best_single_leg = 1.0 / (settings.hybrid_rrf_k + 1)
    assert settings.hybrid_min_score < best_single_leg, (
        f"hybrid_min_score={settings.hybrid_min_score} ≥ {best_single_leg:.5f}, the most a "
        "document found by one leg can score. Hybrid retrieval is an AND-gate at this value."
    )


def test_a_floor_above_that_contribution_is_refused_at_boot() -> None:
    with pytest.raises(ValidationError, match="AND-gate"):
        Settings(hybrid_min_score=0.03, hybrid_rrf_k=60)


def test_a_floor_below_it_is_accepted() -> None:
    assert Settings(hybrid_min_score=0.01, hybrid_rrf_k=60).hybrid_min_score == 0.01


# --------------------------------------------------------------------------
# What the floor was doing to real retrievals.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_dense_only_hit_at_rank_one_survives() -> None:
    """The case the dense leg exists for: no lexical overlap at all."""
    hr = _retriever([], ["semantic"], rrf_k=60, min_score=settings.hybrid_min_score)
    assert [r.doc_id for r in await hr.query("p", "how do we decide a lapse", k=10)] == ["semantic"]


@pytest.mark.asyncio
async def test_a_bm25_only_hit_at_rank_one_survives() -> None:
    hr = _retriever(["lexical"], [], rrf_k=60, min_score=settings.hybrid_min_score)
    assert [r.doc_id for r in await hr.query("p", "invoice_id", k=10)] == ["lexical"]


@pytest.mark.asyncio
async def test_a_two_leg_hit_deeper_than_rank_six_survives() -> None:
    """``2/67 < 0.03``: both legs found it, and the old floor dropped it anyway."""
    filler = [f"f{i}" for i in range(6)]
    hr = _retriever(
        filler + ["both"], filler + ["both"], rrf_k=60, min_score=settings.hybrid_min_score
    )
    assert "both" in [r.doc_id for r in await hr.query("p", "q", k=20)]


# --------------------------------------------------------------------------
# The rank cut-off RET-R5 actually wanted, now expressed as one.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tail_noise_past_the_cutoff_is_dropped() -> None:
    ids = [f"d{i}" for i in range(1, 41)]  # ranks 1..40 in one leg
    hr = _retriever([], ids, rrf_k=60, max_rank=30)
    out = [r.doc_id for r in await hr.query("p", "q", k=40)]
    assert "d30" in out, "rank 30 is inside the cut-off"
    assert "d31" not in out, "rank 31 is past it"


@pytest.mark.asyncio
async def test_the_cutoff_is_per_leg_so_the_better_rank_wins() -> None:
    """Deep in one leg, shallow in the other — the document is still findable."""
    deep = [f"d{i}" for i in range(1, 40)] + ["target"]  # bm25 rank 40
    hr = _retriever(deep, ["x", "y", "target"], rrf_k=60, max_rank=30)
    assert "target" in [r.doc_id for r in await hr.query("p", "q", k=40)]


@pytest.mark.asyncio
async def test_the_cutoff_is_off_when_unset() -> None:
    ids = [f"d{i}" for i in range(1, 41)]
    hr = _retriever([], ids, rrf_k=60)
    assert "d40" in [r.doc_id for r in await hr.query("p", "q", k=40)]


def test_the_configured_cutoff_is_the_one_ret_r5_asked_for() -> None:
    assert settings.hybrid_max_rank == 30
