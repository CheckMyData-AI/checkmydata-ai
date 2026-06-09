"""Tests for the Phase 3 cross-encoder reranker.

The cross-encoder model itself is heavy and optional, so these tests focus on
the contract that matters for production safety: graceful degradation to a
no-op when the model is unavailable, correct reordering when a model *is*
present (via a stub), and that both dataclass-like and dict candidates are
handled.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app.knowledge.reranker import (
    CrossEncoderReranker,
    NoopReranker,
    build_reranker,
)


@dataclass
class _Result:
    document: str
    metadata: dict = field(default_factory=dict)


@pytest.mark.asyncio
async def test_noop_reranker_preserves_order_and_trims() -> None:
    rr = NoopReranker()
    items = [_Result("a"), _Result("b"), _Result("c")]
    out = await rr.rerank("q", items, top_k=2)
    assert [r.document for r in out] == ["a", "b"]


def test_build_reranker_factory() -> None:
    assert isinstance(build_reranker(enabled=False, model_name="x"), NoopReranker)
    assert isinstance(build_reranker(enabled=True, model_name=""), NoopReranker)
    assert isinstance(build_reranker(enabled=True, model_name="some/model"), CrossEncoderReranker)


@pytest.mark.asyncio
async def test_cross_encoder_degrades_to_noop_when_model_unavailable() -> None:
    # A bogus model name forces the lazy import/load to fail → no-op fallback.
    rr = CrossEncoderReranker("definitely/not-a-real-model-xyz")
    items = [_Result("a"), _Result("b")]
    out = await rr.rerank("q", items, top_k=2)
    assert [r.document for r in out] == ["a", "b"]
    # Latched unavailable so subsequent calls don't retry the import.
    assert rr._unavailable is True


@pytest.mark.asyncio
async def test_cross_encoder_reorders_with_stub_model(monkeypatch) -> None:
    rr = CrossEncoderReranker("stub")

    class _StubModel:
        def predict(self, pairs):
            # Score = length of the document text → longer docs rank higher.
            return [float(len(doc)) for _q, doc in pairs]

    # Inject the stub, bypassing the real sentence-transformers load.
    rr._model = _StubModel()

    items = [
        _Result("short", {"k": 1}),
        _Result("the-longest-document", {"k": 2}),
        _Result("medium-doc", {"k": 3}),
    ]
    out = await rr.rerank("q", items, top_k=3)
    assert [r.document for r in out] == [
        "the-longest-document",
        "medium-doc",
        "short",
    ]
    # Reranker annotates metadata for observability.
    assert out[0].metadata["rerank_position"] == 1
    assert "rerank_score" in out[0].metadata


@pytest.mark.asyncio
async def test_cross_encoder_handles_dict_candidates(monkeypatch) -> None:
    rr = CrossEncoderReranker("stub")

    class _StubModel:
        def predict(self, pairs):
            return [float(len(doc)) for _q, doc in pairs]

    rr._model = _StubModel()

    items = [
        {"document": "x", "metadata": {}},
        {"document": "longer-text", "metadata": {}},
    ]
    out = await rr.rerank("q", items, top_k=2)
    assert out[0]["document"] == "longer-text"
    assert out[0]["metadata"]["rerank_position"] == 1
