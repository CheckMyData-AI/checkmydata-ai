"""Pipeline: DataValidationFeedback → analysis → learnings/notes/benchmarks."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.models.data_validation import DataValidationFeedback
from app.services.agent_learning_service import AgentLearningService
from app.services.benchmark_service import BenchmarkService, normalize_metric_key
from app.services.data_validation_service import DataValidationService
from app.services.session_notes_service import SessionNotesService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

SMALL_DEVIATION_PCT = 5.0
MEDIUM_DEVIATION_PCT = 20.0


class FeedbackPipeline:
    """Processes user data-accuracy feedback into persistent learning artifacts."""

    def __init__(self) -> None:
        self._learning_svc = AgentLearningService()
        self._notes_svc = SessionNotesService()
        self._benchmark_svc = BenchmarkService()
        self._validation_svc = DataValidationService()

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

        category, lesson = _derive_learning(fb, reason)
        if category and lesson:
            try:
                learning = await self._learning_svc.create_learning(
                    session,
                    connection_id=fb.connection_id,
                    category=category,
                    subject=_extract_subject(fb),
                    lesson=lesson,
                    confidence=0.7,
                    source_query=fb.query,
                    source_error=f"User rejection: {reason}",
                )
                result["learnings_created"].append(learning.id)
            except ValueError:
                logger.warning(
                    "Skipped learning from rejected feedback (quality check): subj=%s",
                    _extract_subject(fb),
                )

        metric_key = normalize_metric_key(fb.metric_description or fb.query[:100])
        await self._benchmark_svc.flag_stale(session, fb.connection_id, metric_key)

        result["resolution"] = f"User rejected result. Learning + note created. Reason: {reason}"


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


def _try_float(val: str | None) -> float | None:
    if not val:
        return None
    cleaned = val.replace(",", "").replace("$", "").replace("€", "").strip()
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None
