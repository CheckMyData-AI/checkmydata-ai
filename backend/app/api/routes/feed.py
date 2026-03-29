"""Autonomous Insight Feed API — trigger scans and retrieve feed data."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
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
    await _membership_svc.require_role(db, project_id, user["user_id"], "owner")

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
    await _membership_svc.require_role(db, project_id, user["user_id"], "owner")

    from sqlalchemy import select

    from app.agents.insight_feed_agent import InsightFeedAgent
    from app.models.connection import Connection

    result_conn = await db.execute(select(Connection.id).where(Connection.project_id == project_id))
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


@router.post("/{project_id}/opportunities/{connection_id}")
@limiter.limit("5/minute")
async def scan_opportunities(
    request: Request,
    project_id: str,
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Scan a connection's tables for growth opportunities."""
    project_id = validate_safe_id(project_id, "project_id")
    connection_id = validate_safe_id(connection_id, "connection_id")
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")

    from sqlalchemy import select

    from app.connectors.registry import get_connector
    from app.core.opportunity_detector import OpportunityDetector
    from app.models.connection import Connection
    from app.models.db_index import DbIndex
    from app.services.connection_service import ConnectionService

    conn_svc = ConnectionService()
    result = await db.execute(
        select(Connection).where(
            Connection.id == connection_id,
            Connection.project_id == project_id,
        )
    )
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")

    cfg = await conn_svc.to_config(db, conn)

    idx_result = await db.execute(
        select(DbIndex).where(DbIndex.connection_id == connection_id).limit(5)
    )
    db_entries = idx_result.scalars().all()

    if not db_entries:
        return {"ok": True, "opportunities": [], "tables_scanned": 0, "insights_stored": 0}

    detector = OpportunityDetector()
    all_opportunities: list[dict] = []

    connector = get_connector(cfg.db_type, ssh_exec_mode=cfg.ssh_exec_mode)
    await connector.connect(cfg)

    try:
        for entry in db_entries:
            table = entry.table_name
            try:
                import json

                sample_data = json.loads(entry.sample_data_json) if entry.sample_data_json else []
                col_notes = json.loads(entry.column_notes_json) if entry.column_notes_json else {}
                columns = list(col_notes.keys())[:20]

                if not sample_data or not columns:
                    continue

                rows = sample_data[:100] if isinstance(sample_data, list) else []
                if not rows:
                    continue

                opps = detector.analyze(
                    rows=rows,
                    columns=columns,
                    table_name=table,
                )
                for opp in opps:
                    all_opportunities.append(opp.to_dict())

            except Exception as exc:
                logger.warning(
                    "Opportunity scan failed for table %s: %s",
                    table,
                    exc,
                )
    finally:
        await connector.disconnect()

    from app.core.insight_memory import InsightMemoryService

    svc = InsightMemoryService()
    stored = 0
    for opp_dict in all_opportunities[:10]:
        try:
            await svc.store_insight(
                db,
                project_id=project_id,
                connection_id=connection_id,
                insight_type="opportunity",
                severity="positive",
                title=opp_dict["title"],
                description=opp_dict["description"],
                recommended_action=opp_dict["suggested_action"],
                expected_impact=opp_dict["estimated_impact"],
                confidence=opp_dict["confidence"],
            )
            stored += 1
        except Exception:
            logger.debug("Failed to store opportunity insight", exc_info=True)

    await db.commit()

    return {
        "ok": True,
        "opportunities": all_opportunities[:20],
        "tables_scanned": len(db_entries),
        "insights_stored": stored,
    }


@router.post("/{project_id}/losses/{connection_id}")
@limiter.limit("5/minute")
async def scan_losses(
    request: Request,
    project_id: str,
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Scan a connection's tables for revenue leaks and conversion drops."""
    project_id = validate_safe_id(project_id, "project_id")
    connection_id = validate_safe_id(connection_id, "connection_id")
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")

    from sqlalchemy import select

    from app.connectors.registry import get_connector
    from app.core.loss_detector import LossDetector
    from app.models.connection import Connection
    from app.models.db_index import DbIndex
    from app.services.connection_service import ConnectionService

    conn_svc = ConnectionService()
    result = await db.execute(
        select(Connection).where(
            Connection.id == connection_id,
            Connection.project_id == project_id,
        )
    )
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")

    cfg = await conn_svc.to_config(db, conn)

    idx_result = await db.execute(
        select(DbIndex).where(DbIndex.connection_id == connection_id).limit(5)
    )
    db_entries = idx_result.scalars().all()

    if not db_entries:
        return {"ok": True, "losses": [], "tables_scanned": 0, "insights_stored": 0}

    detector = LossDetector()
    all_losses: list[dict] = []

    connector = get_connector(cfg.db_type, ssh_exec_mode=cfg.ssh_exec_mode)
    await connector.connect(cfg)

    try:
        for entry in db_entries:
            table = entry.table_name
            try:
                import json

                sample_data = json.loads(entry.sample_data_json) if entry.sample_data_json else []
                col_notes = json.loads(entry.column_notes_json) if entry.column_notes_json else {}
                columns = list(col_notes.keys())[:20]

                if not sample_data or not columns:
                    continue

                rows = sample_data[:100] if isinstance(sample_data, list) else []
                if not rows:
                    continue

                losses = detector.analyze(
                    rows=rows,
                    columns=columns,
                    table_name=table,
                )
                for loss in losses:
                    all_losses.append(loss.to_dict())

            except Exception as exc:
                logger.warning(
                    "Loss scan failed for table %s: %s",
                    table,
                    exc,
                )
    finally:
        await connector.disconnect()

    from app.core.insight_memory import InsightMemoryService

    svc = InsightMemoryService()
    stored = 0
    for loss_dict in all_losses[:10]:
        try:
            await svc.store_insight(
                db,
                project_id=project_id,
                connection_id=connection_id,
                insight_type="loss",
                severity=loss_dict.get("severity", "warning"),
                title=loss_dict["title"],
                description=loss_dict["description"],
                recommended_action=loss_dict["suggested_fix"],
                expected_impact=loss_dict["estimated_monthly_impact"],
                confidence=loss_dict["confidence"],
            )
            stored += 1
        except Exception:
            logger.debug("Failed to store loss insight", exc_info=True)

    await db.commit()

    return {
        "ok": True,
        "losses": all_losses[:20],
        "tables_scanned": len(db_entries),
        "insights_stored": stored,
    }
