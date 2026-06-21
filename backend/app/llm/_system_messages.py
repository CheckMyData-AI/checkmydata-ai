"""Shared message normalization helpers for LLM adapters.

Some provider backends (Anthropic, Amazon Bedrock — both natively and routed
through OpenRouter) reject a ``system`` role that does not immediately follow a
user message or a tool result: ``role 'system' must follow a 'user' message``.
Callers historically insert mid-conversation ``system`` markers (an
end-of-history delimiter, a per-iteration budget note, an emergency-synthesis
directive). This module folds those non-leading ``system`` messages into the
adjacent user turn so the payload is valid for every provider while preserving
the marker's recency.
"""

from __future__ import annotations

from app.llm.base import Message


def merge_nonleading_system(messages: list[Message]) -> list[Message]:
    """Fold non-leading ``system`` messages into the adjacent user turn.

    Keeps the leading run of ``system`` messages as-is; merges any later
    ``system`` content into the next ``user`` message, or appends a trailing
    ``user`` message when no subsequent user turn exists. Leaves OpenAI-style
    providers (which accept mid-conversation system) semantically unaffected.
    """
    result: list[Message] = []
    leading = True
    pending: list[str] = []
    for m in messages:
        if m.role == "system":
            if leading:
                result.append(m)
            elif m.content:
                pending.append(m.content)
            continue
        leading = False
        if pending and m.role == "user":
            prefix = "\n\n".join(pending)
            m = Message(
                role="user",
                content=f"{prefix}\n\n{m.content}" if m.content else prefix,
                tool_call_id=m.tool_call_id,
                name=m.name,
                tool_calls=m.tool_calls,
            )
            pending = []
        result.append(m)
    if pending:
        # No trailing user turn to attach to — emit one so the guidance survives
        # without an invalid mid-conversation system role.
        result.append(Message(role="user", content="\n\n".join(pending)))
    return result
