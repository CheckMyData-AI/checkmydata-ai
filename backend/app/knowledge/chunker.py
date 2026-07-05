"""Semantic chunking for vector store documents.

Splits documents by class/model boundaries to produce chunks that embed well
and retrieve meaningfully.  As of CODEIDX-C1 (Wave 2) chunks are sized to the
*real* embedder token window (``settings.embedder_max_tokens``) via the
``WindowTokenizer`` from :mod:`app.knowledge.tokenizer_window`, replacing the
old char-math approximation.

Back-compat shim: the original positional/keyword call shape used by
``pipeline_runner.py`` is preserved — callers that do not pass ``max_tokens``
or ``tokenizer`` get sensible defaults resolved from ``settings``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# CODEIDX-C1: target ≈ 55% of the embedder window to leave headroom for the
# overlap prefix and for documents whose char/token ratio is higher than prose.
TARGET_CHUNK_FRACTION = 0.55

# Number of tokens prepended from the previous chunk as overlap context.
OVERLAP_TOKENS = 40

# ---------------------------------------------------------------------------
# NOTE: MAX_CHUNK_TOKENS is intentionally removed.  It was 1500, which was
# larger than the 512-token bge-base-en-v1.5 window → CODEIDX-C1 bug.
# The effective limit is now resolved from settings.embedder_max_tokens at
# call time.  See test_embedder_window_validation.py for the flipped C1 lock.
# ---------------------------------------------------------------------------

CLASS_BOUNDARY = re.compile(r"^(?:class |## |### |model |\bCREATE TABLE\b)", re.MULTILINE)


@dataclass
class Chunk:
    content: str
    metadata: dict


def chunk_document(
    content: str,
    file_path: str,
    doc_type: str,
    extra_metadata: dict | None = None,
    *,
    max_tokens: int | None = None,
    tokenizer=None,
) -> list[Chunk]:
    """Split a document into semantic chunks sized to the embedder window.

    Parameters
    ----------
    content:
        Raw text to chunk.
    file_path:
        Source path attached to every chunk's metadata (``source_path``).
    doc_type:
        Document type tag attached to every chunk's metadata (``doc_type``).
    extra_metadata:
        Additional key/value pairs merged into every chunk's metadata.
    max_tokens:
        Maximum tokens per chunk (inclusive).  When *None*, resolved from
        ``settings.embedder_max_tokens`` (default 512).
    tokenizer:
        A :class:`~app.knowledge.tokenizer_window.WindowTokenizer` instance.
        When *None*, resolved via :func:`~app.knowledge.tokenizer_window.get_tokenizer`
        for ``settings.chroma_embedding_model``.

    Strategy
    --------
    1. Split on class/model/heading/SQL boundaries.
    2. Merge small consecutive sections up to ``target_tokens``.
    3. Split oversized sections at paragraph boundaries; hard-truncate any
       single paragraph that still exceeds *max_tokens*.
    4. Prepend an overlap prefix (≤ ``OVERLAP_TOKENS`` tokens) from the
       previous chunk for retrieval continuity.
    """
    # Resolve defaults lazily so settings/tokenizer are only imported when needed.
    if max_tokens is None or tokenizer is None:
        from app.config import settings
        from app.knowledge.tokenizer_window import get_tokenizer

        if max_tokens is None:
            max_tokens = settings.embedder_max_tokens
        if tokenizer is None:
            tokenizer = get_tokenizer(settings.chroma_embedding_model)

    base_meta = {"source_path": file_path, "doc_type": doc_type}
    if extra_metadata:
        base_meta.update(extra_metadata)

    if not content.strip():
        return []

    target_tokens = max(1, int(max_tokens * TARGET_CHUNK_FRACTION))

    # Fast path: entire document fits within the window.
    if tokenizer.count_tokens(content) <= max_tokens:
        return [Chunk(content=content, metadata={**base_meta, "chunk_index": "0"})]

    sections = _split_at_boundaries(content)
    merged = _merge_small_sections(sections, target_tokens, tokenizer)

    raw_chunks: list[str] = []
    for section in merged:
        if tokenizer.count_tokens(section) > max_tokens:
            raw_chunks.extend(_split_large_section(section, max_tokens, tokenizer))
        else:
            raw_chunks.append(section)

    chunks: list[Chunk] = []
    for i, text in enumerate(raw_chunks):
        overlap_prefix = ""
        if i > 0 and OVERLAP_TOKENS > 0:
            prev = raw_chunks[i - 1]
            # Take the tail of the previous chunk and truncate to OVERLAP_TOKENS.
            # Use a conservative estimate: overlap_chars is the last portion of prev.
            overlap_chars = OVERLAP_TOKENS * 3  # conservative: 3 chars/token
            tail = prev[-overlap_chars:] if len(prev) > overlap_chars else prev
            overlap_prefix = tokenizer.truncate_to_tokens(tail, OVERLAP_TOKENS)

        if overlap_prefix:
            combined = (overlap_prefix + text).strip()
            # If the overlap pushes us over the window, trim the body text to fit.
            # This guarantees the invariant: count_tokens(chunk_text) <= max_tokens.
            if tokenizer.count_tokens(combined) > max_tokens:
                # Reserve tokens for overlap, body gets whatever remains.
                overlap_tokens_used = tokenizer.count_tokens(overlap_prefix)
                body_budget = max(1, max_tokens - overlap_tokens_used)
                body = tokenizer.truncate_to_tokens(text.strip(), body_budget)
                chunk_text = (overlap_prefix + body).strip()
            else:
                chunk_text = combined
        else:
            chunk_text = text.strip()

        if chunk_text:
            meta = {**base_meta, "chunk_index": str(i)}
            chunks.append(Chunk(content=chunk_text, metadata=meta))

    return chunks


def _split_at_boundaries(content: str) -> list[str]:
    positions = [m.start() for m in CLASS_BOUNDARY.finditer(content)]
    if not positions:
        return [content]

    sections: list[str] = []
    starts = [0] + positions
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(content)
        section = content[start:end]
        if section.strip():
            sections.append(section)
    return sections


def _merge_small_sections(
    sections: list[str],
    target_tokens: int,
    tokenizer,
) -> list[str]:
    """Merge consecutive sections whose combined token count stays under *target_tokens*."""
    merged: list[str] = []
    buf = ""
    for section in sections:
        if buf and (tokenizer.count_tokens(buf) + tokenizer.count_tokens(section) > target_tokens):
            merged.append(buf)
            buf = section
        else:
            buf = buf + section if buf else section
    if buf:
        merged.append(buf)
    return merged


def _split_large_section(text: str, max_tokens: int, tokenizer) -> list[str]:
    """Split *text* at paragraph then sentence boundaries so each piece fits within
    *max_tokens*.

    Strategy (coarsest → finest granularity):
    1. Split on double-newlines (paragraph boundaries).
    2. For any paragraph still over *max_tokens*, split on sentence boundaries
       (``". "`` / ``".\n"``).
    3. For any sentence still over *max_tokens* (dense single-line text),
       split on spaces (word boundaries) by accumulating words until the limit.

    This ensures the returned list always satisfies
    ``tokenizer.count_tokens(chunk) <= max_tokens``.
    """
    # Phase 1: paragraph split → merge/accumulate within window
    paras = re.split(r"\n\n+", text)
    parts: list[str] = []
    cur = ""
    for para in paras:
        cand = (cur + "\n\n" + para) if cur else para
        if cur and tokenizer.count_tokens(cand) > max_tokens:
            parts.append(cur)
            cur = para
        else:
            cur = cand
    if cur:
        parts.append(cur)

    # Phase 2/3: recursively break any piece still over the limit
    result: list[str] = []
    for piece in parts:
        if tokenizer.count_tokens(piece) <= max_tokens:
            result.append(piece)
        else:
            result.extend(_split_oversized_paragraph(piece, max_tokens, tokenizer))
    return result


def _split_oversized_paragraph(text: str, max_tokens: int, tokenizer) -> list[str]:
    """Break a single oversized paragraph at sentence then word boundaries."""
    # Phase 2: sentence-level split
    sentences = re.split(r"(?<=\. )|\n", text)
    parts: list[str] = []
    cur = ""
    for sent in sentences:
        if not sent:
            continue
        cand = (cur + " " + sent) if cur else sent
        if cur and tokenizer.count_tokens(cand) > max_tokens:
            parts.append(cur)
            cur = sent
        else:
            cur = cand
    if cur:
        parts.append(cur)

    # Phase 3: word-level split for any sentence still over the limit
    result: list[str] = []
    for piece in parts:
        if tokenizer.count_tokens(piece) <= max_tokens:
            result.append(piece)
        else:
            # Word-level accumulation
            words = piece.split(" ")
            buf = ""
            for word in words:
                cand = (buf + " " + word) if buf else word
                if buf and tokenizer.count_tokens(cand) > max_tokens:
                    result.append(buf)
                    buf = word
                else:
                    buf = cand
            if buf:
                result.append(buf)
    return result
