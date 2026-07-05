"""Validation lock: embedder max_seq_length vs chunker sizing — CODEIDX-C1 fix verified.

Wave 2 (T2) fixed the truncation bug: the default ChromaDB ONNX embedder
(all-MiniLM-L6-v2) had a 256-token context window, but the old chunker targeted
MAX_CHUNK_TOKENS=1500 (char-math), silently dropping ~80% of each large chunk.

The fix (CODEIDX-C1):
  - Default model switched to ``BAAI/bge-base-en-v1.5`` (512-token context).
  - ``settings.embedder_max_tokens = 512`` introduced as the authoritative window.
  - ``chunk_document`` now sizes chunks to the real window via ``WindowTokenizer``.
  - ``MAX_CHUNK_TOKENS`` removed; chunking is no longer char-math based.

These tests VERIFY THE FIX is in place.  Previously the C1 lock asserted
``MAX_CHUNK_TOKENS > 256`` (documenting the bug); that constant no longer exists and
chunks are now guaranteed to fit the embedder window.

NOTE: previously-embedded ChromaDB collections indexed under the old model/chunker
must be re-indexed to benefit from this fix (see T3 reindex check / Wave 2 runbook).
"""

from __future__ import annotations

import pytest

st = pytest.importorskip("sentence_transformers")


@pytest.mark.parametrize(
    "model_name, expected_window",
    [
        ("sentence-transformers/all-MiniLM-L6-v2", 256),
        ("BAAI/bge-base-en-v1.5", 512),
    ],
)
def test_embedder_context_window(model_name: str, expected_window: int) -> None:
    """Lock the max_seq_length for shipped and target embedder models."""
    try:
        model = st.SentenceTransformer(model_name)
    except Exception as exc:  # offline / model download blocked
        pytest.skip(f"model {model_name} unavailable: {exc}")
    assert model.max_seq_length == expected_window


def test_chunk_target_fits_embedder_window_verifies_c1_fix() -> None:
    """CODEIDX-C1 FIX verified: chunker no longer targets tokens > embedder window.

    The old MAX_CHUNK_TOKENS=1500 constant has been removed.  The new approach
    resolves chunk size from settings.embedder_max_tokens (512) at call time.
    This test asserts the fix is in place: chunk_document accepts a max_tokens
    parameter and produces chunks that fit within the supplied window.
    """
    from app.config import settings
    from app.knowledge.chunker import chunk_document
    from app.knowledge.tokenizer_window import WindowTokenizer

    # Confirm settings are correct (bge-base-en-v1.5 = 512 tokens)
    assert settings.embedder_max_tokens == 512
    assert settings.chroma_embedding_model == "BAAI/bge-base-en-v1.5"

    # Verify chunk_document actually respects the window — use char fallback tokenizer
    tk = WindowTokenizer("definitely/not-a-real-tokenizer-xyz")
    text = "The orders table stores each purchase. " * 200  # ~4000 chars
    max_tokens = settings.embedder_max_tokens  # 512
    chunks = chunk_document(
        content=text,
        file_path="doc.md",
        doc_type="markdown",
        max_tokens=max_tokens,
        tokenizer=tk,
    )
    # Every chunk must fit within the embedder window (CODEIDX-C1 fix)
    for c in chunks:
        token_count = tk.count_tokens(c.content)
        assert token_count <= max_tokens, (
            f"CODEIDX-C1 regression: chunk has {token_count} tokens, "
            f"exceeds embedder window of {max_tokens}"
        )
