"""PipelineLearningExtractor — learns from orchestrator-level events.

Complements the SQL-level ``LearningAnalyzer`` by extracting lessons from:
- Replan outcomes (what failed, what the replacement plan did)
- DataGate failures (data quality issues in stage results)
- Pipeline completion patterns (complexity estimation misses, high retry rates)

All lessons are stored via ``AgentLearningService`` using the same
``AgentLearning`` model, tagged with pipeline-specific categories:
``pipeline_pattern``, ``data_quality_hint``, ``replan_recovery``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.agents.data_gate import DataGateOutcome
from app.agents.stage_context import StageContext
from app.knowledge.learning_analyzer import ExtractedLesson

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class PipelineLearningExtractor:
    """Extracts reusable lessons from pipeline execution outcomes."""

    async def extract_from_replan(
        self,
        session: AsyncSession,
        connection_id: str,
        *,
        question: str,
        failed_stage_id: str,
        failed_stage_tool: str,
        error: str,
        replan_succeeded: bool,
        replan_plan_summary: str = "",
    ) -> list[ExtractedLesson]:
        """Extract lessons when a replan occurs after stage failure."""
        lessons: list[ExtractedLesson] = []

        if replan_succeeded:
            lessons.append(
                ExtractedLesson(
                    category="replan_recovery",
                    subject=failed_stage_tool,
                    lesson=(
                        f"Stage '{failed_stage_id}' ({failed_stage_tool}) failed with: "
                        f"{error[:200]}. Replan succeeded"
                        + (f" by: {replan_plan_summary[:150]}" if replan_plan_summary else "")
                        + "."
                    ),
                    confidence=0.7,
                    source_error=error[:500],
                )
            )
        else:
            lessons.append(
                ExtractedLesson(
                    category="pipeline_pattern",
                    subject=failed_stage_tool,
                    lesson=(
                        f"Stage '{failed_stage_id}' ({failed_stage_tool}) is unreliable "
                        f"for this type of query. Error: {error[:200]}. "
                        "Consider breaking into simpler sub-queries."
                    ),
                    confidence=0.6,
                    source_error=error[:500],
                )
            )

        return await self._store(session, connection_id, lessons)

    async def extract_from_data_gate(
        self,
        session: AsyncSession,
        connection_id: str,
        *,
        stage_id: str,
        stage_tool: str,
        outcome: DataGateOutcome,
        query: str | None = None,
    ) -> list[ExtractedLesson]:
        """Extract lessons from DataGate quality check failures/warnings."""
        lessons: list[ExtractedLesson] = []

        for err in outcome.errors:
            lessons.append(
                ExtractedLesson(
                    category="data_quality_hint",
                    subject=stage_tool,
                    lesson=f"DataGate error on stage '{stage_id}': {err[:250]}",
                    confidence=0.65,
                    source_query=query,
                    source_error=err[:500],
                )
            )

        for warn in outcome.warnings:
            if "cartesian join" in warn.lower() or "duplicate" in warn.lower():
                lessons.append(
                    ExtractedLesson(
                        category="data_quality_hint",
                        subject=stage_tool,
                        lesson=f"DataGate warning on stage '{stage_id}': {warn[:250]}",
                        confidence=0.55,
                        source_query=query,
                    )
                )

        return await self._store(session, connection_id, lessons)

    async def extract_from_pipeline_completion(
        self,
        session: AsyncSession,
        connection_id: str,
        *,
        stage_ctx: StageContext,
        replan_history: list[dict[str, Any]],
    ) -> list[ExtractedLesson]:
        """Extract broad pipeline-level patterns after full completion."""
        lessons: list[ExtractedLesson] = []

        if len(replan_history) >= 2:
            tools = [h.get("failed_stage", "?") for h in replan_history]
            lessons.append(
                ExtractedLesson(
                    category="pipeline_pattern",
                    subject="multi_replan",
                    lesson=(
                        f"This query type triggered {len(replan_history)} replans "
                        f"(failed stages: {', '.join(tools)}). "
                        "Consider simplifying the plan or breaking into sub-queries."
                    ),
                    confidence=0.7,
                )
            )

        total_retries = sum(1 for sr in stage_ctx.results.values() if sr.status == "error")
        if total_retries >= 3:
            lessons.append(
                ExtractedLesson(
                    category="pipeline_pattern",
                    subject="high_retry_rate",
                    lesson=(
                        f"Pipeline had {total_retries} stage errors across "
                        f"{len(stage_ctx.results)} stages. Database may have "
                        "complex schema that needs careful JOIN planning."
                    ),
                    confidence=0.55,
                )
            )

        return await self._store(session, connection_id, lessons)

    @staticmethod
    async def _store(
        session: AsyncSession,
        connection_id: str,
        lessons: list[ExtractedLesson],
    ) -> list[ExtractedLesson]:
        """Persist lessons via AgentLearningService."""
        if not lessons or not connection_id:
            return []

        from app.services.agent_learning_service import AgentLearningService

        svc = AgentLearningService()
        stored: list[ExtractedLesson] = []
        for lesson in lessons:
            try:
                await svc.create_learning(
                    session,
                    connection_id=connection_id,
                    category=lesson.category,
                    subject=lesson.subject,
                    lesson=lesson.lesson,
                    confidence=lesson.confidence,
                    source_query=lesson.source_query,
                    source_error=lesson.source_error,
                )
                stored.append(lesson)
            except Exception:
                logger.debug(
                    "Failed to store pipeline learning: %s",
                    lesson.lesson[:100],
                    exc_info=True,
                )

        if stored:
            try:
                await session.commit()
            except Exception:
                logger.warning("Failed to commit pipeline learnings", exc_info=True)
            else:
                logger.info(
                    "Stored %d pipeline learnings for connection %s",
                    len(stored),
                    connection_id,
                )

        return stored
