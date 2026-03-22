"""API routes for Query-less Exploration."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, validate_safe_id
from app.core.exploration_engine import ExplorationEngine
from app.services.membership_service import MembershipService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["explore"])

_membership_svc = MembershipService()
_engine = ExplorationEngine()


@router.post("/{project_id}")
async def explore_project(
    project_id: str,
    connection_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Autonomous investigation: 'What's wrong with my data?'

    Scans existing insights, anomaly reports, and data health to compile
    a structured investigation report.
    """
    project_id = validate_safe_id(project_id, "project_id")
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")

    from app.core.insight_memory import InsightMemoryService

    insight_svc = InsightMemoryService()
    raw_insights = await insight_svc.get_insights(
        db,
        project_id,
        connection_id=connection_id,
        status="active",
        limit=50,
    )
    insights = [
        {
            "insight_type": i.insight_type,
            "severity": i.severity,
            "title": i.title,
            "description": i.description,
            "confidence": i.confidence,
            "recommended_action": i.recommended_action or "",
        }
        for i in raw_insights
    ]

    health: dict[str, Any] = {}
    try:
        from sqlalchemy import select

        from app.models.db_index import DbIndexSummary

        if connection_id:
            result = await db.execute(
                select(DbIndexSummary).where(DbIndexSummary.connection_id == connection_id)
            )
            summary = result.scalar_one_or_none()
            if summary:
                health = {
                    "total_tables": summary.total_tables,
                    "active_tables": summary.active_tables,
                    "empty_tables": summary.empty_tables,
                    "orphan_tables": summary.orphan_tables,
                }
    except Exception:
        logger.debug("Failed to load DB index summary", exc_info=True)

    report = _engine.investigate(
        insights=insights,
        table_health=health if health else None,
    )

    return report.to_dict()
