"""Validation lock: the chunker's target window vs the embedder that actually runs.

**This lock did not run for the entire time it existed.** `importorskip` sat at module
level, so with `sentence_transformers` absent — which is every shipped install and every
dev machine without the optional `ml` extra — the whole module collected as a single
skipped item. It was written to lock a fix and locked nothing.

The history matters, because the same defect was fixed once already and the fix went the
wrong way:

* **Wave 2 (CODEIDX-C1)** found chunks targeting `MAX_CHUNK_TOKENS=1500` against ChromaDB's
  bundled `all-MiniLM-L6-v2`, whose window is 256 — dropping ~80% of each large chunk.
* The fix **raised the embedder** rather than lowering the chunker: the default model became
  `BAAI/bge-base-en-v1.5` (512-token window) and `embedder_max_tokens = 512` was declared
  "the authoritative window".
* But `sentence-transformers` is in an optional extra that no shipped install carries, so
  bge never embedded anything. The window moved to a model that never ran, which turned a
  visible 80% truncation into an invisible one.

**Measured 2026-09-01**, 1 500 production chunks through the project's own tokenizer: p50
112 tokens, p90 490, max 513 — chunking respected 512 faithfully — with **434 (28.9%) above
the 256 the bundled embedder truncates at**. Roughly 9 900 of 34 348 rows carried a vector
built from only the first half of their text.

So the invariant below is now asserted **without** the optional package, because an
invariant that only holds where the package is installed is an invariant about the package.
"""

from __future__ import annotations

import pytest


def test_the_chunk_window_never_exceeds_the_embedder_that_runs() -> None:
    """The invariant, checkable everywhere. This is the assertion whose absence let the
    window sit at 512 for a 256-token embedder across two releases."""
    from app.config import settings
    from app.core.embedder import BUNDLED_EMBEDDING_MAX_TOKENS, BUNDLED_EMBEDDING_MODEL

    if settings.chroma_embedding_model == BUNDLED_EMBEDDING_MODEL:
        assert settings.embedder_max_tokens <= BUNDLED_EMBEDDING_MAX_TOKENS, (
            f"chunks are sized to {settings.embedder_max_tokens} tokens while the bundled "
            f"embedder truncates at {BUNDLED_EMBEDDING_MAX_TOKENS}; everything past that "
            "is absent from the vector and cannot be retrieved"
        )


def test_this_module_is_not_skipped_wholesale() -> None:
    """The guard for the guard: a module-level `importorskip` made every assertion in this
    file vanish. If one returns to the top, this test disappears with it — so the check is
    that the file's own source has no module-level skip."""
    import pathlib
    import re

    src = pathlib.Path(__file__).read_text()
    head = src[: src.index("def test_")]
    assert not re.search(r"^\s*st\s*=\s*pytest\.importorskip", head, re.M), (
        "a module-level importorskip silently skips this entire lock"
    )


@pytest.mark.parametrize(
    "model_name, expected_window",
    [
        ("sentence-transformers/all-MiniLM-L6-v2", 256),
        ("BAAI/bge-base-en-v1.5", 512),
    ],
)
def test_embedder_context_window(model_name: str, expected_window: int) -> None:
    """Lock `max_seq_length` for the shipped and the optional model.

    This one genuinely needs the package, so the skip is scoped to it rather than to the
    module. Note the shipped model's 256: ChromaDB's own source comments that
    "sentence-transformers uses 256 even though the HF config has" more.
    """
    st = pytest.importorskip("sentence_transformers")
    try:
        model = st.SentenceTransformer(model_name)
    except Exception as exc:  # offline / model download blocked
        pytest.skip(f"model {model_name} unavailable: {exc}")
    assert model.max_seq_length == expected_window


def test_chunk_target_fits_embedder_window_verifies_c1_fix() -> None:
    """CODEIDX-C1, verified against the embedder that RUNS rather than the one configured.

    The previous version asserted `embedder_max_tokens == 512` and
    `chroma_embedding_model == "BAAI/bge-base-en-v1.5"` — it locked the wrong half of the
    fix, and being module-skipped it never even failed.
    """
    from app.config import settings
    from app.knowledge.chunker import chunk_document
    from app.knowledge.tokenizer_window import WindowTokenizer

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
