from __future__ import annotations

from app.config import Settings


def test_max_orchestrator_iterations_default_is_20():
    s = Settings()
    assert s.max_orchestrator_iterations == 20


def test_the_default_model_is_the_one_that_actually_embeds():
    """Renamed from `..._defaults_to_512ctx_model`, because the old name carried the
    mistake: the 512-token model needed an optional extra that no shipped install has, so
    it never embedded anything while the chunker was sized to its window."""
    from app.core.embedder import BUNDLED_EMBEDDING_MODEL

    assert Settings().chroma_embedding_model == BUNDLED_EMBEDDING_MODEL


def test_embedder_max_tokens_matches_that_model():
    """512 -> 256. Not a tightened margin: 512 was the window of a model that never ran,
    and the bundled one truncates at 256, so 28.9% of production chunks (measured over a
    1 500-row sample) had everything past token 256 missing from the vector."""
    from app.core.embedder import BUNDLED_EMBEDDING_MAX_TOKENS

    assert Settings().embedder_max_tokens == BUNDLED_EMBEDDING_MAX_TOKENS
