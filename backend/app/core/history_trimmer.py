"""Token-budget-aware chat history trimming.

Keeps the most recent messages verbatim and summarises older ones
so the total stays within ``max_tokens``.  Handles ``tool`` role
messages by condensing large tool results into compact summaries
before they enter the LLM context window.
"""

from __future__ import annotations

import logging

from app.llm.base import Message

logger = logging.getLogger(__name__)

CHARS_PER_TOKEN_ESTIMATE = 4
TOOL_RESULT_MAX_CHARS = 500


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN_ESTIMATE)


def estimate_messages_tokens(messages: list[Message]) -> int:
    return sum(estimate_tokens(m.content) for m in messages)


def condense_tool_results(messages: list[Message]) -> list[Message]:
    """Shorten tool-result messages so they don't blow up the context budget."""
    out: list[Message] = []
    for m in messages:
        if m.role == "tool" and len(m.content) > TOOL_RESULT_MAX_CHARS:
            lines = m.content.splitlines()
            preview = "\n".join(lines[:8])
            if len(preview) > TOOL_RESULT_MAX_CHARS:
                preview = preview[:TOOL_RESULT_MAX_CHARS]
            condensed = f"{preview}\n... (truncated, {len(m.content)} chars total)"
            out.append(
                Message(
                    role=m.role,
                    content=condensed,
                    tool_call_id=m.tool_call_id,
                    name=m.name,
                )
            )
        else:
            out.append(m)
    return out


async def trim_history(
    messages: list[Message],
    max_tokens: int,
    llm_router=None,
    preferred_provider: str | None = None,
    model: str | None = None,
    summary_model: str | None = None,
) -> list[Message]:
    """Return a token-budget-aware version of *messages*.

    Strategy:
    1. Condense large tool results first.
    2. Walk backwards from the newest message, accumulating tokens.
    3. As soon as the budget is reached, the remaining older messages are
       summarised into a single ``system`` message.
    4. If no LLM router is provided, older messages are dropped instead
       of summarised.
    """
    if not messages:
        return messages

    messages = condense_tool_results(messages)

    total = estimate_messages_tokens(messages)
    if total <= max_tokens:
        return messages

    keep: list[Message] = []
    budget = max_tokens
    split_idx = len(messages)

    for i in range(len(messages) - 1, -1, -1):
        msg_tokens = estimate_tokens(messages[i].content)
        if budget - msg_tokens < 0:
            split_idx = i + 1
            break
        budget -= msg_tokens
        keep.insert(0, messages[i])

    older = messages[:split_idx]
    if not older:
        return keep

    if llm_router is not None:
        summary = await _summarise(
            older,
            llm_router,
            preferred_provider,
            summary_model or model,
        )
    else:
        summary = _fallback_summary(older)

    summary_msg = Message(
        role="system",
        content=f"[Conversation summary of {len(older)} earlier messages]\n{summary}",
    )
    return [summary_msg, *keep]


async def _summarise(
    messages: list[Message],
    llm_router,
    preferred_provider: str | None = None,
    model: str | None = None,
) -> str:
    non_tool = [m for m in messages if m.role != "tool"]
    conversation = "\n".join(f"{m.role}: {(m.content or '')[:300]}" for m in non_tool)
    prompt_messages = [
        Message(
            role="system",
            content=(
                "Summarise the following conversation in 2-3 sentences. "
                "Focus on what was asked, what SQL queries or data insights "
                "were discussed, and any knowledge-base findings. Be concise."
            ),
        ),
        Message(role="user", content=conversation[:4000]),
    ]
    try:
        resp = await llm_router.complete(
            messages=prompt_messages,
            max_tokens=300,
            temperature=0.0,
            preferred_provider=preferred_provider,
            model=model,
        )
        return resp.content.strip()
    except (RuntimeError, ValueError, TypeError, OSError):
        logger.debug("LLM summary failed, using fallback", exc_info=True)
        return _fallback_summary(messages)


def _fallback_summary(messages: list[Message]) -> str:
    user_msgs = [m for m in messages if m.role == "user"]
    topics = [m.content[:80] for m in user_msgs[-3:]]
    return "Previous topics discussed: " + "; ".join(topics)


# ---------------------------------------------------------------------------
# In-loop message trimming (for agent tool-calling loops)
# ---------------------------------------------------------------------------

_TRIM_THRESHOLD = 0.80
_WRAP_UP_THRESHOLD = 0.70


def _summarise_pair(assistant_msg: Message, tool_msgs: list[Message]) -> str:
    """Build a compact one-liner from an assistant + tool result pair."""
    snippet = assistant_msg.content[:120].replace("\n", " ").strip()
    tool_summaries: list[str] = []
    for tm in tool_msgs:
        name = tm.name or "tool"
        preview = tm.content[:80].replace("\n", " ").strip()
        tool_summaries.append(f"{name}→{preview}")
    return f"[{snippet}] {'; '.join(tool_summaries)}"


def trim_loop_messages(
    messages: list[Message],
    max_tokens: int,
) -> tuple[list[Message], bool]:
    """Trim an agent's in-loop message list to stay within *max_tokens*.

    Preserves: system prompt (index 0) and the last user message.
    Strategy:
    1. Condense older tool results (> 500 chars).
    2. If still over budget, collapse oldest assistant+tool pairs into a
       single system summary message.

    Returns ``(trimmed_messages, did_trim)`` so callers can emit events.
    """
    if not messages or len(messages) < 3:
        return messages, False

    total = estimate_messages_tokens(messages)
    threshold = int(max_tokens * _TRIM_THRESHOLD)
    if total <= threshold:
        return messages, False

    system_msg = messages[0]
    last_user_idx = max(
        (i for i, m in enumerate(messages) if m.role == "user"),
        default=1,
    )

    middle = list(messages[1:last_user_idx])
    tail = list(messages[last_user_idx:])

    condensed_middle = condense_tool_results(middle)
    candidate = [system_msg, *condensed_middle, *tail]
    total = estimate_messages_tokens(candidate)
    if total <= threshold:
        return candidate, True

    summaries: list[str] = []
    keep_middle: list[Message] = []
    i = 0
    while i < len(condensed_middle):
        m = condensed_middle[i]
        if m.role == "assistant":
            tool_msgs: list[Message] = []
            j = i + 1
            while j < len(condensed_middle) and condensed_middle[j].role == "tool":
                tool_msgs.append(condensed_middle[j])
                j += 1
            summaries.append(_summarise_pair(m, tool_msgs))
            i = j
        else:
            keep_middle.append(m)
            i += 1

    if summaries:
        summary_text = "[Earlier analysis summary]\n" + "\n".join(summaries)
        summary_msg = Message(role="system", content=summary_text)
        candidate = [system_msg, summary_msg, *keep_middle, *tail]
    else:
        candidate = [system_msg, *keep_middle, *tail]

    return candidate, True


def should_wrap_up(messages: list[Message], max_tokens: int) -> bool:
    """Return True when context usage exceeds the wrap-up threshold."""
    return estimate_messages_tokens(messages) > int(max_tokens * _WRAP_UP_THRESHOLD)
