from unittest.mock import AsyncMock, MagicMock

import pytest

from app.knowledge.doc_generator import (
    DocGenerator,
    _is_binary_content,
    _sanitize_content,
)
from app.llm.base import LLMResponse


class TestDocGenerator:
    @pytest.mark.asyncio
    async def test_generate_returns_llm_output(self):
        mock_router = MagicMock()
        mock_router.complete = AsyncMock(
            return_value=LLMResponse(
                content=(
                    "## users\nStores user accounts.\n\n"
                    "| Column | Description |\n|---|---|\n| id | Primary key |"
                ),
            )
        )
        gen = DocGenerator(llm_router=mock_router)

        result = await gen.generate(
            file_path="models/user.py",
            content="class User(Base):\n    id = Column(Integer, primary_key=True)",
            doc_type="orm_model",
        )
        assert "users" in result
        assert "Primary key" in result
        mock_router.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_falls_back_on_error(self):
        mock_router = MagicMock()
        mock_router.complete = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
        gen = DocGenerator(llm_router=mock_router)

        raw = "class User(Base):\n    id = Column(Integer)"
        result = await gen.generate(
            file_path="models/user.py",
            content=raw,
            doc_type="orm_model",
        )
        assert result == raw

    @pytest.mark.asyncio
    async def test_generate_truncates_long_content(self):
        mock_router = MagicMock()
        mock_router.complete = AsyncMock(return_value=LLMResponse(content="Summary"))
        gen = DocGenerator(llm_router=mock_router)

        long_content = "x" * 20000
        result = await gen.generate("big.py", long_content, "orm_model")
        assert result == "Summary"
        call_args = mock_router.complete.call_args
        prompt_content = call_args[1]["messages"][0].content
        assert "truncated" in prompt_content

    @pytest.mark.asyncio
    async def test_fallback_returns_placeholder_for_binary_content(self):
        mock_router = MagicMock()
        mock_router.complete = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
        gen = DocGenerator(llm_router=mock_router)

        binary_ish = "\x01\x02\x03\x04\x05" * 300
        result = await gen.generate("binary.dat", binary_ish, "orm_model")
        assert "Binary or non-text content" in result

    @pytest.mark.asyncio
    async def test_fallback_truncates_oversized_content(self):
        mock_router = MagicMock()
        mock_router.complete = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
        gen = DocGenerator(llm_router=mock_router)

        huge = "x" * 100_000
        result = await gen.generate("huge.py", huge, "orm_model")
        assert len(result) == 50_000

    @pytest.mark.asyncio
    async def test_null_bytes_stripped_before_llm_call(self):
        mock_router = MagicMock()
        mock_router.complete = AsyncMock(return_value=LLMResponse(content="Clean doc"))
        gen = DocGenerator(llm_router=mock_router)

        content_with_nulls = "class User:\x00\x00    pass"
        result = await gen.generate("models.py", content_with_nulls, "orm_model")
        assert result == "Clean doc"
        call_args = mock_router.complete.call_args
        prompt = call_args[1]["messages"][0].content
        assert "\x00" not in prompt


class TestDiffAwareGeneration:
    @pytest.mark.asyncio
    async def test_small_change_uses_diff_prompt(self):
        """When previous_content and existing_doc are provided with a small change,
        the DOC_UPDATE_PROMPT should be used (contains 'CHANGES (unified diff)')."""
        mock_router = MagicMock()
        mock_router.complete = AsyncMock(return_value=LLMResponse(content="Updated documentation"))
        gen = DocGenerator(llm_router=mock_router)

        old_content = "class User(Base):\n    id = Column(Integer)\n    name = Column(String)\n"
        new_content = (
            "class User(Base):\n    id = Column(Integer)\n"
            "    name = Column(String)\n    email = Column(String)\n"
        )

        result = await gen.generate(
            file_path="models/user.py",
            content=new_content,
            doc_type="orm_model",
            previous_content=old_content,
            existing_doc="## User table docs",
        )
        assert result == "Updated documentation"
        prompt = mock_router.complete.call_args[1]["messages"][0].content
        assert "CHANGES (unified diff)" in prompt

    @pytest.mark.asyncio
    async def test_large_change_uses_full_prompt(self):
        """When the diff is too large, the full generation prompt should be used."""
        mock_router = MagicMock()
        mock_router.complete = AsyncMock(return_value=LLMResponse(content="Full documentation"))
        gen = DocGenerator(llm_router=mock_router)

        old_content = "line A\n" * 10
        new_content = "line B\n" * 10

        result = await gen.generate(
            file_path="models/user.py",
            content=new_content,
            doc_type="orm_model",
            previous_content=old_content,
            existing_doc="## Old docs",
        )
        assert result == "Full documentation"
        prompt = mock_router.complete.call_args[1]["messages"][0].content
        assert "CHANGES (unified diff)" not in prompt

    def test_compute_diff(self):
        gen = DocGenerator(llm_router=MagicMock())
        old = "line1\nline2\nline3\n"
        new = "line1\nline2_changed\nline3\n"
        diff = gen._compute_diff(old, new)
        assert "-line2\n" in diff
        assert "+line2_changed\n" in diff


class TestBinaryContentDetection:
    def test_normal_text_is_not_binary(self):
        assert _is_binary_content("class User(Base):\n    pass\n") is False

    def test_high_non_printable_ratio_is_binary(self):
        assert _is_binary_content("\x01\x02\x03\x04\x05" * 200) is True

    def test_empty_string_is_not_binary(self):
        assert _is_binary_content("") is False

    def test_mixed_content_below_threshold(self):
        text = "Hello world! " * 100 + "\x01\x02"
        assert _is_binary_content(text) is False


class TestSanitizeContent:
    def test_strips_null_bytes(self):
        assert _sanitize_content("hello\x00world") == "helloworld"

    def test_no_change_for_clean_text(self):
        assert _sanitize_content("clean text") == "clean text"

    def test_strips_multiple_null_bytes(self):
        assert _sanitize_content("\x00\x00abc\x00") == "abc"
