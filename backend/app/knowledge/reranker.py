"""Cross-encoder reranking stage (Phase 3 — Intelligent Retrieval Stack).

Reciprocal Rank Fusion (:mod:`app.knowledge.hybrid_retriever`) is a strong,
cheap *first-stage* retriever, but it ranks on rank-position arithmetic alone —
it never actually reads the query against the candidate text. A cross-encoder
re-scores each ``(query, document)`` pair jointly, which reliably lifts the
truly relevant chunk into the top-k before it reaches the LLM prompt.

Design constraints:

* **Optional + graceful.** ``sentence-transformers`` (and a model download) are
  heavy. The reranker is OFF by default; if the library or model is unavailable
  at runtime it degrades to a no-op (returns the input order) and logs once, so
  retrieval never hard-fails on a missing optional dependency.
* **Off the event loop.** Model inference is CPU-bound; scoring runs in a worker
  thread via ``asyncio.to_thread``.
* **Bounded.** Only the top ``candidates`` fused results are reranked, capping
  inference cost regardless of how wide the first stage fans out.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)


@runtime_checkable
class Rerankable(Protocol):
    """Minimal shape the reranker needs from a candidate result."""

    document: str


class Reranker(Protocol):
    """Protocol for a second-stage reranker."""

    async def rerank(
        self,
        query: str,
        results: Sequence,
        *,
        top_k: int,
    ) -> list:
        """Return ``results`` reordered by relevance to ``query``, trimmed to
        ``top_k``."""
        ...


class NoopReranker:
    """Identity reranker — returns the first ``top_k`` unchanged.

    Used when reranking is disabled or the backing model is unavailable, so
    callers can always hold a ``Reranker`` without branching.
    """

    async def rerank(self, query: str, results: Sequence, *, top_k: int) -> list:  # noqa: ARG002
        return list(results)[:top_k]


class CrossEncoderReranker:
    """Sentence-Transformers ``CrossEncoder`` reranker with lazy model load.

    The model is loaded on first use (not at construction) so flipping the flag
    on never blocks startup and a broken/missing model only ever degrades the
    request that touched it. After a failed load the instance latches into a
    no-op so we don't retry the expensive import on every query.
    """

    def __init__(self, model_name: str, *, max_length: int = 512) -> None:
        self._model_name = model_name
        self._max_length = max_length
        self._model: Any = None
        self._unavailable = False

    def _ensure_model(self) -> bool:
        """Best-effort lazy load. Returns ``True`` when a model is ready."""
        if self._model is not None:
            return True
        if self._unavailable:
            return False
        try:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self._model_name, max_length=self._max_length)
            logger.info("reranker: loaded cross-encoder model %s", self._model_name)
            return True
        except Exception:
            self._unavailable = True
            logger.warning(
                "reranker: cross-encoder unavailable (model=%s) — falling back to "
                "no-op reranking. Install 'sentence-transformers' to enable.",
                self._model_name,
                exc_info=True,
            )
            return False

    @staticmethod
    def _doc_text(item: object) -> str:
        """Extract candidate text whether the item is a dataclass-like object
        (``HybridResult``) or a BM25 hit dict."""
        if isinstance(item, dict):
            return str(item.get("document", "") or "")
        return str(getattr(item, "document", "") or "")

    @staticmethod
    def _annotate(item: object, score: float, rank: int) -> None:
        """Attach the cross-encoder score + new rank for observability when the
        candidate exposes a mutable ``metadata`` mapping."""
        if isinstance(item, dict):
            meta = item.get("metadata")
        else:
            meta = getattr(item, "metadata", None)
        if isinstance(meta, dict):
            meta["rerank_score"] = round(score, 6)
            meta["rerank_position"] = rank

    def _rank_sync(self, query: str, documents: list[str]) -> list[dict]:
        """Use ``CrossEncoder.rank(query, docs)`` when available (RET-R14).

        ``CrossEncoder.rank`` returns a list of ``{"corpus_id": int, "score": float}``
        dicts already sorted highest-relevance first — the library's contract, not a
        local sign assumption.  Falls back to ``predict`` + manual sort for stub models
        in tests or older sentence-transformers versions that lack ``.rank``.
        """
        if callable(getattr(self._model, "rank", None)):
            ranked = self._model.rank(query, documents, return_documents=False)
            # Normalise: sentence-transformers may return objects or dicts.
            return [
                {
                    "corpus_id": int(r["corpus_id"] if isinstance(r, dict) else r.corpus_id),
                    "score": float(r["score"] if isinstance(r, dict) else r.score),
                }
                for r in ranked
            ]
        # Fallback: predict() + manual sort for models without .rank().
        pairs = [[query, doc] for doc in documents]
        raw_scores = self._model.predict(pairs)
        scores = [float(s) for s in raw_scores]
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        return [{"corpus_id": idx, "score": scores[idx]} for idx in order]

    async def rerank(self, query: str, results: Sequence, *, top_k: int) -> list:
        items = list(results)
        if not query or not query.strip() or len(items) <= 1:
            return items[:top_k]
        if not self._ensure_model():
            return items[:top_k]

        documents = [self._doc_text(r) for r in items]
        try:
            ranked = await asyncio.to_thread(self._rank_sync, query, documents)
        except Exception:
            logger.warning("reranker: scoring failed — keeping fusion order", exc_info=True)
            return items[:top_k]

        reranked = []
        for position, entry in enumerate(ranked, start=1):
            idx = entry["corpus_id"]
            score = entry["score"]
            item = items[idx]
            self._annotate(item, score, position)
            reranked.append(item)
        return reranked[:top_k]


def build_reranker(
    *,
    enabled: bool,
    model_name: str,
) -> Reranker:
    """Factory: a real cross-encoder when enabled, else a no-op."""
    if enabled and model_name:
        return CrossEncoderReranker(model_name)
    return NoopReranker()


__all__ = ["CrossEncoderReranker", "NoopReranker", "Reranker", "build_reranker"]
