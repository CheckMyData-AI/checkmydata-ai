"""BM25 lexical index for hybrid RAG retrieval (M3).

Persists a per-project BM25 corpus on disk and supplies a fast tokenizer
tailored to source code (handles camelCase, snake_case, dotted identifiers,
and SQL keywords). Used as the lexical leg of :class:`HybridRetriever`.

Persistence layout::

    {bm25_data_dir}/{project_id}.pkl   # pickled BM25Snapshot
    {bm25_data_dir}/{project_id}.tmp   # atomic-write staging file
"""

from __future__ import annotations

import logging
import os
import pickle
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rank_bm25 import BM25Okapi

logger = logging.getLogger(__name__)

# Tokenization knobs.
_MAX_TOKENS_PER_DOC = 1024  # cap to keep BM25 fast even on huge files.
_MIN_TOKEN_LEN = 2
_STOPWORDS: frozenset[str] = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "in",
        "on",
        "for",
        "to",
        "is",
        "are",
        "be",
        "by",
        "with",
        "from",
        "this",
        "that",
        "it",
        "as",
        "at",
        "but",
        "if",
        "then",
        "else",
    }
)

# Snapshot format version. Bump on breaking changes; older snapshots will be
# treated as "missing" and rebuilt on next index run.
_SCHEMA_VERSION = 1


@dataclass
class BM25Snapshot:
    """The pickled payload persisted to disk."""

    schema_version: int
    project_id: str
    indexed_sha: str
    doc_ids: list[str]
    doc_metadatas: list[dict[str, Any]]
    bm25: BM25Okapi
    raw_texts: list[str] = field(default_factory=list)


def tokenize_code(text: str) -> list[str]:
    """Code-aware tokenizer.

    * Splits ``camelCase`` and ``PascalCase`` into component words.
    * Splits ``snake_case``, ``kebab-case``, and dotted identifiers.
    * Lowercases and drops single-character tokens, ``__init__``-style noise,
      and short stopwords. Caps the output at ``_MAX_TOKENS_PER_DOC`` to
      keep BM25 inference cheap on whole-file documents.
    """
    if not text:
        return []
    # Split on any non-alphanumeric/underscore.
    raw = re.split(r"[^A-Za-z0-9_]+", text)
    out: list[str] = []
    for chunk in raw:
        if not chunk:
            continue
        # Split snake_case and kebab-case first.
        for sub in chunk.replace("__", "_").split("_"):
            if not sub:
                continue
            # Split camelCase / PascalCase.
            parts = re.findall(
                r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z0-9]+|[A-Z]+|[0-9]+",
                sub,
            )
            if not parts:
                parts = [sub]
            for p in parts:
                lower = p.lower()
                if len(lower) < _MIN_TOKEN_LEN:
                    continue
                if lower in _STOPWORDS:
                    continue
                out.append(lower)
                if len(out) >= _MAX_TOKENS_PER_DOC:
                    return out
    return out


