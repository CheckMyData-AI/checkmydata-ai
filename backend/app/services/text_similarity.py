"""Text-similarity helpers used for semantic deduplication (T13).

This module centralises two strategies so callers can pick the best one
available at runtime:

* ``encode_batch`` / ``cosine_similarity`` — sentence-transformer embeddings
  when a model is configured and loadable. Cached per process via a thread-
  safe singleton so we pay the cold-start cost only once.
* ``jaccard_overlap`` — a cheap word-set fallback suitable when embeddings
  are disabled or unavailable (e.g. CI).

The embedding model is intentionally loaded lazily so unit tests can run
without downloading weights.
"""

from __future__ import annotations

import logging
import math
import threading
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_model_lock = threading.Lock()
_model: Any = None
_model_failed: bool = False


def _load_model() -> Any | None:
    """Return a cached ``SentenceTransformer`` instance or ``None`` if unavailable."""
    global _model, _model_failed
    if _model is not None:
        return _model
    if _model_failed:
        return None
    model_name = settings.tool_dedup_embedding_model or settings.chroma_embedding_model
    if not model_name:
        return None
    with _model_lock:
        if _model is not None:
            return _model
        if _model_failed:
            return None
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]

            _model = SentenceTransformer(model_name)
            logger.info("text_similarity: loaded embedding model %s", model_name)
            return _model
        except Exception:
            logger.warning(
                "text_similarity: failed to load embedding model %s; "
                "falling back to word-overlap",
                model_name,
                exc_info=True,
            )
            _model_failed = True
            return None


def encode_batch(texts: list[str]) -> list[list[float]] | None:
    """Encode a batch of texts. Returns ``None`` when embeddings are unavailable."""
    if not texts:
        return []
    model = _load_model()
    if model is None:
        return None
    try:
        vectors = model.encode(texts, normalize_embeddings=True, convert_to_numpy=False)
    except Exception:
        logger.warning("text_similarity: encode_batch failed", exc_info=True)
        return None

    out: list[list[float]] = []
    for v in vectors:
        try:
            out.append([float(x) for x in v])
        except Exception:
            return None
    return out


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity on two vectors. Assumes normalised vectors when possible."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=False):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0 or nb == 0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def jaccard_overlap(a: str, b: str) -> float:
    """Word-set Jaccard similarity used as a cheap fallback."""
    wa = {w for w in a.lower().split() if w}
    wb = {w for w in b.lower().split() if w}
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def _difflib_ratio(a: str, b: str) -> float:
    """Character-level similarity using :class:`difflib.SequenceMatcher`.

    Historically our fallback similarity metric; preserved as the last-ditch
    option when embeddings are unavailable so dedup accuracy does not regress.
    """
    from difflib import SequenceMatcher  # local import — only used on fallback

    return SequenceMatcher(None, a, b).ratio()


def semantic_similarity(a: str, b: str) -> float:
    """Best-available similarity between two strings (T21).

    Uses embeddings when a model is loaded, otherwise falls back to the
    character-level ``difflib`` ratio for backwards compatibility.
    Lower-casing and stripping is the caller's responsibility.
    """
    vectors = encode_batch([a, b])
    if vectors is not None and len(vectors) == 2:
        return cosine_similarity(vectors[0], vectors[1])
    return _difflib_ratio(a, b)


def semantic_best_match(
    target: str,
    candidates: list[str],
    *,
    threshold: float = 0.0,
) -> tuple[int, float] | None:
    """Return ``(index, score)`` of the best-matching candidate (T21).

    Uses a single embedding batch for ``[target] + candidates`` when
    embeddings are available; this is ~O(n) and far cheaper than running
    ``SequenceMatcher`` in a Python loop. Falls back to ``difflib`` per
    candidate when embeddings are unavailable.
    """
    if not candidates:
        return None

    vectors = encode_batch([target, *candidates])
    if vectors is not None and len(vectors) == len(candidates) + 1:
        target_vec = vectors[0]
        best_idx = -1
        best_score = -1.0
        for idx, vec in enumerate(vectors[1:]):
            score = cosine_similarity(target_vec, vec)
            if score > best_score:
                best_score = score
                best_idx = idx
        if best_idx >= 0 and best_score >= threshold:
            return best_idx, best_score
        return None

    best_idx = -1
    best_score = -1.0
    for idx, cand in enumerate(candidates):
        score = _difflib_ratio(target, cand)
        if score > best_score:
            best_score = score
            best_idx = idx
    if best_idx >= 0 and best_score >= threshold:
        return best_idx, best_score
    return None


def reset_for_tests() -> None:
    """Clear the cached model — test-only helper."""
    global _model, _model_failed
    with _model_lock:
        _model = None
        _model_failed = False
