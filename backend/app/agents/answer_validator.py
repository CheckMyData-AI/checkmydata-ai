"""LLM-based answer quality gate for partial / step-limited responses.

When the orchestrator hits the step or wall-clock budget but still returns an
answer, we cannot rely on length alone (the legacy ``len > 80`` heuristic) to
tell whether the user actually got a useful reply. ``AnswerValidator`` asks the
LLM a tightly-scoped yes/no question:

> "Does this answer address the user's question, given the supporting data?"

The result downgrades the orchestrator's ``response_type`` to
``step_limit_reached`` when the answer is judged inadequate, so the UI can
offer a "Continue analysis" affordance instead of presenting a half-baked
answer as final.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from app.llm.base import Message
from app.llm.errors import LLMError
from app.llm.router import LLMRouter

logger = logging.getLogger(__name__)


@dataclass
class AnswerValidationResult:
    """Verdict from :class:`AnswerValidator` on a single answer."""

    addresses_question: bool
    confidence: float
    reason: str
    is_partial: bool = False


_VALIDATOR_SYSTEM = (
    "You judge whether an analytics agent's answer addresses the user's "
    "question. Be strict: an answer that says it ran out of time, was cut "
    "short, asks the user to retry, or only describes intermediate steps "
    "without conclusions does NOT address the question. An answer that "
    "presents the final numeric / categorical / textual conclusion based on "
    "the provided data DOES address the question.\n\n"
    "Reply with a single JSON object:\n"
    '{"addresses_question": true|false, '
    '"confidence": 0.0-1.0, '
    '"is_partial": true|false, '
    '"reason": "<one short sentence>"}'
)


class AnswerValidator:
    """Tiny LLM-driven sanity check for final orchestrator answers."""

    def __init__(self, llm: LLMRouter) -> None:
        self._llm = llm

    async def validate(
        self,
        *,
        question: str,
        answer: str,
        sql_summaries: list[str] | None = None,
        preferred_provider: str | None = None,
        model: str | None = None,
    ) -> AnswerValidationResult:
        """Return a structured verdict; failures default to ``True`` (do no harm)."""
        if not answer or not answer.strip():
            return AnswerValidationResult(
                addresses_question=False,
                confidence=0.95,
                reason="answer is empty",
                is_partial=True,
            )

        evidence = ""
        if sql_summaries:
            evidence = "\n\n## Supporting data\n" + "\n".join(f"- {s}" for s in sql_summaries[:5])

        user_payload = (
            f"## User question\n{question.strip()}\n\n"
            f"## Agent answer\n{answer.strip()[:4000]}"
            f"{evidence}"
        )

        try:
            response = await self._llm.complete(
                messages=[
                    Message(role="system", content=_VALIDATOR_SYSTEM),
                    Message(role="user", content=user_payload),
                ],
                temperature=0.0,
                max_tokens=200,
                preferred_provider=preferred_provider,
                model=model,
            )
        except LLMError:
            logger.debug("AnswerValidator LLM call failed; defaulting to OK", exc_info=True)
            return AnswerValidationResult(
                addresses_question=True,
                confidence=0.0,
                reason="validator unavailable",
            )

        text = (response.content or "").strip()
        return _parse_validator_output(text)


def _parse_validator_output(text: str) -> AnswerValidationResult:
    """Parse the validator JSON output, tolerating preamble/code-fence noise."""
    if not text:
        return AnswerValidationResult(
            addresses_question=True,
            confidence=0.0,
            reason="empty validator output",
        )
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1:
        return AnswerValidationResult(
            addresses_question=True,
            confidence=0.0,
            reason="non-JSON validator output",
        )
    try:
        payload = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        logger.debug("AnswerValidator JSON parse failed: %s", cleaned[:200])
        return AnswerValidationResult(
            addresses_question=True,
            confidence=0.0,
            reason="invalid validator JSON",
        )
    return AnswerValidationResult(
        addresses_question=bool(payload.get("addresses_question", True)),
        confidence=float(payload.get("confidence", 0.5) or 0.0),
        reason=str(payload.get("reason", ""))[:300],
        is_partial=bool(payload.get("is_partial", False)),
    )
