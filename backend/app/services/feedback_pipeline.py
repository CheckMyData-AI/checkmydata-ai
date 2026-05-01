"""Pipeline: DataValidationFeedback → analysis → learnings/notes/benchmarks."""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

from app.models.data_validation import DataValidationFeedback
from app.services.agent_learning_service import AgentLearningService
from app.services.benchmark_service import BenchmarkService, normalize_metric_key
from app.services.data_validation_service import DataValidationService
from app.services.session_notes_service import SessionNotesService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.llm.router import LLMRouter

logger = logging.getLogger(__name__)

SMALL_DEVIATION_PCT = 5.0
MEDIUM_DEVIATION_PCT = 20.0


_LEARNING_PROMPT = """Classify a user rejection of an agent-generated
metric into a structured learning entry.

Return ONLY this JSON object:
  {
    "category": "data_format" | "schema_gotcha" | "table_preference"
              | "column_usage" | "query_pattern" | "performance_hint",
    "subject": "<table-or-metric-name>",
    "lesson": "<one-sentence takeaway, <= 300 chars>"
  }

Inputs: metric description, agent SQL, agent value, user expected value,
rejection reason. If nothing useful can be extracted, return
``{"category":"","subject":"","lesson":""}``.
"""


class FeedbackPipeline:
    """Processes user data-accuracy feedback into persistent learning artifacts.

    Pass ``llm_router`` to enable LLM-driven learning extraction (T11).
    The keyword classifier :func:`_derive_learning` stays as a fallback.
    """

    def __init__(self, llm_router: LLMRouter | None = None) -> None:
        self._learning_svc = AgentLearningService()
        self._notes_svc = SessionNotesService()
        self._benchmark_svc = BenchmarkService()
        self._validation_svc = DataValidationService()
        self._llm_router = llm_router

    async def process(
        self,
        session: AsyncSession,
        feedback: DataValidationFeedback,
        project_id: str,
    ) -> dict:
        """Analyse a piece of validation feedback and create appropriate artifacts.

        Returns a summary dict with keys ``learnings_created``, ``notes_created``,
        ``benchmark_updated``, and ``resolution``.
        """
        result: dict = {
            "learnings_created": [],
            "notes_created": [],
            "benchmark_updated": False,
            "resolution": "",
        }

        verdict = feedback.verdict

        if verdict == "confirmed":
            await self._handle_confirmed(session, feedback, project_id, result)
        elif verdict == "approximate":
            await self._handle_approximate(session, feedback, project_id, result)
        elif verdict == "rejected":
            await self._handle_rejected(session, feedback, project_id, result)
        else:
            result["resolution"] = "Feedback recorded; no automatic action taken."
            await self._validation_svc.resolve(session, feedback.id, result["resolution"])
            return result

        await self._validation_svc.resolve(session, feedback.id, result["resolution"])
        return result

    # ------------------------------------------------------------------
    # Verdict handlers
    # ------------------------------------------------------------------

    async def _handle_confirmed(
        self,
        session: AsyncSession,
        fb: DataValidationFeedback,
        project_id: str,
        result: dict,
    ) -> None:
        metric_key = normalize_metric_key(fb.metric_description or fb.query[:100])
        await self._benchmark_svc.create_or_confirm(
            session,
            connection_id=fb.connection_id,
            metric_key=metric_key,
            value=fb.agent_value,
            value_numeric=_try_float(fb.agent_value),
            source="user_confirmed",
            metric_description=fb.metric_description,
        )
        result["benchmark_updated"] = True
        result["resolution"] = "User confirmed data accuracy. Benchmark stored."

    async def _handle_approximate(
        self,
        session: AsyncSession,
        fb: DataValidationFeedback,
        project_id: str,
        result: dict,
    ) -> None:
        metric_key = normalize_metric_key(fb.metric_description or fb.query[:100])
        await self._benchmark_svc.create_or_confirm(
            session,
            connection_id=fb.connection_id,
            metric_key=metric_key,
            value=fb.agent_value,
            value_numeric=_try_float(fb.agent_value),
            source="user_confirmed",
            metric_description=fb.metric_description,
        )
        result["benchmark_updated"] = True

        if fb.user_expected_value:
            note = await self._notes_svc.create_note(
                session,
                connection_id=fb.connection_id,
                project_id=project_id,
                category="data_observation",
                subject=_extract_subject(fb),
                note=(
                    f"User expected ~{fb.user_expected_value} for '{fb.metric_description}', "
                    f"agent returned {fb.agent_value}. Small deviation accepted."
                ),
                confidence=0.6,
            )
            result["notes_created"].append(note.id)

        result["resolution"] = "Approximate match accepted. Benchmark + note created."

    async def _handle_rejected(
        self,
        session: AsyncSession,
        fb: DataValidationFeedback,
        project_id: str,
        result: dict,
    ) -> None:
        reason = fb.rejection_reason or "User flagged result as incorrect"

        note = await self._notes_svc.create_note(
            session,
            connection_id=fb.connection_id,
            project_id=project_id,
            category="data_observation",
            subject=_extract_subject(fb),
            note=(
                f"REJECTED: '{fb.metric_description}' returned {fb.agent_value}. "
                f"User expected: {fb.user_expected_value or 'not specified'}. "
                f"Reason: {reason}. Query: {fb.query[:300]}"
            ),
            confidence=0.8,
        )
        result["notes_created"].append(note.id)

        category, subject, lesson = await self._derive_learning_llm_first(fb, reason)
        if category and lesson:
            try:
                learning = await self._learning_svc.create_learning(
                    session,
                    connection_id=fb.connection_id,
                    category=category,
                    subject=subject or _extract_subject(fb),
                    lesson=lesson,
                    confidence=0.7,
                    source_query=fb.query,
                    source_error=f"User rejection: {reason}",
                )
                result["learnings_created"].append(learning.id)
            except ValueError:
                logger.warning(
                    "Skipped learning from rejected feedback (quality check): subj=%s",
                    subject or _extract_subject(fb),
                )

        metric_key = normalize_metric_key(fb.metric_description or fb.query[:100])
        await self._benchmark_svc.flag_stale(session, fb.connection_id, metric_key)

        result["resolution"] = f"User rejected result. Learning + note created. Reason: {reason}"

    async def _derive_learning_llm_first(
        self,
        fb: DataValidationFeedback,
        reason: str,
    ) -> tuple[str | None, str | None, str | None]:
        """LLM-first learning classifier. Returns (category, subject, lesson).

        Falls back to :func:`_derive_learning` (keyword heuristic) on any
        failure so the pipeline keeps learning even without the LLM.
        """
        if self._llm_router is not None:
            try:
                from app.llm.base import Message

                payload = json.dumps(
                    {
                        "metric_description": fb.metric_description,
                        "agent_value": fb.agent_value,
                        "user_expected_value": fb.user_expected_value,
                        "query": (fb.query or "")[:2000],
                        "reason": reason,
                    },
                    default=str,
                )
                resp = await self._llm_router.complete(
                    messages=[
                        Message(role="system", content=_LEARNING_PROMPT),
                        Message(role="user", content=payload),
                    ],
                    temperature=0.0,
                    max_tokens=400,
                )
                parsed = _extract_json(resp.content if resp else "")
                if isinstance(parsed, dict):
                    category = str(parsed.get("category", "")).strip() or None
                    subject = (
                        str(parsed.get("subject", "")).strip() or None
                    )
                    lesson = str(parsed.get("lesson", "")).strip() or None
                    if category and lesson:
                        return category, subject, lesson
            except Exception:
                logger.debug(
                    "LLM-based feedback classification failed; using fallback",
                    exc_info=True,
                )

        category, lesson = _derive_learning(fb, reason)
        return category, None, lesson


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _extract_subject(fb: DataValidationFeedback) -> str:
    """Best-effort table/metric name from feedback."""
    if fb.metric_description:
        words = fb.metric_description.split()
        return words[0] if words else "unknown"
    return "query_result"


