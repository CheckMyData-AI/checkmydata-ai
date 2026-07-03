from __future__ import annotations

from app.config import Settings


def test_max_orchestrator_iterations_default_is_20():
    s = Settings()
    assert s.max_orchestrator_iterations == 20


def test_chroma_embedding_model_defaults_to_512ctx_model():
    s = Settings()
    assert s.chroma_embedding_model == "BAAI/bge-base-en-v1.5"


def test_embedder_max_tokens_default():
    s = Settings()
    assert s.embedder_max_tokens == 512