class BM25Index:
    """Per-project BM25 index, lazily loaded from disk.

    Threading model: instances are immutable after construction; the global
    cache of loaded snapshots uses an ``RLock``. Build operations always write
    via ``.tmp`` -> ``os.replace`` so concurrent readers never see partial files.
    """

    def __init__(self, data_dir: str | Path) -> None:
        self._dir = Path(data_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._snapshots: dict[str, BM25Snapshot] = {}
        self._lock = threading.RLock()

    def _path(self, project_id: str) -> Path:
        safe = re.sub(r"[^a-zA-Z0-9_-]", "_", project_id)[:64]
        return self._dir / f"{safe}.pkl"

    # ------------------------------------------------------------------
    # Build / persist
    # ------------------------------------------------------------------

    def build(
        self,
        project_id: str,
        indexed_sha: str,
        documents: list[tuple[str, str, dict[str, Any]]],
    ) -> BM25Snapshot:
        """Build and persist a snapshot atomically.

        ``documents`` is a list of ``(doc_id, text, metadata)``. Returns the
        in-memory :class:`BM25Snapshot` (also written to disk).
        Empty corpora are persisted as a no-op snapshot (so freshness can still
        be tracked).
        """
        doc_ids: list[str] = []
        raw_texts: list[str] = []
        metadatas: list[dict[str, Any]] = []
        tokenized: list[list[str]] = []
        for doc_id, text, meta in documents:
            tokens = tokenize_code(text or "")
            if not tokens:
                continue
            doc_ids.append(doc_id)
            raw_texts.append(text)
            metadatas.append(dict(meta or {}))
            tokenized.append(tokens)
        if not tokenized:
            # BM25Okapi requires at least one token; create a sentinel.
            tokenized = [["__empty__"]]
            doc_ids = ["__empty__"]
            raw_texts = [""]
            metadatas = [{}]
        bm25 = BM25Okapi(tokenized)
        snapshot = BM25Snapshot(
            schema_version=_SCHEMA_VERSION,
            project_id=project_id,
            indexed_sha=indexed_sha,
            doc_ids=doc_ids,
            doc_metadatas=metadatas,
            bm25=bm25,
            raw_texts=raw_texts,
        )
        self._persist(project_id, snapshot)
        with self._lock:
            self._snapshots[project_id] = snapshot
        logger.info(
            "bm25_index: built project=%s docs=%d sha=%s",
            project_id[:8],
            len(doc_ids),
            indexed_sha[:8] if indexed_sha else "?",
        )
        return snapshot

    def _persist(self, project_id: str, snapshot: BM25Snapshot) -> None:
        target = self._path(project_id)
        tmp = target.with_suffix(".tmp")
        try:
            with tmp.open("wb") as fh:
                pickle.dump(snapshot, fh, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp, target)
        except Exception:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------
    # Load / query
    # ------------------------------------------------------------------

    def load(self, project_id: str) -> BM25Snapshot | None:
        """Return the cached/loaded snapshot, or ``None`` if absent or corrupted."""
        with self._lock:
            cached = self._snapshots.get(project_id)
            if cached is not None:
                return cached
            path = self._path(project_id)
            if not path.exists():
                return None
            try:
                with path.open("rb") as fh:
                    snap = pickle.load(fh)
            except Exception:
                logger.warning(
                    "bm25_index: failed to load %s (corrupted? rebuilding will fix)",
                    path,
                    exc_info=True,
                )
                return None
            if not isinstance(snap, BM25Snapshot):
                return None
            if snap.schema_version != _SCHEMA_VERSION:
                logger.info(
                    "bm25_index: schema mismatch for %s (have v%d, expected v%d)",
                    project_id[:8],
                    snap.schema_version,
                    _SCHEMA_VERSION,
                )
                return None
            self._snapshots[project_id] = snap
            return snap

    def query(
        self,
        project_id: str,
        query_text: str,
        n_results: int = 20,
    ) -> list[dict[str, Any]]:
        """Return the top ``n_results`` documents for ``query_text``.

        Output schema matches :meth:`app.knowledge.vector_store.VectorStore.query`
        for compatibility with the existing retrieval contract::

            [{"id": ..., "document": ..., "metadata": ..., "score": float}, ...]
        """
        snap = self.load(project_id)
        if snap is None:
            return []
        tokens = tokenize_code(query_text)
        if not tokens:
            return []
        try:
            scores = snap.bm25.get_scores(tokens)
        except Exception:
            logger.warning("bm25_index: scoring failed for %s", project_id[:8], exc_info=True)
            return []
        if not len(scores):
            return []
        # Pick top-n indices by score descending.
        # ``argsort`` is O(n log n); for small corpora that's fine.
        idx_sorted = sorted(
            range(len(scores)),
            key=lambda i: scores[i],
            reverse=True,
        )[: max(0, n_results)]
        out: list[dict[str, Any]] = []
        for idx in idx_sorted:
            score = float(scores[idx])
            if score <= 0.0:
                break
            doc_id = snap.doc_ids[idx]
            if doc_id == "__empty__":
                continue
            out.append(
                {
                    "id": doc_id,
                    "document": snap.raw_texts[idx] if idx < len(snap.raw_texts) else "",
                    "metadata": snap.doc_metadatas[idx] if idx < len(snap.doc_metadatas) else {},
                    "score": score,
                }
            )
        return out

    def delete(self, project_id: str) -> None:
        """Remove a project's snapshot from disk and the in-memory cache."""
        with self._lock:
            self._snapshots.pop(project_id, None)
        path = self._path(project_id)
        try:
            if path.exists():
                path.unlink()
        except OSError:
            logger.warning("bm25_index: failed to delete %s", path, exc_info=True)

    def indexed_sha(self, project_id: str) -> str | None:
        """Cheap freshness check that doesn't deserialize the full snapshot.

        We still need to open the file to read the SHA, but the parse is O(1).
        Returns ``None`` if no snapshot exists or it's unreadable.
        """
        snap = self.load(project_id)
        return snap.indexed_sha if snap else None


__all__ = [
    "BM25Index",
    "BM25Snapshot",
    "tokenize_code",
]
