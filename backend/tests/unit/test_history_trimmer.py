"""Tests for token-budget-aware chat history trimming."""

from unittest.mock import AsyncMock

import pytest

from app.core.history_trimmer import (
    CHARS_PER_TOKEN_ESTIMATE,
    _fallback_summary,
    condense_tool_results,
    estimate_messages_tokens,
    estimate_tokens,
    trim_history,
)
from app.llm.base import Message


class TestEstimateTokens:
    def test_empty_string(self):
        assert estimate_tokens("") == 1

    def test_short_string(self):
        assert estimate_tokens("hi") == 1

    def test_normal_string(self):
        text = "x" * 100
        assert estimate_tokens(text) == 100 // CHARS_PER_TOKEN_ESTIMATE

    def test_messages_tokens(self):
        msgs = [
            Message(role="user", content="x" * 100),
            Message(role="assistant", content="y" * 200),
        ]
        total = estimate_messages_tokens(msgs)
        assert total == (100 + 200) // CHARS_PER_TOKEN_ESTIMATE


class TestCondenseToolResults:
    def test_short_tool_result_unchanged(self):
        msgs = [Message(role="tool", content="short result", tool_call_id="tc1")]
        result = condense_tool_results(msgs)
        assert result[0].content == "short result"

    def test_long_tool_result_truncated(self):
        long_content = "line\n" * 200
        msgs = [Message(role="tool", content=long_content, tool_call_id="tc1")]
        result = condense_tool_results(msgs)
        assert len(result[0].content) < len(long_content)
        assert "truncated" in result[0].content

    def test_non_tool_messages_unchanged(self):
        msgs = [
            Message(role="user", content="hello"),
            Message(role="assistant", content="world"),
        ]
        result = condense_tool_results(msgs)
        assert result == msgs

    def test_preserves_tool_call_id(self):
        msgs = [Message(role="tool", content="x" * 1000, tool_call_id="tc-abc", name="func")]
        result = condense_tool_results(msgs)
        assert result[0].tool_call_id == "tc-abc"
        assert result[0].name == "func"


class TestTrimHistory:
    @pytest.mark.asyncio
    async def test_empty_messages_returned(self):
        result = await trim_history([], max_tokens=100)
        assert result == []

    @pytest.mark.asyncio
    async def test_under_budget_unchanged(self):
        msgs = [Message(role="user", content="short")]
        result = await trim_history(msgs, max_tokens=10000)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_over_budget_trims_without_llm(self):
        msgs = [
            Message(role="user", content="x" * 400),
            Message(role="assistant", content="y" * 400),
            Message(role="user", content="z" * 400),
        ]
        result = await trim_history(msgs, max_tokens=150)
        assert len(result) < len(msgs)
        assert result[0].role == "system"
        assert "summary" in result[0].content.lower()

    @pytest.mark.asyncio
    async def test_over_budget_with_llm_summarizes(self):
        from app.llm.base import LLMResponse

        mock_router = AsyncMock()
        mock_router.complete = AsyncMock(
            return_value=LLMResponse(
                content="Summary of old messages",
                tool_calls=[],
                usage={},
            )
        )
        msgs = [
            Message(role="user", content="x" * 1000),
            Message(role="assistant", content="y" * 1000),
            Message(role="user", content="latest question"),
        ]
        result = await trim_history(msgs, max_tokens=50, llm_router=mock_router)
        assert result[0].role == "system"
        assert "Summary" in result[0].content


class TestFallbackSummary:
    def test_extracts_user_topics(self):
        msgs = [
            Message(role="user", content="What are total sales?"),
            Message(role="assistant", content="100"),
            Message(role="user", content="Show me by month"),
        ]
        summary = _fallback_summary(msgs)
        assert "total sales" in summary.lower()
        assert "by month" in summary.lower()

    def test_empty_messages(self):
        summary = _fallback_summary([])
        assert "Previous topics discussed" in summary

    def test_only_recent_three(self):
        msgs = [Message(role="user", content=f"q{i}") for i in range(10)]
        summary = _fallback_summary(msgs)
        assert "q7" in summary
        assert "q8" in summary
        assert "q9" in summary
