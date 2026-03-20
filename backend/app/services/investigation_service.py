"""Investigation lifecycle management for 'Wrong Data' reports."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.models.data_validation import DataInvestigation

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


VALID_STATUSES = frozenset(
    {"collecting_info", "investigating", "presenting_fix", "resolved", "failed"}
)
VALID_PHASES = frozenset({"collect_info", "investigate", "present_fix", "update_memory"})
VALID_COMPLAINT_TYPES = frozenset(
    {
        "numbers_too_high",
        "numbers_too_low",
        "wrong_time_period",
        "missing_data",
        "wrong_categories",
        "completely_wrong",
        "other",
    }
)


class InvestigationService:
    """Manages the lifecycle of a data investigation."""

    async def create_investigation(
        self,
        session: AsyncSession,
        connection_id: str,
        session_id: str,
        trigger_message_id: str,
        original_query: str,
        original_result_summary: str = "{}",
        user_complaint_type: str = "other",
        user_complaint_detail: str | None = None,
        user_expected_value: str | None = None,
        problematic_column: str | None = None,
        validation_feedback_id: str | None = None,
    ) -> DataInvestigation:
        investigation = DataInvestigation(
            connection_id=connection_id,
            session_id=session_id,
            trigger_message_id=trigger_message_id,
            original_query=original_query,
            original_result_summary=original_result_summary,
            user_complaint_type=user_complaint_type,
            user_complaint_detail=user_complaint_detail,
            user_expected_value=user_expected_value,
            problematic_column=problematic_column,
            validation_feedback_id=validation_feedback_id,
            status="collecting_info",
            phase="collect_info",
        )
        session.add(investigation)
        await session.flush()
        return investigation

    async def update_phase(
        self,
        session: AsyncSession,
        investigation_id: str,
        status: str,
        phase: str,
        log_entry: str | None = None,
    ) -> DataInvestigation | None:
        inv = await session.get(DataInvestigation, investigation_id)
        if not inv:
            return None

        inv.status = status
        inv.phase = phase

        if log_entry:
            try:
                existing_log = json.loads(inv.investigation_log_json or "[]")
            except json.JSONDecodeError:
                existing_log = []
            existing_log.append(
                {
                    "phase": phase,
                    "status": status,
                    "detail": log_entry,
                    "ts": datetime.now(UTC).isoformat(),
                }
            )
            inv.investigation_log_json = json.dumps(existing_log)

        await session.flush()
        return inv

    async def record_finding(
        self,
        session: AsyncSession,
        investigation_id: str,
        corrected_query: str | None = None,
        corrected_result_json: str | None = None,
        root_cause: str | None = None,
        root_cause_category: str | None = None,
    ) -> DataInvestigation | None:
        inv = await session.get(DataInvestigation, investigation_id)
        if not inv:
            return None

        if corrected_query is not None:
            inv.corrected_query = corrected_query
        if corrected_result_json is not None:
            inv.corrected_result_json = corrected_result_json
        if root_cause is not None:
            inv.root_cause = root_cause
        if root_cause_category is not None:
            inv.root_cause_category = root_cause_category

        inv.status = "presenting_fix"
        inv.phase = "present_fix"

        await session.flush()
        return inv

    async def complete_investigation(
        self,
        session: AsyncSession,
        investigation_id: str,
        learnings_created: list[str] | None = None,
        notes_created: list[str] | None = None,
        benchmarks_updated: list[str] | None = None,
    ) -> DataInvestigation | None:
        inv = await session.get(DataInvestigation, investigation_id)
        if not inv:
            return None

        inv.status = "resolved"
        inv.phase = "update_memory"
        inv.completed_at = datetime.now(UTC)

        if learnings_created:
            inv.learnings_created_json = json.dumps(learnings_created)
        if notes_created:
            inv.notes_created_json = json.dumps(notes_created)
        if benchmarks_updated:
            inv.benchmarks_updated_json = json.dumps(benchmarks_updated)

        await session.flush()
        return inv

    async def fail_investigation(
        self,
        session: AsyncSession,
        investigation_id: str,
        reason: str,
    ) -> DataInvestigation | None:
        inv = await session.get(DataInvestigation, investigation_id)
        if not inv:
            return None

        inv.status = "failed"
        inv.completed_at = datetime.now(UTC)
        inv.root_cause = reason

        await session.flush()
        return inv

    async def get_investigation(
        self,
        session: AsyncSession,
        investigation_id: str,
    ) -> DataInvestigation | None:
        return await session.get(DataInvestigation, investigation_id)

    async def get_active_investigation(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> DataInvestigation | None:
        result = await session.execute(
            select(DataInvestigation)
            .where(
                DataInvestigation.session_id == session_id,
                DataInvestigation.status.notin_(["resolved", "failed"]),
            )
            .order_by(DataInvestigation.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
