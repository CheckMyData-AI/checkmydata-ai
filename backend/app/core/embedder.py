"""Facts about the embedder that actually runs. One home, no imports.

A leaf module on purpose. `config.py` imports nothing from `app`, and
`models/base.py` imports `app.config`, so putting these beside `DocEmbedding`
would make the chain circular — and copying them into `config.py` is what caused
the defect this module exists to prevent.

**The defect, measured in production on 2026-09-01.** `chroma_embedding_model`
defaulted to ``BAAI/bge-base-en-v1.5`` (768-d, needs the optional ``ml`` extra,
which is in no shipped install), and ``embedder_max_tokens = 512`` was documented
as "the real tokenizer context window of ``chroma_embedding_model``" — true of
bge, and it is the number the chunker sizes to. What embeds is ChromaDB's bundled
ONNX ``all-MiniLM-L6-v2``, whose own source does
``tokenizer.enable_truncation(max_length=256)``.

So chunks were built for a 512-token window and embedded by a 256-token model.
On a 1 500-chunk sample through the project's own tokenizer: p50 112, p90 **490**,
max 513 — **434 (28.9%) over 256**, roughly 9 900 of 34 348 rows. Everything past
token 256 in those chunks never reached the vector: the text stays in ``document``
and is returned once retrieved, but cannot be *found* by the half that was cut.

Nothing crashed, and nothing was going to. The check that compares the configured
window against the model's real one sits inside a silenced ``except Exception:
pass`` (``vector_store.py:43``).
"""

from __future__ import annotations

#: ChromaDB's bundled ONNX embedder — what runs unless the optional ``ml`` extra is
#: installed AND a different model is configured. Named rather than left blank so the
#: chunker's tokenizer has a real model to count with; a blank name degrades
#: ``WindowTokenizer`` to ``ceil(len(text) / 3)`` for every chunk.
BUNDLED_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

#: Its hard truncation limit, pinned against ChromaDB's own source rather than
#: restated from memory — `test_the_window_is_pinned_against_chromadb_itself` reads
#: `enable_truncation(max_length=...)` out of the installed package and fails if
#: upstream moves it. 256, not the 512 in the HF config: ChromaDB's own comment says
#: "sentence-transformers uses 256 even though the HF config has" more.
BUNDLED_EMBEDDING_MAX_TOKENS = 256

#: Dimensions it produces. Asserted at write time — a mismatch is a silently wrong
#: index rather than a crash, so it is checked.
EMBEDDING_DIM = 384

__all__ = [
    "BUNDLED_EMBEDDING_MAX_TOKENS",
    "BUNDLED_EMBEDDING_MODEL",
    "EMBEDDING_DIM",
]
