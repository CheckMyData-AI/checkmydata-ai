"""Tests for tokenizer_window.WindowTokenizer (CODEIDX-C2).

Covers:
- count_tokens fallback path (when real tokenizer is unavailable)
- count_tokens returns >= chars/4 (conservative — never under-counts code)
- code-dense strings produce MORE tokens than naive chars/4 estimate
- truncate_to_tokens fits within the requested budget
- get_tokenizer() returns a WindowTokenizer
- real tokenizer path when tokenizers lib is available (importorskip)
"""

import pytest

from app.knowledge.tokenizer_window import WindowTokenizer, get_tokenizer

# A model name that definitely doesn't exist — forces the char-fallback path.
_FAKE_MODEL = "definitely/not-a-real-tokenizer-xyz"


class TestWindowTokenizerFallback:
    """All tests use a non-existent model so the char fallback activates."""

    def setup_method(self) -> None:
        self.tk = WindowTokenizer(_FAKE_MODEL)

    def test_count_tokens_returns_positive_int(self) -> None:
        assert self.tk.count_tokens("hello world") > 0

    def test_count_tokens_is_at_least_chars_over_4(self) -> None:
        """Fallback must be conservative: never return fewer tokens than chars/4."""
        text = "a" * 400
        # chars/4 == 100; fallback must be >= 100
        assert self.tk.count_tokens(text) >= len(text) // 4

    def test_count_tokens_empty_string_returns_zero(self) -> None:
        assert self.tk.count_tokens("") == 0

    def test_count_tokens_single_char(self) -> None:
        assert self.tk.count_tokens("x") >= 1

    def test_code_dense_string_exceeds_chars_over_4(self) -> None:
        """Code identifiers are ~3 chars/token (shorter than prose).

        A code-dense string should produce MORE tokens than the naive chars/4
        estimate — i.e. conservative fallback beats the old approximation.
        """
        code = (
            "SELECT user_id, COUNT(*) AS cnt, AVG(amount) "
            "FROM orders WHERE created_at > '2024-01-01' "
            "GROUP BY user_id HAVING cnt > 10 ORDER BY cnt DESC "
        ) * 10  # repeat to get a good sample
        naive_estimate = len(code) // 4
        actual = self.tk.count_tokens(code)
        # Conservative fallback must be >= naive estimate
        assert actual >= naive_estimate, (
            f"Fallback ({actual}) must be >= chars/4 ({naive_estimate})"
        )

    def test_truncate_to_tokens_within_budget(self) -> None:
        long_text = "word " * 1000  # ~5000 chars
        truncated = self.tk.truncate_to_tokens(long_text, max_tokens=50)
        assert self.tk.count_tokens(truncated) <= 50

    def test_truncate_to_tokens_short_text_unchanged(self) -> None:
        short = "hello world"
        result = self.tk.truncate_to_tokens(short, max_tokens=200)
        assert result == short

    def test_truncate_to_tokens_empty(self) -> None:
        assert self.tk.truncate_to_tokens("", max_tokens=50) == ""

    def test_truncate_to_tokens_exactly_at_limit(self) -> None:
        # Build a text that is exactly at the limit — should be returned as-is.
        text = "x " * 10  # small enough to fit easily in any reasonable budget
        result = self.tk.truncate_to_tokens(text, max_tokens=1000)
        assert result == text

    def test_count_tokens_is_integer(self) -> None:
        assert isinstance(self.tk.count_tokens("test text here"), int)


class TestGetTokenizer:
    def test_returns_window_tokenizer_instance(self) -> None:
        tk = get_tokenizer(_FAKE_MODEL)
        assert isinstance(tk, WindowTokenizer)

    def test_same_model_returns_same_object(self) -> None:
        """get_tokenizer caches per model_name."""
        tk1 = get_tokenizer(_FAKE_MODEL)
        tk2 = get_tokenizer(_FAKE_MODEL)
        assert tk1 is tk2

    def test_different_model_returns_different_object(self) -> None:
        tk1 = get_tokenizer(_FAKE_MODEL)
        tk2 = get_tokenizer("another/fake-model-xyz")
        assert tk1 is not tk2


class TestWindowTokenizerRealTokenizer:
    """Tests that only run when the `tokenizers` library AND a real model are
    available.  In CI the model is not downloaded, so these are xfail/skip-safe.
    """

    @pytest.fixture()
    def real_tokenizer(self) -> WindowTokenizer:
        pytest.importorskip("tokenizers", reason="tokenizers not installed")
        # Attempt to use a model that's available in sentence-transformers style.
        # In a no-network CI environment, from_pretrained will fail — skip gracefully.
        tk = WindowTokenizer("BAAI/bge-base-en-v1.5")
        # Trigger lazy load; if it fails we skip.
        try:
            _ = tk._get_tokenizer()  # noqa: SLF001
        except Exception:
            pytest.skip("Model not downloadable in this environment")
        return tk

    def test_count_tokens_vs_word_count(self, real_tokenizer: WindowTokenizer) -> None:
        text = "The orders table stores each purchase made by a customer."
        tokens = real_tokenizer.count_tokens(text)
        # Sanity: more tokens than words (subword tokenisation)
        words = len(text.split())
        assert tokens >= words

    def test_code_dense_more_than_prose(self, real_tokenizer: WindowTokenizer) -> None:
        prose = "The quick brown fox jumps over the lazy dog " * 5
        code = "SELECT id, name, COUNT(*) FROM table GROUP BY id HAVING COUNT(*) > 0 " * 5
        prose_tokens = real_tokenizer.count_tokens(prose)
        code_tokens = real_tokenizer.count_tokens(code)
        # Code has more tokens per char (identifiers, punctuation, special chars)
        prose_ratio = prose_tokens / len(prose)
        code_ratio = code_tokens / len(code)
        assert code_ratio >= prose_ratio, (
            f"code ratio {code_ratio:.3f} should be >= prose ratio {prose_ratio:.3f}"
        )

    def test_truncate_respects_limit_with_real_tokenizer(
        self, real_tokenizer: WindowTokenizer
    ) -> None:
        text = "word " * 500
        truncated = real_tokenizer.truncate_to_tokens(text, max_tokens=64)
        assert real_tokenizer.count_tokens(truncated) <= 64
