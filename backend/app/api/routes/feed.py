"""Autonomous Insight Feed API — trigger scans and retrieve feed data."""

import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, validate_safe_id
from app.core.rate_limit import limiter
from app.services.membership_service import MembershipService

logger = logging.getLogger(__name__)

router = APIRouter()
_membership_svc = MembershipService()


@router.post("/{project_id}/scan/{connection_id}")
@limiter.limit("3/minute")
async def trigger_scan(
    request: Request,
    project_id: str,
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Trigger an autonomous insight scan for a specific connection."""
    project_id = validate_safe_id(project_id, "project_id")
    connection_id = validate_safe_id(connection_id, "connection_id")
    await _membership_svc.require_role(db, project_id, user["user_id"], "editor")

    from app.agents.insight_feed_agent import InsightFeedAgent

    agent = InsightFeedAgent()
    result = await agent.run_scan(db, project_id, connection_id)
    await db.commit()

    return {
        "insights_created": result.insights_created,
        "insights_updated": result.insights_updated,
        "queries_run": result.queries_run,
        "errors": result.errors[:5],
    }


@router.post("/{project_id}/scan")
@limiter.limit("3/minute")
async def trigger_full_scan(
    request: Request,
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Trigger an insight scan across all connections in a project."""
    project_id = validate_safe_id(project_id, "project_id")
    await _membership_svc.require_role(db, project_id, user["user_id"], "editor")

    from sqlalchemy import select

    from app.agents.insight_feed_agent import InsightFeedAgent
    from app.models.connection import Connection

    result_conn = await db.execute(
        select(Connection.id).where(Connection.project_id == project_id)
    )
    connection_ids = [r[0] for r in result_conn.all()]

    if not connection_ids:
        return {
            "total_insights_created": 0,
            "total_insights_updated": 0,
            "connections_scanned": 0,
        }

    agent = InsightFeedAgent()
    total_created = 0
    total_updated = 0

    for conn_id in connection_ids:
        try:
            result = await agent.run_scan(db, project_id, conn_id)
            total_created += result.insights_created
            total_updated += result.insights_updated
        except Exception as exc:
            logger.warning("Scan failed for connection %s: %s", conn_id, exc)

    await db.commit()

    return {
        "total_insights_created": total_created,
        "total_insights_updated": total_updated,
        "connections_scanned": len(connection_ids),
    }
