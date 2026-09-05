"""BM25 lexical index for hybrid RAG retrieval (M3).

Persists a per-project BM25 corpus on disk and supplies a fast tokenizer
tailored to source code (handles camelCase, snake_case, dotted identifiers,
and SQL keywords). Used as the lexical leg of :class:`HybridRetriever`.

Persistence layout::

    {bm25_data_dir}/{project_id}.json.gz   # gzip-compressed JSON snapshot
    {bm25_data_dir}/{project_id}.tmp       # atomic-write staging file

F-KNOW-06: this was a pickle, and ``pickle.load`` executes whatever the payload
says. The file is written by the app to its own disk, which is why the finding
called the risk *latent* — but ``BM25_DATA_DIR`` is configurable, and the
shared-volume fix that F-KNOW-12 nearly took would have put it somewhere several
processes can write. The stored form is now data, not opcodes: the **tokenized
corpus** is persisted and :class:`BM25Okapi` is reconstructed on load, which also
means the on-disk format is inspectable with ``zcat``.

A leftover ``.pkl`` from an older build is **never read** — not even once, not to
migrate. Reading it "just for the upgrade" keeps the primitive alive for exactly
the window an attacker needs, and snapshots are derived data anyway: the start-up
reconcile (F-KNOW-12) rebuilds a missing one from Postgres for free.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rank_bm25 import BM25Okapi

logger = logging.getLogger(__name__)

#: Why a BM25 leg came back empty (F-KNOW-07). Only ``MISS_NO_MATCH`` and
#: ``MISS_NO_QUERY_TOKENS`` are healthy — the index worked and had nothing to say.
#: The rest mean hybrid retrieval is silently dense-only until a reindex.
MISS_NO_SNAPSHOT = "no_snapshot"
MISS_CORRUPT = "corrupt"
MISS_SCHEMA_MISMATCH = "schema_mismatch"
MISS_NO_QUERY_TOKENS = "no_query_tokens"
MISS_NO_MATCH = "no_match"
MISS_SCORE_ERROR = "score_error"

#: Reasons that mean the index is unusable, not merely unhelpful.
BM25_UNUSABLE = frozenset({MISS_NO_SNAPSHOT, MISS_CORRUPT, MISS_SCHEMA_MISMATCH, MISS_SCORE_ERROR})

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
_SCHEMA_VERSION = 3


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
    #: The tokenized corpus. This is what is persisted; ``bm25`` is rebuilt from it
    #: on load, so nothing on disk has to be a class instance.
    tokenized: list[list[str]] = field(default_factory=list)


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

    def _emit(token: str) -> bool:
        """Append one token. Returns False when the per-document cap is reached."""
        if len(token) < _MIN_TOKEN_LEN or token in _STOPWORDS:
            return True
        out.append(token)
        if len(out) >= _MAX_TOKENS_PER_DOC:
            # RET-R17: log when a document hits the cap so operators
            # know schema/source docs are being silently truncated.
            logger.debug(
                "bm25_index: doc truncated at %d-token cap (text len=%d chars)",
                _MAX_TOKENS_PER_DOC,
                len(text),
            )
            return False
        return True

    for chunk in raw:
        if not chunk:
            continue
        # Split snake_case and kebab-case first.
        subs = [s for s in chunk.replace("__", "_").split("_") if s]
        for sub in subs:
            # Split camelCase / PascalCase.
            parts = re.findall(
                r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z0-9]+|[A-Z]+|[0-9]+",
                sub,
            )
            if not parts:
                parts = [sub]
            for p in parts:
                if not _emit(p.lower()):
                    return out
            # RET row 2.3: the compound itself, beside its parts. `getUserName`
            # was indexed as three ordinary words and the name a person types
            # existed nowhere in the corpus. BM25 ranks by IDF, so the whole
            # identifier — a rare term — is exactly the signal the parts cannot
            # carry. Only when it actually splits: emitting a plain word twice
            # would double its term frequency and bias the ranking silently.
            if len(parts) > 1 and not _emit(sub.lower()):
                return out
        # The snake_case identifier as one term, same reasoning one level up.
        if len(subs) > 1 and not _emit("_".join(s.lower() for s in subs)):
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

    def _safe_name(self, project_id: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_-]", "_", project_id)[:64]

    def _path(self, project_id: str) -> Path:
        return self._dir / f"{self._safe_name(project_id)}.json.gz"

    def _legacy_pickle_path(self, project_id: str) -> Path:
        """Where an older build left its pickle. Only ever deleted, never read."""
        return self._dir / f"{self._safe_name(project_id)}.pkl"

    def _drop_legacy_pickle(self, project_id: str) -> None:
        legacy = self._legacy_pickle_path(project_id)
        try:
            if legacy.exists():
                legacy.unlink()
                logger.info("bm25_index: removed legacy pickle snapshot %s", legacy)
        except OSError:
            logger.warning("bm25_index: could not remove %s", legacy, exc_info=True)

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
            tokenized=tokenized,
        )
        self._persist(project_id, snapshot)
        self._drop_legacy_pickle(project_id)
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
        payload = {
            "schema_version": snapshot.schema_version,
            "project_id": snapshot.project_id,
            "indexed_sha": snapshot.indexed_sha,
            "doc_ids": snapshot.doc_ids,
            "doc_metadatas": snapshot.doc_metadatas,
            "raw_texts": snapshot.raw_texts,
            "tokenized": snapshot.tokenized,
        }
        try:
            with gzip.open(tmp, "wt", encoding="utf-8") as fh:
                json.dump(payload, fh)
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
        return self.load_with_reason(project_id)[0]

    def load_with_reason(self, project_id: str) -> tuple[BM25Snapshot | None, str]:
        """Like :meth:`load`, but say *why* there is no snapshot.

        F-KNOW-07: a missing file means hybrid retrieval is dense-only for this
        project until a reindex — on an ephemeral disk that is every restart. A
        corrupt or stale-schema file means the same thing for a different reason
        and wants a different fix. ``None`` alone could not tell them apart, so
        the caller's degradation metric labelled all of them identically.
        """
        with self._lock:
            cached = self._snapshots.get(project_id)
            if cached is not None:
                return cached, "ok"
            path = self._path(project_id)
            if not path.exists():
                # A leftover `.pkl` is deliberately NOT consulted here: an absent
                # snapshot is the honest answer, and the start-up reconcile rebuilds
                # it from Postgres (F-KNOW-12). Reading the pickle to "migrate" it
                # would keep the primitive alive for exactly the window that matters.
                return None, MISS_NO_SNAPSHOT
            try:
                with gzip.open(path, "rt", encoding="utf-8") as fh:
                    raw = json.load(fh)
            except Exception:
                logger.warning(
                    "bm25_index: failed to load %s (corrupted? rebuilding will fix)",
                    path,
                    exc_info=True,
                )
                return None, MISS_CORRUPT
            if not isinstance(raw, dict):
                logger.warning("bm25_index: %s holds %s, not a snapshot", path, type(raw).__name__)
                return None, MISS_CORRUPT
            if raw.get("schema_version") != _SCHEMA_VERSION:
                logger.info(
                    "bm25_index: schema mismatch for %s (have %s, expected v%d)",
                    project_id[:8],
                    raw.get("schema_version"),
                    _SCHEMA_VERSION,
                )
                return None, MISS_SCHEMA_MISMATCH
            try:
                tokenized = [list(map(str, doc)) for doc in raw["tokenized"]]
                snap = BM25Snapshot(
                    schema_version=_SCHEMA_VERSION,
                    project_id=str(raw["project_id"]),
                    indexed_sha=str(raw["indexed_sha"]),
                    doc_ids=[str(d) for d in raw["doc_ids"]],
                    doc_metadatas=[dict(m) for m in raw["doc_metadatas"]],
                    # Rebuilt from the stored tokens: the corpus is data on disk and
                    # only becomes an object here, in this process.
                    bm25=BM25Okapi(tokenized),
                    raw_texts=[str(t) for t in raw.get("raw_texts", [])],
                    tokenized=tokenized,
                )
            except Exception:
                logger.warning(
                    "bm25_index: %s parsed but does not describe a corpus", path, exc_info=True
                )
                return None, MISS_CORRUPT
            self._snapshots[project_id] = snap
            return snap, "ok"

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
        return self.query_with_reason(project_id, query_text, n_results)[0]

    def query_with_reason(
        self,
        project_id: str,
        query_text: str,
        n_results: int = 20,
    ) -> tuple[list[dict[str, Any]], str]:
        """Like :meth:`query`, plus why the list is empty when it is.

        One of the reasons is healthy: ``no_match`` means the index worked and
        the query had no lexical overlap. Counting that as degradation is what
        made ``retrieval_degraded_total`` unreadable in both directions.
        """
        snap, load_reason = self.load_with_reason(project_id)
        if snap is None:
            return [], load_reason
        tokens = tokenize_code(query_text)
        if not tokens:
            return [], MISS_NO_QUERY_TOKENS
        try:
            scores = snap.bm25.get_scores(tokens)
        except Exception:
            logger.warning("bm25_index: scoring failed for %s", project_id[:8], exc_info=True)
            return [], MISS_SCORE_ERROR
        if not len(scores):
            return [], MISS_NO_MATCH
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
        return out, ("ok" if out else MISS_NO_MATCH)

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
        self._drop_legacy_pickle(project_id)

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
