"""Validation lock: embedder max_seq_length vs chunker target mismatch (CODEIDX-C1).

Pins the truncation bug: the default ChromaDB ONNX embedder (all-MiniLM-L6-v2) has a
256-token context window, but the chunker targets MAX_CHUNK_TOKENS=1500. This mismatch
means most chunks are silently truncated at indexing time. Wave 2 fixes this by switching
to a 512-token model and sizing chunks to the real window.

These tests PASS today (documenting current reality). Wave 2 will change the default model
and lower MAX_CHUNK_TOKENS, at which point the parametrized model tests still pass (the
new default IS 512), but the chunk-target test will flip.
"""

from __future__ import annotations

import pytest

st = pytest.importorskip("sentence_transformers")

from app.knowledge.chunker import MAX_CHUNK_TOKENS  # noqa: E402  (1500 today)


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


def test_chunk_target_exceeds_minilm_window_documents_c1() -> None:
    # CODEIDX-C1: chunks target 1500 tokens but all-MiniLM-L6-v2 truncates at 256.
    # This inequality is the bug Wave 2 fixes (size chunks to the real window).
    assert MAX_CHUNK_TOKENS > 256
