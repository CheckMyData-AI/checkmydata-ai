"""CRUD for data validation feedback and accuracy stats."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.models.data_validation import DataValidationFeedback

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class DataValidationService:
    """Manages structured user data accuracy feedback."""

    async def record_validation(
        self,
        session: AsyncSession,
        connection_id: str,
        session_id: str,
        message_id: str,
        query: str,
        verdict: str,
        metric_description: str = "",
        agent_value: str = "",
        user_expected_value: str | None = None,
        deviation_pct: float | None = None,
        rejection_reason: str | None = None,
    ) -> DataValidationFeedback:
        entry = DataValidationFeedback(
            connection_id=connection_id,
            session_id=session_id,
            message_id=message_id,
            query=query,
            verdict=verdict,
            metric_description=metric_description,
            agent_value=agent_value,
            user_expected_value=user_expected_value,
            deviation_pct=deviation_pct,
            rejection_reason=rejection_reason,
        )
        session.add(entry)
        await session.flush()
        return entry

    async def get_unresolved(
        self,
        session: AsyncSession,
        connection_id: str,
    ) -> list[DataValidationFeedback]:
        result = await session.execute(
            select(DataValidationFeedback)
            .where(
                DataValidationFeedback.connection_id == connection_id,
                DataValidationFeedback.resolved.is_(False),
            )
            .order_by(DataValidationFeedback.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_id(
        self,
        session: AsyncSession,
        feedback_id: str,
    ) -> DataValidationFeedback | None:
        return await session.get(DataValidationFeedback, feedback_id)

    async def get_by_message_id(
        self,
        session: AsyncSession,
        message_id: str,
    ) -> DataValidationFeedback | None:
        result = await session.execute(
            select(DataValidationFeedback).where(DataValidationFeedback.message_id == message_id)
        )
        return result.scalar_one_or_none()

    async def resolve(
        self,
        session: AsyncSession,
        feedback_id: str,
        resolution: str,
    ) -> DataValidationFeedback | None:
        entry = await session.get(DataValidationFeedback, feedback_id)
        if not entry:
            return None
        entry.resolved = True
        entry.resolution = resolution
        await session.flush()
        return entry

    async def get_accuracy_stats(
        self,
        session: AsyncSession,
        connection_id: str,
    ) -> dict:
        total = await session.execute(
            select(func.count(DataValidationFeedback.id)).where(
                DataValidationFeedback.connection_id == connection_id
            )
        )
        total_count = total.scalar_one()

        if total_count == 0:
            return {
                "total": 0,
                "confirmed": 0,
                "rejected": 0,
                "approximate": 0,
                "unknown": 0,
                "resolved": 0,
                "confirmation_rate": None,
            }

        verdicts = await session.execute(
            select(
                DataValidationFeedback.verdict,
                func.count(DataValidationFeedback.id),
            )
            .where(DataValidationFeedback.connection_id == connection_id)
            .group_by(DataValidationFeedback.verdict)
        )
        counts = dict(verdicts.all())

        resolved = await session.execute(
            select(func.count(DataValidationFeedback.id)).where(
                DataValidationFeedback.connection_id == connection_id,
                DataValidationFeedback.resolved.is_(True),
            )
        )
        resolved_count = resolved.scalar_one()

        confirmed = counts.get("confirmed", 0) + counts.get("approximate", 0)
        total_rated = confirmed + counts.get("rejected", 0)
        rate = (confirmed / total_rated * 100) if total_rated else None

        return {
            "total": total_count,
            "confirmed": counts.get("confirmed", 0),
            "rejected": counts.get("rejected", 0),
            "approximate": counts.get("approximate", 0),
            "unknown": counts.get("unknown", 0),
            "resolved": resolved_count,
            "confirmation_rate": round(rate, 1) if rate is not None else None,
        }
