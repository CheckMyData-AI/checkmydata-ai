"""Hybrid (BM25 + semantic) retrieval with Reciprocal Rank Fusion (M3).

Fuses results from :class:`BM25Index` (lexical) and
:class:`VectorStore` (dense semantic) using RRF::

    rrf_score(doc) = sum_over_retrievers( 1 / (rrf_k + rank_in_retriever) )

This gives lexical hits a fair shake (which the existing Chroma-only path
misses badly for exact identifier matches like ``analyze_query``) while
preserving semantic recall for natural-language queries.

Critical-situation handling:
    * Each retriever runs under a soft timeout (default 5 s); a timeout or
      exception in one retriever degrades gracefully -- we just use the other.
    * If both fail, the caller receives an empty list (matching the existing
      KnowledgeAgent contract for "no relevant docs found").
    * Memory: we intentionally do **not** load full document bodies a second
      time -- ``document`` field is taken from whichever retriever supplied it.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from app.knowledge.bm25_index import BM25Index
from app.knowledge.vector_store import VectorStore

logger = logging.getLogger(__name__)

# Soft per-retriever timeout (seconds). The query as a whole is bounded by
# ``max(bm25_timeout, chroma_timeout) + a few ms`` because gather runs them
# in parallel.
_DEFAULT_RETRIEVER_TIMEOUT_SEC = 5.0


@dataclass
class HybridResult:
    """A single fused document.

    Attributes:
        doc_id: Stable identifier from the underlying retriever.
        document: The document text (may be empty if neither retriever
            returned it).
        metadata: Merged metadata dict.
        rrf_score: Final fused score.
        bm25_rank: 1-indexed rank in the lexical leg, or ``None`` if absent.
        chroma_rank: 1-indexed rank in the semantic leg, or ``None`` if absent.
        sources: Tuple of source names contributing to the score.
    """

    doc_id: str
    document: str
    metadata: dict[str, Any] = field(default_factory=dict)
    rrf_score: float = 0.0
    bm25_rank: int | None = None
    chroma_rank: int | None = None
    sources: tuple[str, ...] = ()


class HybridRetriever:
    """Glue between :class:`BM25Index` and :class:`VectorStore`.

    Stateful only via the two underlying retrievers it composes; safe to share
    across requests. Construct once at app startup and inject.
    """

    def __init__(
        self,
        bm25: BM25Index,
        vector_store: VectorStore,
        *,
        rrf_k: int = 60,
        min_score: float = 0.0,
        retriever_timeout_sec: float = _DEFAULT_RETRIEVER_TIMEOUT_SEC,
    ) -> None:
        self._bm25 = bm25
        self._vector = vector_store
        self._rrf_k = max(1, rrf_k)
        self._min_score = max(0.0, min_score)
        self._timeout = max(0.1, retriever_timeout_sec)

    async def query(
        self,
        project_id: str,
        query_text: str,
        *,
        k: int = 20,
        where: dict[str, Any] | None = None,
        n_per_retriever: int | None = None,
    ) -> list[HybridResult]:
        """Run both retrievers in parallel and fuse the result lists.

        ``n_per_retriever`` defaults to ``2 * k`` so RRF has enough overlap
        material to fuse. Returns up to ``k`` results sorted by RRF score.
        """
        if not query_text or not query_text.strip():
            return []
        per_leg = n_per_retriever if n_per_retriever is not None else max(10, 2 * k)

        bm25_task = asyncio.create_task(self._run_bm25(project_id, query_text, per_leg))
        chroma_task = asyncio.create_task(self._run_chroma(project_id, query_text, per_leg, where))
        bm25_results, chroma_results = await asyncio.gather(
            bm25_task,
            chroma_task,
            return_exceptions=False,
        )

        fused = self._fuse(bm25_results, chroma_results)
        # Apply min_score and trim to k.
        fused = [r for r in fused if r.rrf_score >= self._min_score]
        return fused[:k]

    # ------------------------------------------------------------------
    # Retriever wrappers (with per-leg timeout + error containment)
    # ------------------------------------------------------------------

    async def _run_bm25(
        self,
        project_id: str,
        query: str,
        n: int,
    ) -> list[dict[str, Any]]:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._bm25.query, project_id, query, n),
                timeout=self._timeout,
            )
        except TimeoutError:
            logger.warning("hybrid: BM25 timed out for %s", project_id[:8])
            return []
        except Exception:
            logger.warning("hybrid: BM25 failed for %s", project_id[:8], exc_info=True)
            return []

    async def _run_chroma(
        self,
        project_id: str,
        query: str,
        n: int,
        where: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    self._vector.query,
                    project_id,
                    query,
                    n,
                    where,
                ),
                timeout=self._timeout,
            )
        except TimeoutError:
            logger.warning("hybrid: Chroma timed out for %s", project_id[:8])
            return []
        except Exception:
            logger.warning("hybrid: Chroma failed for %s", project_id[:8], exc_info=True)
            return []

    # ------------------------------------------------------------------
    # Reciprocal Rank Fusion
    # ------------------------------------------------------------------

    def _fuse(
        self,
        bm25_results: list[dict[str, Any]],
        chroma_results: list[dict[str, Any]],
    ) -> list[HybridResult]:
        merged: dict[str, HybridResult] = {}

        for rank, hit in enumerate(bm25_results, start=1):
            doc_id = hit.get("id")
            if not doc_id:
                continue
            entry = merged.setdefault(
                doc_id,
                HybridResult(
                    doc_id=doc_id,
                    document=hit.get("document", "") or "",
                    metadata=dict(hit.get("metadata") or {}),
                ),
            )
            entry.rrf_score += 1.0 / (self._rrf_k + rank)
            entry.bm25_rank = rank
            entry.sources = tuple(set(entry.sources) | {"bm25"})

        for rank, hit in enumerate(chroma_results, start=1):
            doc_id = hit.get("id")
            if not doc_id:
                continue
            existing = merged.get(doc_id)
            if existing is None:
                entry = HybridResult(
                    doc_id=doc_id,
                    document=hit.get("document", "") or "",
                    metadata=dict(hit.get("metadata") or {}),
                )
                merged[doc_id] = entry
            else:
                entry = existing
                # Prefer non-empty document text if BM25 had none.
                if not entry.document and hit.get("document"):
                    entry.document = hit["document"]
                # Merge metadata (BM25 wins on conflicts; both come from same source).
                for key, value in (hit.get("metadata") or {}).items():
                    entry.metadata.setdefault(key, value)
            entry.rrf_score += 1.0 / (self._rrf_k + rank)
            entry.chroma_rank = rank
            entry.sources = tuple(set(entry.sources) | {"chroma"})

        return sorted(merged.values(), key=lambda r: r.rrf_score, reverse=True)


__all__ = ["HybridResult", "HybridRetriever"]