def _derive_learning(
    fb: DataValidationFeedback,
    reason: str,
) -> tuple[str | None, str | None]:
    """Attempt to classify the rejection into a learning category."""
    reason_lower = reason.lower()

    if any(kw in reason_lower for kw in ("cent", "dollar", "currency", "unit", "format")):
        return (
            "data_format",
            f"Data format issue with '{fb.metric_description}': {reason}. "
            f"Agent returned {fb.agent_value}, user expected {fb.user_expected_value or '?'}.",
        )
    if any(kw in reason_lower for kw in ("filter", "missing", "where", "status", "deleted")):
        return (
            "schema_gotcha",
            f"Missing filter/condition for '{fb.metric_description}': {reason}. "
            "Ensure correct WHERE clauses are applied.",
        )
    if any(kw in reason_lower for kw in ("wrong table", "table", "legacy")):
        return (
            "table_preference",
            f"Wrong table used for '{fb.metric_description}': {reason}.",
        )
    if any(kw in reason_lower for kw in ("join", "relationship")):
        return (
            "schema_gotcha",
            f"JOIN issue for '{fb.metric_description}': {reason}.",
        )

    return (
        "schema_gotcha",
        f"Data accuracy issue with '{fb.metric_description}': {reason}. "
        f"Agent value: {fb.agent_value}, expected: {fb.user_expected_value or '?'}.",
    )


def _extract_json(raw: str | None) -> object | None:
    if not raw:
        return None
    stripped = raw.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        return json.loads(stripped)
    except Exception:
        return None


def _try_float(val: str | None) -> float | None:
    if not val:
        return None
    cleaned = val.replace(",", "").replace("$", "").replace("€", "").strip()
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None
