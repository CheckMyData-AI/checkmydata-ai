from unittest.mock import AsyncMock, MagicMock

import pytest

from app.knowledge.doc_generator import DocGenerator
from app.llm.base import LLMResponse


class TestDocGenerator:
    @pytest.mark.asyncio
    async def test_generate_returns_llm_output(self):
        mock_router = MagicMock()
        mock_router.complete = AsyncMock(return_value=LLMResponse(
            content="## users\nStores user accounts.\n\n| Column | Description |\n|---|---|\n| id | Primary key |",
        ))
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
