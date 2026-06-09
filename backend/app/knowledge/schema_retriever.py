"""Question-aware schema retrieval (M4).

Replaces the top-12-by-``relevance_score`` heuristic in
``SQLAgent._build_query_context`` with a BM25 lookup over per-table schema
documents. The retriever consumes the LLM-enriched fields already produced by
:mod:`app.knowledge.db_index_pipeline` (business_description, data_patterns,
column notes, query_hints), tokenizes them with the same code-aware tokenizer
used by the codebase retriever, and ranks tables by lexical relevance to the
user's question.

We intentionally do **not** wire Chroma into this path:

* Schema docs are short (a few hundred tokens) and identifier-heavy, where
  BM25 dominates and embeddings add little lexical recall.
* Eliminating Chroma keeps the build cheap (no embedding API calls per table)
  and lets us roll out the feature behind a flag without an embedding budget.

Phase 3 adds the *semantic* leg as an optional **cross-encoder rerank** stage
instead: BM25 over-fetches a wider candidate set, then a cross-encoder jointly
scores ``(question, schema_doc)`` pairs to reorder by true relevance. This is
the "hybrid" form best suited to short identifier-heavy schema text — it gets
semantic ranking without paying to embed and store every table. The reranker is
optional and degrades to a no-op when disabled or unavailable, so the rest of
the pipeline doesn't care.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.knowledge.bm25_index import BM25Index

if TYPE_CHECKING:
    from app.knowledge.reranker import Reranker
    from app.models.db_index import DbIndex

logger = logging.getLogger(__name__)

# Cap how many column notes we splice into a table's schema doc to keep BM25
# tokens proportional to information content.
_MAX_COLUMN_NOTES = 25


class SchemaRetriever:
    """Per-connection BM25 retriever over LLM-enriched schema docs.

    Stateless beyond the BM25 file cache it shares with the codebase
    retriever. Construct once and inject (or instantiate per-call -- it's
    cheap).
    """

    def __init__(
        self,
        data_dir: str | Path,
        *,
        reranker: Reranker | None = None,
        rerank_candidates: int = 30,
    ) -> None:
        # Snapshots live next to the codebase BM25 snapshots but under a
        # ``schema_`` prefix so they can be cleaned independently.
        self._bm25 = BM25Index(Path(data_dir))
        # Phase 3: optional cross-encoder rerank over BM25 candidates. When
        # None, query() returns pure BM25 order (unchanged behaviour).
        self._reranker = reranker
        self._rerank_candidates = max(1, rerank_candidates)

    @staticmethod
    def _project_key(connection_id: str) -> str:
        # The BM25Index sanitizes this further (alphanumeric + underscore).
        return f"schema_{connection_id}"

    @staticmethod
    def _build_schema_doc(entry: DbIndex) -> str:
        """Compose the searchable text for one table.

        Layout (newline-separated) so token weighting reflects what users
        typically ask about::

            <table_name>
            description: <business_description>
            patterns: <data_patterns>
            hints: <query_hints>
            columns: <col_1>, <col_2>, ...
            notes_for_col1: <note>
            ...
        """
        import json

        lines: list[str] = [entry.table_name]
        if entry.business_description:
            lines.append(f"description: {entry.business_description}")
        if entry.data_patterns:
            lines.append(f"patterns: {entry.data_patterns}")
        if entry.query_hints:
            lines.append(f"hints: {entry.query_hints}")
        # column_notes_json is dict[col_name -> note]
        try:
            col_notes = json.loads(entry.column_notes_json or "{}")
        except Exception:
            col_notes = {}
        if isinstance(col_notes, dict) and col_notes:
            cols = list(col_notes.keys())[:_MAX_COLUMN_NOTES]
            lines.append(f"columns: {', '.join(cols)}")
            for col in cols:
                note = col_notes.get(col) or ""
                if note:
                    lines.append(f"{col}: {note}")
        return "\n".join(lines)

    @staticmethod
    def _build_metadata(entry: DbIndex) -> dict[str, Any]:
        return {
            "connection_id": entry.connection_id,
            "table_name": entry.table_name,
            "table_schema": entry.table_schema,
            "relevance_score": entry.relevance_score,
            "is_active": entry.is_active,
            "row_count": entry.row_count,
        }

    def build(
        self,
        connection_id: str,
        indexed_sha: str,
        entries: list[DbIndex],
    ) -> None:
        """Build and persist a BM25 snapshot for ``connection_id``.

        ``indexed_sha`` should be a fingerprint of the inputs (typically the
        max ``indexed_at`` timestamp formatted as a string) so freshness checks
        can detect drift without re-reading every row.
        """
        docs: list[tuple[str, str, dict[str, Any]]] = []
        for e in entries:
            text = self._build_schema_doc(e)
            if not text.strip():
                continue
            # R2-6: schema-qualify the BM25 doc id. Lowercasing the bare table
            # name alone collides when the same table name exists in two
            # schemas (e.g. ``public.users`` and ``analytics.users``) -- the
            # second doc silently overwrites the first in the BM25 store, so
            # one of the tables becomes unsearchable. Downstream consumers
            # resolve the entry via ``metadata["table_name"]`` (which stays the
            # bare name) and only fall back to ``id``, so qualifying the id is
            # safe.
            schema = (getattr(e, "table_schema", None) or "").strip()
            doc_id = f"{schema}.{e.table_name}".lower() if schema else e.table_name.lower()
            docs.append((doc_id, text, self._build_metadata(e)))
        self._bm25.build(self._project_key(connection_id), indexed_sha, docs)
        logger.info(
            "schema_retriever: built bm25 for conn=%s tables=%d sha=%s",
            connection_id[:8],
            len(docs),
            indexed_sha[:12] if indexed_sha else "?",
        )

    def query(
        self,
        connection_id: str,
        question: str,
        *,
        k: int = 15,
        only_active: bool = True,
    ) -> list[dict[str, Any]]:
        """Return up to ``k`` ranked tables for ``question``.

        Each result is the hit dict from :meth:`BM25Index.query` -- in
        particular ``id`` is the lowercased table name and ``metadata``
        contains the connection id + relevance score for downstream filtering.
        """
        if not question or not question.strip():
            return []
        # When a reranker is wired we over-fetch BM25 candidates so the
        # cross-encoder has a wider pool to reorder; aquery() trims back to k.
        fetch = max(k, self._rerank_candidates) if self._reranker is not None else k
        hits = self._bm25.query(self._project_key(connection_id), question, fetch)
        if only_active:
            hits = [h for h in hits if h.get("metadata", {}).get("is_active", True)]
        return hits

    async def aquery(
        self,
        connection_id: str,
        question: str,
        *,
        k: int = 15,
        only_active: bool = True,
    ) -> list[dict[str, Any]]:
        """Async query: BM25 (off-thread) + optional cross-encoder rerank.

        Falls back to pure BM25 order when no reranker is configured. This is
        the preferred entry point from async call sites; :meth:`query` remains
        for synchronous/threaded callers and BM25-only use.
        """
        import asyncio

        hits = await asyncio.to_thread(
            self.query, connection_id, question, k=k, only_active=only_active
        )
        if self._reranker is None or len(hits) <= 1:
            return hits[:k]
        candidates = hits[: self._rerank_candidates]
        reranked = await self._reranker.rerank(question, candidates, top_k=k)
        return list(reranked)[:k]

    def delete(self, connection_id: str) -> None:
        """Drop the snapshot for ``connection_id``."""
        self._bm25.delete(self._project_key(connection_id))

    def has_index(self, connection_id: str) -> bool:
        return self._bm25.indexed_sha(self._project_key(connection_id)) is not None


__all__ = ["SchemaRetriever"]
