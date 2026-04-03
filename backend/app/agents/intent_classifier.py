"""LLM-based intent classification for the orchestrator.

Classifies the user's message into an intent type *before* any heavy
context loading (table maps, learnings, staleness checks, etc.).
This allows the orchestrator to build the minimal execution chain
needed for each request.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from enum import StrEnum

from app.agents.prompts.orchestrator_prompt import build_classification_prompt
from app.llm.base import Message
from app.llm.router import LLMRouter

logger = logging.getLogger(__name__)

_CLASSIFICATION_MAX_TOKENS = 80
_HISTORY_TAIL_FOR_CLASSIFICATION = 4


class IntentType(StrEnum):
    DIRECT_RESPONSE = "direct_response"
    DATA_QUERY = "data_query"
    KNOWLEDGE_QUERY = "knowledge_query"
    MCP_QUERY = "mcp_query"
    MIXED = "mixed"


@dataclass
class ClassifiedIntent:
    intent: IntentType
    reason: str


def _valid_intents(
    *,
    has_connection: bool,
    has_knowledge_base: bool,
    has_mcp_sources: bool,
) -> set[str]:
    """Return the set of intent values that are valid given the project capabilities."""
    valid = {IntentType.DIRECT_RESPONSE.value, IntentType.MIXED.value}
    if has_connection:
        valid.add(IntentType.DATA_QUERY.value)
    if has_knowledge_base:
        valid.add(IntentType.KNOWLEDGE_QUERY.value)
    if has_mcp_sources:
        valid.add(IntentType.MCP_QUERY.value)
    return valid


async def classify_intent(
    question: str,
    llm_router: LLMRouter,
    *,
    has_connection: bool = False,
    has_knowledge_base: bool = False,
    has_mcp_sources: bool = False,
    chat_history: list[Message] | None = None,
    preferred_provider: str | None = None,
    model: str | None = None,
) -> ClassifiedIntent:
    """Classify user intent via a lightweight LLM call (~500 tokens).

    Falls back to ``IntentType.MIXED`` on any failure so the full
    orchestrator pipeline handles the request.
    """
    system_prompt = build_classification_prompt(
        has_connection=has_connection,
        has_knowledge_base=has_knowledge_base,
        has_mcp_sources=has_mcp_sources,
    )

    messages: list[Message] = [Message(role="system", content=system_prompt)]

    if chat_history:
        tail = chat_history[-_HISTORY_TAIL_FOR_CLASSIFICATION:]
        for m in tail:
            if m.role in ("user", "assistant") and m.content:
                snippet = m.content[:200]
                messages.append(Message(role=m.role, content=snippet))

    messages.append(Message(role="user", content=question[:500]))

    try:
        resp = await llm_router.complete(
            messages=messages,
            max_tokens=_CLASSIFICATION_MAX_TOKENS,
            temperature=0.0,
            preferred_provider=preferred_provider,
            model=model,
        )
    except Exception:
        logger.debug("Intent classification LLM call failed, falling back to MIXED", exc_info=True)
        return ClassifiedIntent(intent=IntentType.MIXED, reason="classification_error")

    valid = _valid_intents(
        has_connection=has_connection,
        has_knowledge_base=has_knowledge_base,
        has_mcp_sources=has_mcp_sources,
    )

    return _parse_classification_response(resp.content, valid)


_JSON_OBJ_RE = re.compile(r"\{[^{}]*\}")
_ALL_INTENT_VALUES = {e.value for e in IntentType}


def _extract_json(raw: str) -> dict | None:
    """Try increasingly aggressive strategies to pull a JSON object out of *raw*."""
    raw = raw.strip()

    if "```" in raw:
        lines = raw.split("\n")
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        raw = "\n".join(lines).strip()

    for start_char in ("{", "["):
        idx = raw.find(start_char)
        if idx > 0:
            raw = raw[idx:]
            break

    try:
        data = json.loads(raw)
        if isinstance(data, list):
            data = data[0] if data else None
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass

    m = _JSON_OBJ_RE.search(raw)
    if m:
        try:
            data = json.loads(m.group())
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

    return None


def _extract_plain_text_intent(raw: str, valid_intents: set[str]) -> str | None:
    """Fallback: check if the raw LLM output contains a recognizable intent name."""
    lower = raw.strip().strip("\"'").lower()
    for intent_val in _ALL_INTENT_VALUES:
        if intent_val in lower and intent_val in valid_intents:
            return intent_val
    return None


def _parse_classification_response(
    raw: str,
    valid_intents: set[str],
) -> ClassifiedIntent:
    """Parse the LLM JSON response into a ClassifiedIntent."""
    data = _extract_json(raw)

    if data is not None:
        intent_str = data.get("intent", "").strip().lower()
        reason = data.get("reason", "")

        if intent_str not in valid_intents:
            logger.warning(
                "Intent classification returned invalid intent '%s' (valid: %s), raw: %s",
                intent_str,
                valid_intents,
                raw[:200],
            )
            return ClassifiedIntent(intent=IntentType.MIXED, reason=f"invalid_intent:{intent_str}")

        try:
            intent = IntentType(intent_str)
        except ValueError:
            return ClassifiedIntent(intent=IntentType.MIXED, reason=f"unknown_intent:{intent_str}")

        return ClassifiedIntent(intent=intent, reason=reason)

    plain_intent = _extract_plain_text_intent(raw, valid_intents)
    if plain_intent:
        logger.info(
            "Intent classifier: recovered intent '%s' from plain text (raw: %s)",
            plain_intent,
            raw[:120],
        )
        try:
            return ClassifiedIntent(intent=IntentType(plain_intent), reason="recovered_from_text")
        except ValueError:
            pass

    logger.warning("Intent classification returned unparseable response: %s", raw[:200])
    return ClassifiedIntent(intent=IntentType.MIXED, reason="parse_error")
