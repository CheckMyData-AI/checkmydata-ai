"""Tests for CODEIDX-C1: chunks sized to the real embedder window.

Verifies that chunk_document uses the WindowTokenizer to enforce per-chunk
token limits that match the embedder's context window (settings.embedder_max_tokens),
rather than the old hardcoded 1500-token / char-math approach.
"""

from __future__ import annotations

from app.knowledge.chunker import chunk_document
from app.knowledge.tokenizer_window import WindowTokenizer


def test_no_chunk_exceeds_max_tokens() -> None:
    """CODEIDX-C1: every chunk must fit within the supplied max_tokens window."""
    tk = WindowTokenizer("definitely/not-a-real-tokenizer-xyz")  # char fallback
    # ~4000 chars of prose → must split into <=max_tokens chunks.
    text = "The orders table stores each purchase. " * 200
    chunks = chunk_document(
        content=text, file_path="doc.md", doc_type="markdown", max_tokens=128, tokenizer=tk
    )
    assert len(chunks) >= 2
    for c in chunks:
        assert tk.count_tokens(c.content) <= 128, tk.count_tokens(c.content)


def test_small_doc_single_chunk() -> None:
    """A document that fits within max_tokens must produce exactly one chunk."""
    tk = WindowTokenizer("definitely/not-a-real-tokenizer-xyz")
    chunks = chunk_document(
        content="short doc", file_path="d.md", doc_type="markdown", max_tokens=128, tokenizer=tk
    )
    assert len(chunks) == 1
    assert chunks[0].metadata["source_path"] == "d.md"


def test_default_model_is_512_ctx() -> None:
    """CODEIDX-C1 fix: default model is a 512-token model and embedder_max_tokens=512."""
    from app.config import settings

    assert settings.chroma_embedding_model == "BAAI/bge-base-en-v1.5"
    assert settings.embedder_max_tokens == 512


def test_compat_call_no_extra_metadata() -> None:
    """Back-compat: pipeline_runner call shape with no extra_metadata still works."""
    text = "SELECT id, name FROM users;" * 10
    chunks = chunk_document(
        content=text,
        file_path="schema.sql",
        doc_type="sql",
    )
    assert isinstance(chunks, list)
    assert all(hasattr(c, "content") and hasattr(c, "metadata") for c in chunks)


def test_compat_call_with_extra_metadata() -> None:
    """Back-compat: extra_metadata is preserved in chunk metadata."""
    text = "Some markdown content.\n\nAnother paragraph."
    chunks = chunk_document(
        content=text,
        file_path="README.md",
        doc_type="markdown",
        extra_metadata={"commit_sha": "abc123"},
    )
    assert all(c.metadata.get("commit_sha") == "abc123" for c in chunks)


def test_chunk_index_present() -> None:
    """chunk_index metadata key is present when document is split into multiple chunks."""
    tk = WindowTokenizer("definitely/not-a-real-tokenizer-xyz")
    text = "The orders table stores each purchase. " * 200
    chunks = chunk_document(
        content=text, file_path="doc.md", doc_type="markdown", max_tokens=128, tokenizer=tk
    )
    assert len(chunks) >= 2
    for c in chunks:
        assert "chunk_index" in c.metadata


def test_no_chunk_exceeds_window_with_code() -> None:
    """CODEIDX-C1: code-dense text (higher chars/token) must still fit in window."""
    tk = WindowTokenizer("definitely/not-a-real-tokenizer-xyz")
    # SQL-like dense text — conservative fallback chars/token=3 handles this
    text = (
        "SELECT u.id, u.name, o.total FROM users u JOIN orders o ON u.id = o.user_id "
        "WHERE o.created_at > '2024-01-01' ORDER BY o.total DESC; "
    ) * 50
    chunks = chunk_document(
        content=text, file_path="query.sql", doc_type="sql", max_tokens=64, tokenizer=tk
    )
    for c in chunks:
        assert tk.count_tokens(c.content) <= 64, tk.count_tokens(c.content)
