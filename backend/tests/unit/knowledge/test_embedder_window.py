"""The chunker sized for one embedder while a different one did the embedding.

Measured in production on 2026-09-01, 1 500-chunk sample through the project's own
`get_tokenizer`: p50 112 tokens, p90 **490**, max 513 — so chunking respects
`embedder_max_tokens = 512`. But what embeds is ChromaDB's bundled ONNX all-MiniLM-L6-v2,
whose own source does `tokenizer.enable_truncation(max_length=256)`. **434 of 1 500 chunks
(28.9%) exceed that**, and everything past token 256 never reaches the vector — the text
stays in `document` and can be returned once retrieved, but cannot be *found* by the half
that was cut.

Extrapolated over 34 348 rows: roughly 9 900 chunks with a truncated embedding.

The cause was a chain of four things, each individually defensible:

1. `chroma_embedding_model` defaulted to `BAAI/bge-base-en-v1.5` — 768-d, needing the `ml`
   extra, which is in no shipped install.
2. `embedder_max_tokens = 512` is documented as "the real tokenizer context window of
   `chroma_embedding_model`" — true of bge, and it sizes the chunker.
3. The embedder that actually runs truncates at 256.
4. The check that would have noticed sits inside a silenced `except Exception: pass`
   (`vector_store.py:43`).

So the defaults now name the embedder that actually runs, and the 256 is pinned against
ChromaDB's own source rather than copied into a comment.
"""

from __future__ import annotations

import pytest


class TestTheDefaultsDescribeTheEmbedderThatRuns:
    def test_the_default_model_is_the_bundled_one(self) -> None:
        from app.config import Settings
        from app.core.embedder import BUNDLED_EMBEDDING_MODEL

        assert Settings.model_fields["chroma_embedding_model"].default == BUNDLED_EMBEDDING_MODEL

    def test_the_default_window_is_the_bundled_one(self) -> None:
        from app.config import Settings
        from app.core.embedder import BUNDLED_EMBEDDING_MAX_TOKENS

        assert Settings.model_fields["embedder_max_tokens"].default == BUNDLED_EMBEDDING_MAX_TOKENS

    def test_the_window_is_pinned_against_chromadb_itself(self) -> None:
        """Not copied into a comment — read from the installed package. If ChromaDB changes
        its truncation, this fails and a person decides, instead of a quarter of the index
        being silently cut on the next deploy."""
        import inspect
        import re

        chromadb = pytest.importorskip("chromadb.utils.embedding_functions")
        from app.core.embedder import BUNDLED_EMBEDDING_MAX_TOKENS

        src = inspect.getsource(chromadb.ONNXMiniLM_L6_V2)
        found = re.findall(r"enable_truncation\(max_length=(\d+)\)", src)
        assert found, "ChromaDB no longer sets truncation where this test looks for it"
        assert {int(f) for f in found} == {BUNDLED_EMBEDDING_MAX_TOKENS}, (
            f"ChromaDB truncates at {found}, this project chunks to {BUNDLED_EMBEDDING_MAX_TOKENS}"
        )

    def test_the_dimension_is_not_declared_twice(self) -> None:
        """`EMBEDDING_DIM` was a second copy of the same fact. Two homes for one number is
        how the window and the model drifted apart in the first place."""
        from app.core.embedder import EMBEDDING_DIM
        from app.models.doc_embedding import EMBEDDING_DIM as MODEL_DIM

        assert MODEL_DIM is EMBEDDING_DIM


class TestTheCapabilityClaimsOnlyFireForANonBundledModel:
    """Naming the bundled model is not a claim about an extra — it is the truth."""

    def _firing(self):
        from app.ops.capability_report import CLAIMS

        return [c for c in CLAIMS if c.setting == "chroma_embedding_model" and c.asserted()]

    def test_the_bundled_model_raises_no_claim(self, monkeypatch) -> None:
        from app.config import settings
        from app.core.embedder import BUNDLED_EMBEDDING_MODEL

        monkeypatch.setattr(settings, "chroma_embedding_model", BUNDLED_EMBEDDING_MODEL)
        monkeypatch.setattr(
            settings, "database_url", "postgresql+asyncpg://u:p@h/db", raising=False
        )
        monkeypatch.setattr(settings, "vector_store_backend", "auto", raising=False)
        assert self._firing() == [], (
            "the default configuration must not warn about itself; a warning that fires on "
            "every boot of an untouched install is one an operator learns to scroll past"
        )

    def test_a_different_model_still_raises_one(self, monkeypatch) -> None:
        from app.config import settings

        monkeypatch.setattr(settings, "chroma_embedding_model", "BAAI/bge-base-en-v1.5")
        monkeypatch.setattr(
            settings, "database_url", "postgresql+asyncpg://u:p@h/db", raising=False
        )
        monkeypatch.setattr(settings, "vector_store_backend", "auto", raising=False)
        assert len(self._firing()) == 1


def test_changing_either_default_still_triggers_a_rebuild() -> None:
    """Both keys ride `embedding_fingerprint()`, so moving them enqueues one idempotent,
    advisory-locked `force_full` reindex at start-up. Without that the new chunk boundaries
    would apply only to files somebody happens to edit, leaving most of the index cut."""
    from app.ops.embedding_reconcile import embedding_fingerprint

    fp = embedding_fingerprint()
    from app.config import settings

    assert settings.chroma_embedding_model in fp
    assert str(settings.embedder_max_tokens) in fp
