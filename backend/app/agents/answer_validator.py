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
from app.llm.router import LLMRouter
from app.llm.usage_sink import UsageSink

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

    def __init__(self, llm: LLMRouter, usage_sink: UsageSink | None = None) -> None:
        self._llm = llm
        self._sink = usage_sink

    async def validate(
        self,
        *,
        question: str,
        answer: str,
        sql_summaries: list[str] | None = None,
        row_count: int | None = None,
        truncated: bool = False,
        preferred_provider: str | None = None,
        model: str | None = None,
    ) -> AnswerValidationResult:
        """Return a structured verdict.

        Both an LLM *call* failure and an unparseable / verdict-less *reply*
        honour ``settings.answer_validator_fail_closed`` (fail closed by
        default): an answer we could not verify is reported as not addressing
        the question so the caller frames it as a continuable partial. Set the
        flag to ``False`` to restore the historic lenient behaviour.
        """
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

        data_facts = ""
        if row_count is not None:
            data_facts += f"\n\n## Result facts\n- rows returned: {row_count}"
            if truncated:
                data_facts += (
                    "\n- PARTIAL DATA: the result was TRUNCATED/capped — any total is a "
                    "lower bound. An answer that presents it as a complete/exact total does "
                    "NOT correctly address the question."
                )

        user_payload = (
            f"## User question\n{question.strip()}\n\n"
            f"## Agent answer\n{answer.strip()[:4000]}"
            f"{evidence}{data_facts}"
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
                usage_sink=self._sink,
            )
        except Exception:
            # R5-6: fail closed by default for ANY validator failure (not just
            # LLMError — a timeout or unexpected error must not crash the
            # response pipeline or slip an unverified answer through). An answer
            # we could not verify is reported as "does not address the question"
            # so the caller frames it as a continuable partial result instead of
            # a verified final answer. ``answer_validator_fail_closed=False``
            # restores the old lenient behaviour. (CancelledError, a
            # BaseException, still propagates and is not swallowed here.)
            from app.config import settings

            fail_closed = settings.answer_validator_fail_closed
            logger.debug(
                "AnswerValidator LLM call failed; failing %s",
                "closed" if fail_closed else "open",
                exc_info=True,
            )
            return AnswerValidationResult(
                addresses_question=not fail_closed,
                confidence=0.0,
                reason="validator unavailable",
                is_partial=fail_closed,
            )

        text = (response.content or "").strip()
        from app.config import settings

        return _parse_validator_output(text, fail_closed=settings.answer_validator_fail_closed)


def _parse_failure_result(reason: str, *, fail_closed: bool) -> AnswerValidationResult:
    """Verdict for an unparseable validator reply.

    R5-6 (parse half): parse failure must honour the SAME fail-closed policy as
    a failed LLM *call* (see :meth:`AnswerValidator.validate`). When
    ``fail_closed`` is true a garbage / empty / non-JSON / field-missing reply
    is reported as "does not address the question" (a continuable partial)
    instead of being silently waved through as a verified answer. When false the
    historic lenient default (``addresses_question=True``) is preserved. Either
    way confidence is ``0.0`` — a parse failure carries no real signal.
    """
    return AnswerValidationResult(
        addresses_question=not fail_closed,
        confidence=0.0,
        reason=reason,
        is_partial=fail_closed,
    )


def _parse_validator_output(text: str, *, fail_closed: bool = False) -> AnswerValidationResult:
    """Parse the validator JSON output, tolerating preamble/code-fence noise.

    ``fail_closed`` mirrors ``settings.answer_validator_fail_closed``: when true,
    any unparseable / verdict-less reply routes through
    :func:`_parse_failure_result` (treated as not-addressed) rather than the
    lenient pass that would otherwise fail open.
    """
    if not text:
        return _parse_failure_result("empty validator output", fail_closed=fail_closed)
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1:
        return _parse_failure_result("non-JSON validator output", fail_closed=fail_closed)
    try:
        payload = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        logger.debug("AnswerValidator JSON parse failed: %s", cleaned[:200])
        return _parse_failure_result("invalid validator JSON", fail_closed=fail_closed)
    if not isinstance(payload, dict) or "addresses_question" not in payload:
        # A successful-looking JSON object that omits the verdict field is just
        # as unverifiable as malformed JSON — treat it the same.
        return _parse_failure_result("validator verdict missing", fail_closed=fail_closed)
    return AnswerValidationResult(
        addresses_question=bool(payload.get("addresses_question", True)),
        confidence=float(payload.get("confidence", 0.5) or 0.0),
        reason=str(payload.get("reason", ""))[:300],
        is_partial=bool(payload.get("is_partial", False)),
    )
