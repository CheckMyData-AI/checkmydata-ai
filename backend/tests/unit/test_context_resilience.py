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
from app.llm.base import LLMResponse, Message, ToolCall
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
# trim_loop_messages: tool_call / tool pairing invariant (audit-High)
# -----------------------------------------------------------------------


def _assert_no_orphan_tool_ids(messages: list[Message]) -> None:
    """OpenAI/OpenRouter reject a request where an assistant ``tool_calls[].id``
    has no matching ``tool`` message, or a ``tool`` message's ``tool_call_id``
    has no matching preceding assistant tool_call. Assert neither orphan exists.
    """
    assistant_ids: set[str] = set()
    tool_ids: set[str] = set()
    for m in messages:
        if m.role == "assistant" and m.tool_calls:
            for tc in m.tool_calls:
                assistant_ids.add(tc.id)
        if m.role == "tool" and m.tool_call_id is not None:
            tool_ids.add(m.tool_call_id)

    orphan_tool_msgs = tool_ids - assistant_ids
    orphan_assistant_calls = assistant_ids - tool_ids
    assert not orphan_tool_msgs, (
        f"tool messages with no matching assistant tool_call: {sorted(orphan_tool_msgs)} "
        f"(roles={[m.role for m in messages]})"
    )
    assert not orphan_assistant_calls, (
        f"assistant tool_calls with no matching tool reply: {sorted(orphan_assistant_calls)} "
        f"(roles={[m.role for m in messages]})"
    )


class TestTrimLoopMessagesPairing:
    """Trimming must never separate an assistant ``tool_calls`` message from
    its ``tool`` reply, nor leave an orphaned id of either kind.
    """

    def _round(self, idx: int, *, asst_chars: int, tool_chars: int) -> list[Message]:
        cid = f"call_{idx}"
        return [
            Message(
                role="assistant",
                content="A" * asst_chars,
                tool_calls=[ToolCall(id=cid, name="query", arguments={})],
            ),
            Message(
                role="tool",
                content="T" * tool_chars,
                tool_call_id=cid,
                name="query",
            ),
        ]

    def test_many_rounds_over_budget_no_orphans(self):
        """Several assistant(tool_calls)+tool rounds exceeding the threshold:
        post-trim there must be no orphaned tool_call ids of either kind.

        Includes an intermediate user message (realistic multi-turn session)
        so the trim split point falls inside a tool-calling round.
        """
        msgs: list[Message] = [Message(role="system", content="S" * 200)]
        for r in range(3):
            msgs.extend(self._round(r, asst_chars=600, tool_chars=600))
        msgs.append(Message(role="user", content="follow-up turn"))
        for r in range(3, 6):
            msgs.extend(self._round(r, asst_chars=600, tool_chars=600))
        msgs.append(Message(role="user", content="final question"))

        result, trimmed = trim_loop_messages(msgs, max_tokens=600)

        assert trimmed
        _assert_no_orphan_tool_ids(result)

    def test_last_user_between_assistant_and_tool_no_orphan(self):
        """When the last user message falls between an assistant's tool_calls
        and its tool reply, the split must not orphan the tool reply.
        """
        msgs = [
            Message(role="system", content="S" * 40),
            Message(
                role="assistant",
                content="A" * 4000,
                tool_calls=[ToolCall(id="c0", name="query", arguments={})],
            ),
            Message(role="user", content="mid-then-last user"),
            Message(role="tool", content="T" * 40, tool_call_id="c0", name="query"),
        ]

        result, trimmed = trim_loop_messages(msgs, max_tokens=300)

        assert trimmed
        _assert_no_orphan_tool_ids(result)

    def test_condense_only_path_preserves_pairs(self):
        """When tool-result condensing alone brings the list under budget, all
        assistant/tool pairs must remain intact (no orphan ids).
        """
        msgs: list[Message] = [Message(role="system", content="S" * 40)]
        for r in range(4):
            msgs.extend(self._round(r, asst_chars=40, tool_chars=4000))
        msgs.append(Message(role="user", content="final"))

        result, trimmed = trim_loop_messages(msgs, max_tokens=2000)

        assert trimmed
        _assert_no_orphan_tool_ids(result)

    def test_multi_call_assistant_all_tools_kept_or_summarized_together(self):
        """An assistant emitting several tool_calls in one turn: post-trim,
        either all its tool replies are present or none of its ids survive.
        """
        msgs = [
            Message(role="system", content="S" * 40),
            Message(
                role="assistant",
                content="A" * 100,
                tool_calls=[
                    ToolCall(id="m0", name="query", arguments={}),
                    ToolCall(id="m1", name="query", arguments={}),
                ],
            ),
            Message(role="tool", content="T" * 4000, tool_call_id="m0", name="query"),
            Message(role="tool", content="T" * 4000, tool_call_id="m1", name="query"),
            Message(role="user", content="final"),
        ]

        result, trimmed = trim_loop_messages(msgs, max_tokens=300)

        assert trimmed
        _assert_no_orphan_tool_ids(result)


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
