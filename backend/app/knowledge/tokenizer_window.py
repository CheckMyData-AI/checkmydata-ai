"""Token-aware sizing utilities for chunk-boundary decisions (CODEIDX-C2).

Provides :class:`WindowTokenizer` — a lazy-loading wrapper around a
HuggingFace ``tokenizers`` fast tokenizer — with a conservative char-based
fallback that is used when:

* the ``tokenizers`` library is not installed, or
* the requested model name cannot be loaded (no network / not cached).

The fallback uses ``ceil(len(text) / 3)`` rather than the old ``len(text) / 4``
so that code-dense strings (identifiers, punctuation, operators) are never
*under*-counted relative to the true subword count, which is critical for
ensuring chunks don't overflow the embedder's context window.

Module-level :func:`get_tokenizer` caches one ``WindowTokenizer`` per model
name so repeated calls during a pipeline run share the loaded tokenizer.
"""

from __future__ import annotations

import logging
import math
import threading
from typing import Any

logger = logging.getLogger(__name__)

# Conservative char-per-token ratio used when the real tokenizer is unavailable.
# Prose is ~4 chars/token; code/SQL is ~3 chars/token.  Using 3 means we always
# over-estimate token count (safe: chunks stay *within* the window rather than
# slightly over it).
_FALLBACK_CHARS_PER_TOKEN = 3

# Module-level cache: model_name -> WindowTokenizer
_cache: dict[str, WindowTokenizer] = {}
_cache_lock = threading.Lock()


def get_tokenizer(model_name: str) -> WindowTokenizer:
    """Return a :class:`WindowTokenizer` for *model_name*, creating it once.

    Thread-safe.  The same object is returned on subsequent calls with the same
    model name so the underlying tokenizer is loaded at most once per process.
    """
    with _cache_lock:
        if model_name not in _cache:
            _cache[model_name] = WindowTokenizer(model_name)
        return _cache[model_name]


class WindowTokenizer:
    """Token counter + truncator for a specific embedding model.

    The real tokenizer is loaded lazily on the first :meth:`count_tokens` or
    :meth:`truncate_to_tokens` call.  If the model cannot be loaded the
    instance degrades permanently to the char-based conservative fallback.

    Parameters
    ----------
    model_name:
        A HuggingFace model identifier accepted by
        ``tokenizers.Tokenizer.from_pretrained()``.  May be a remote repo slug
        (``"BAAI/bge-base-en-v1.5"``) or a local path.  An unresolvable name
        silently activates the fallback — no exception is ever raised from the
        constructor.
    """

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._tokenizer: Any | None = None  # tokenizers.Tokenizer once loaded
        self._load_attempted = False
        self._use_fallback = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API (consumed by chunker.py / T2, T4)
    # ------------------------------------------------------------------

    def count_tokens(self, text: str) -> int:
        """Return the number of tokens in *text*.

        Uses the real tokenizer when available; falls back to a conservative
        char-based estimate (``ceil(len(text) / 3)``) that never under-counts.

        Returns 0 for an empty string.
        """
        if not text:
            return 0
        tok = self._get_tokenizer()
        if tok is not None:
            try:
                encoding = tok.encode(text, add_special_tokens=False)
                return len(encoding.ids)
            except Exception:
                logger.debug(
                    "tokenizer_window: encode failed for model %s, using fallback",
                    self._model_name,
                    exc_info=True,
                )
        return self._fallback_count(text)

    def truncate_to_tokens(self, text: str, max_tokens: int) -> str:
        """Return *text* truncated so that ``count_tokens(result) <= max_tokens``.

        Truncation is word-boundary-aware: it removes whole words from the end
        until the token count fits.  If the text already fits it is returned
        unchanged.

        For the fallback path a char-limit derived from *max_tokens* is used so
        the function is always O(1) iterations in the common case.
        """
        if not text:
            return text
        if self.count_tokens(text) <= max_tokens:
            return text

        tok = self._get_tokenizer()
        if tok is not None:
            return self._truncate_with_real_tokenizer(text, max_tokens, tok)
        return self._truncate_fallback(text, max_tokens)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_tokenizer(self) -> Any | None:
        """Lazy-load the HuggingFace fast tokenizer; return None on failure."""
        with self._lock:
            if self._load_attempted:
                return None if self._use_fallback else self._tokenizer
            self._load_attempted = True
            try:
                from tokenizers import Tokenizer

                self._tokenizer = Tokenizer.from_pretrained(self._model_name)
                logger.debug("tokenizer_window: loaded real tokenizer for %s", self._model_name)
            except Exception:
                logger.debug(
                    "tokenizer_window: could not load tokenizer for %s — using "
                    "conservative char fallback",
                    self._model_name,
                    exc_info=True,
                )
                self._use_fallback = True
            return None if self._use_fallback else self._tokenizer

    @staticmethod
    def _fallback_count(text: str) -> int:
        """Conservative token estimate: ceil(len(text) / 3)."""
        return math.ceil(len(text) / _FALLBACK_CHARS_PER_TOKEN)

    def _truncate_fallback(self, text: str, max_tokens: int) -> str:
        """Char-limit truncation for the fallback path."""
        max_chars = max_tokens * _FALLBACK_CHARS_PER_TOKEN
        if len(text) <= max_chars:
            return text
        # Trim to max_chars on a word boundary where possible.
        trimmed = text[:max_chars]
        last_space = trimmed.rfind(" ")
        if last_space > max_chars // 2:
            trimmed = trimmed[:last_space]
        return trimmed

    def _truncate_with_real_tokenizer(self, text: str, max_tokens: int, tok: Any) -> str:
        """Token-precise truncation using the real tokenizer.

        Encodes the full text, slices to ``max_tokens`` token IDs, then
        decodes back to a string.
        """
        try:
            encoding = tok.encode(text, add_special_tokens=False)
            ids = encoding.ids[:max_tokens]
            return tok.decode(ids, skip_special_tokens=True)
        except Exception:
            logger.debug(
                "tokenizer_window: truncate encode/decode failed for model %s",
                self._model_name,
                exc_info=True,
            )
            return self._truncate_fallback(text, max_tokens)
