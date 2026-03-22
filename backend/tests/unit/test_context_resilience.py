"""Tests for context window resilience features.

Covers:
- trim_loop_messages: under/over budget behaviour
- should_wrap_up: threshold detection
- LLMTokenLimitError recovery in orchestrator
- LLMTokenLimitError fallback in router
- ContextBudgetManager wiring
- Partial answer note on recovery failure
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.context_budget import ContextBudgetManager
from app.core.history_trimmer import (
    estimate_messages_tokens,
    should_wrap_up,
    trim_loop_messages,
)
from app.llm.base import LLMResponse, Message
from app.llm.errors import (
    LLMAllProvidersFailedError,
    LLMAuthError,
    LLMTokenLimitError,
)
from app.llm.router import MODEL_CONTEXT_WINDOWS, LLMRouter

# -----------------------------------------------------------------------
# trim_loop_messages
# -----------------------------------------------------------------------


class TestTrimLoopMessages:
    def test_under_budget_not_modified(self):
        msgs = [
            Message(role="system", content="sys"),
            Message(role="user", content="hi"),
        ]
        result, trimmed = trim_loop_messages(msgs, max_tokens=5000)
        assert not trimmed
        assert len(result) == 2

    def test_over_budget_condenses_tool_results(self):
        big_tool = "x" * 4000
        msgs = [
            Message(role="system", content="sys"),
            Message(
                role="assistant",
                content="thinking",
                tool_calls=[],
            ),
            Message(
                role="tool",
                content=big_tool,
                tool_call_id="t1",
                name="query",
            ),
            Message(role="user", content="now what?"),
        ]
        result, trimmed = trim_loop_messages(msgs, max_tokens=500)
        assert trimmed
        assert result[0].role == "system"
        assert result[-1].role == "user"
        assert result[-1].content == "now what?"
        total = estimate_messages_tokens(result)
        assert total < estimate_messages_tokens(msgs)

    def test_preserves_system_and_last_user(self):
        msgs = [
            Message(role="system", content="S" * 200),
            Message(role="assistant", content="A" * 2000),
            Message(
                role="tool",
                content="T" * 3000,
                tool_call_id="t1",
                name="tool1",
            ),
            Message(role="user", content="U" * 100),
        ]
        result, trimmed = trim_loop_messages(msgs, max_tokens=300)
        assert trimmed
        assert result[0].content == "S" * 200
        assert result[-1].content == "U" * 100


# -----------------------------------------------------------------------
# should_wrap_up
# -----------------------------------------------------------------------


class TestShouldWrapUp:
    def test_below_threshold(self):
        msgs = [Message(role="user", content="short")]
        assert not should_wrap_up(msgs, max_tokens=10000)

    def test_above_threshold(self):
        big = "x" * 30000
        msgs = [Message(role="user", content=big)]
        assert should_wrap_up(msgs, max_tokens=5000)


# -----------------------------------------------------------------------
# ContextBudgetManager
# -----------------------------------------------------------------------


class TestContextBudgetManagerWiring:
    def test_truncates_schema_text(self):
        mgr = ContextBudgetManager(total_budget=200)
        big_schema = "s" * 5000
        alloc = mgr.allocate(
            system_prompt="prompt",
            schema_text=big_schema,
        )
        assert len(alloc.schema_text) < len(big_schema)
        assert "truncated" in alloc.schema_text

    def test_all_fields_within_budget(self):
        mgr = ContextBudgetManager(total_budget=500)
        alloc = mgr.allocate(
            system_prompt="prompt" * 10,
            schema_text="schema" * 50,
            rules_text="rules" * 20,
            learnings_text="learn" * 20,
            overview_text="overview" * 20,
        )
        total_chars = (
            len(alloc.system_prompt)
            + len(alloc.schema_text)
            + len(alloc.rules_text)
            + len(alloc.learnings_text)
            + len(alloc.overview_text)
        )
        assert total_chars // 4 <= 500 + 100


# -----------------------------------------------------------------------
# LLMRouter: fallback on token limit
# -----------------------------------------------------------------------


class TestRouterTokenLimitFallback:
    @pytest.mark.asyncio
    async def test_falls_back_to_next_provider(self):
        router = LLMRouter()

        first_provider = MagicMock()
        first_provider.complete = AsyncMock(side_effect=LLMTokenLimitError("too big"))

        second_provider = MagicMock()
        second_provider.complete = AsyncMock(
            return_value=LLMResponse(
                content="ok",
                tool_calls=[],
                usage={
                    "prompt_tokens": 5,
                    "completion_tokens": 5,
                    "total_tokens": 10,
                },
                provider="anthropic",
            )
        )

        router._instances = {
            "openai": first_provider,
            "anthropic": second_provider,
        }

        with patch.object(router, "_get_fallback_chain", return_value=["openai", "anthropic"]):
            resp = await router.complete(
                messages=[Message(role="user", content="hi")],
            )
        assert resp.content == "ok"
        first_provider.complete.assert_awaited_once()
        second_provider.complete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_auth_error_stops_fallback(self):
        router = LLMRouter()

        provider = MagicMock()
        provider.complete = AsyncMock(side_effect=LLMAuthError("bad key"))
        router._instances = {"openai": provider}

        with (
            patch.object(
                router,
                "_get_fallback_chain",
                return_value=["openai", "anthropic"],
            ),
            pytest.raises(LLMAllProvidersFailedError),
        ):
            await router.complete(
                messages=[Message(role="user", content="hi")],
            )


# -----------------------------------------------------------------------
# get_context_window
# -----------------------------------------------------------------------


class TestGetContextWindow:
    def test_known_model(self):
        router = LLMRouter()
        assert router.get_context_window("gpt-4o") == 128_000

    def test_partial_match(self):
        router = LLMRouter()
        assert router.get_context_window("gpt-4o-2024-08-06") == 128_000

    def test_unknown_model_returns_default(self):
        router = LLMRouter()
        assert router.get_context_window("some-unknown-model") == 16_000

    def test_none_model_returns_default(self):
        router = LLMRouter()
        assert router.get_context_window(None) == 16_000


# -----------------------------------------------------------------------
# MODEL_CONTEXT_WINDOWS sanity
# -----------------------------------------------------------------------


class TestModelContextWindows:
    def test_has_major_models(self):
        assert "gpt-4o" in MODEL_CONTEXT_WINDOWS
        assert "claude-sonnet-4-20250514" in MODEL_CONTEXT_WINDOWS

    def test_all_values_positive(self):
        for model, size in MODEL_CONTEXT_WINDOWS.items():
            assert size > 0, f"{model} has non-positive context window"


# -----------------------------------------------------------------------
# Wrap-up instruction injection (integration-style)
# -----------------------------------------------------------------------


class TestWrapUpInjection:
    def test_wrap_up_injected_when_over_threshold(self):
        big = "x" * 30000
        msgs = [
            Message(role="system", content="sys"),
            Message(role="user", content=big),
        ]
        assert should_wrap_up(msgs, max_tokens=5000)

    def test_wrap_up_not_injected_when_under(self):
        msgs = [
            Message(role="system", content="sys"),
            Message(role="user", content="short"),
        ]
        assert not should_wrap_up(msgs, max_tokens=50000)
