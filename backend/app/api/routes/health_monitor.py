from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.connectors.registry import get_connector
from app.core.health_monitor import health_monitor
from app.services.connection_service import ConnectionService
from app.services.membership_service import MembershipService

logger = logging.getLogger(__name__)

router = APIRouter()
_svc = ConnectionService()
_membership_svc = MembershipService()


@router.get("/{connection_id}/health")
async def get_connection_health(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    conn = await _svc.get(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    await _membership_svc.check_access(db, conn.project_id, user["user_id"])

    state = health_monitor.get_health(connection_id)
    if not state:
        return {
            "status": "unknown",
            "latency_ms": 0,
            "last_check": None,
            "consecutive_failures": 0,
            "last_error": None,
        }
    return state


@router.get("/health")
async def get_all_connections_health(
    project_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.check_access(db, project_id, user["user_id"])

    connections = await _svc.list_by_project(db, project_id)
    result: dict[str, dict] = {}
    for conn in connections:
        state = health_monitor.get_health(conn.id)
        result[conn.id] = state or {
            "status": "unknown",
            "latency_ms": 0,
            "last_check": None,
            "consecutive_failures": 0,
            "last_error": None,
        }
    return result


@router.post("/{connection_id}/reconnect")
async def reconnect_connection(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    conn = await _svc.get(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    await _membership_svc.check_access(db, conn.project_id, user["user_id"])

    config = await _svc.to_config(db, conn, user_id=user["user_id"])
    connector = get_connector(conn.db_type, ssh_exec_mode=config.ssh_exec_mode)
    try:
        await connector.connect(config)
        result = await health_monitor.check_connection(connection_id, connector)
        if result["status"] == "down":
            await connector.disconnect()
            return {"success": False, "health": result}
        return {"success": True, "health": result}
    except Exception as exc:
        logger.warning("Reconnect failed for %s: %s", connection_id, exc)
        return {"success": False, "error": str(exc)}
