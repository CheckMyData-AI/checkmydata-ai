"""Tests for :mod:`app.services.text_similarity` (T13)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services import text_similarity


class TestJaccard:
    def test_identical_strings_full_overlap(self):
        assert text_similarity.jaccard_overlap("a b c", "a b c") == 1.0

    def test_disjoint_zero(self):
        assert text_similarity.jaccard_overlap("a b", "c d") == 0.0

    def test_partial(self):
        assert 0.2 < text_similarity.jaccard_overlap("a b c", "b c d") < 1.0

    def test_empty_safe(self):
        assert text_similarity.jaccard_overlap("", "a") == 0.0


class TestCosine:
    def test_identical_vectors(self):
        v = [0.5, 0.5, 0.5, 0.5]
        assert abs(text_similarity.cosine_similarity(v, v) - 1.0) < 1e-6

    def test_orthogonal(self):
        assert text_similarity.cosine_similarity([1, 0], [0, 1]) == 0.0

    def test_zero_safe(self):
        assert text_similarity.cosine_similarity([0, 0], [1, 1]) == 0.0


class TestEncodeBatch:
    def test_returns_none_when_no_model_configured(self, monkeypatch):
        text_similarity.reset_for_tests()
        monkeypatch.setattr(
            text_similarity.settings, "tool_dedup_embedding_model", ""
        )
        monkeypatch.setattr(
            text_similarity.settings, "chroma_embedding_model", ""
        )
        assert text_similarity.encode_batch(["hello"]) is None

    def test_returns_none_when_model_load_fails(self, monkeypatch):
        text_similarity.reset_for_tests()
        monkeypatch.setattr(
            text_similarity.settings, "tool_dedup_embedding_model", "nonexistent-model"
        )

        def _raise(*args, **kwargs):
            raise RuntimeError("boom")

        class _StubST:
            SentenceTransformer = _raise

        with patch.dict(
            "sys.modules",
            {"sentence_transformers": _StubST},
        ):
            assert text_similarity.encode_batch(["hello"]) is None

    def test_uses_model_when_available(self, monkeypatch):
        text_similarity.reset_for_tests()
        monkeypatch.setattr(
            text_similarity.settings, "tool_dedup_embedding_model", "fake-model"
        )

        stub_model = MagicMock()
        stub_model.encode.return_value = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]

        class _StubST:
            SentenceTransformer = MagicMock(return_value=stub_model)

        with patch.dict("sys.modules", {"sentence_transformers": _StubST}):
            out = text_similarity.encode_batch(["a", "b"])

        assert out == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
        text_similarity.reset_for_tests()


class TestSemanticSimilarity:
    def test_falls_back_to_difflib_without_model(self, monkeypatch):
        text_similarity.reset_for_tests()
        monkeypatch.setattr(text_similarity.settings, "tool_dedup_embedding_model", "")
        monkeypatch.setattr(text_similarity.settings, "chroma_embedding_model", "")
        score = text_similarity.semantic_similarity("hello world", "hello world!")
        assert score > 0.8

    def test_different_strings_lower_score(self, monkeypatch):
        text_similarity.reset_for_tests()
        monkeypatch.setattr(text_similarity.settings, "tool_dedup_embedding_model", "")
        monkeypatch.setattr(text_similarity.settings, "chroma_embedding_model", "")
        assert text_similarity.semantic_similarity("abc", "xyz") < 0.3


class TestSemanticBestMatch:
    def test_empty_candidates(self):
        assert text_similarity.semantic_best_match("x", []) is None

    def test_picks_closest_candidate_with_difflib(self, monkeypatch):
        text_similarity.reset_for_tests()
        monkeypatch.setattr(text_similarity.settings, "tool_dedup_embedding_model", "")
        monkeypatch.setattr(text_similarity.settings, "chroma_embedding_model", "")
        match = text_similarity.semantic_best_match(
            "hello world",
            ["goodbye", "hello world!", "totally different"],
            threshold=0.5,
        )
        assert match is not None
        idx, score = match
        assert idx == 1
        assert score > 0.8

    def test_threshold_filters_out_poor_matches(self, monkeypatch):
        text_similarity.reset_for_tests()
        monkeypatch.setattr(text_similarity.settings, "tool_dedup_embedding_model", "")
        monkeypatch.setattr(text_similarity.settings, "chroma_embedding_model", "")
        assert (
            text_similarity.semantic_best_match("xyz", ["abc", "def"], threshold=0.9)
            is None
        )
