from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.connectors.registry import get_connector
from app.core.health_monitor import health_monitor
from app.core.rate_limit import limiter
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
    await _membership_svc.require_role(db, conn.project_id, user["user_id"])

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
    await _membership_svc.require_role(db, project_id, user["user_id"])

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
@limiter.limit("10/minute")
async def reconnect_connection(
    request: Request,
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    conn = await _svc.get(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    await _membership_svc.require_role(db, conn.project_id, user["user_id"])

    config = await _svc.to_config(db, conn, user_id=user["user_id"])
    try:
        connector = get_connector(conn.db_type, ssh_exec_mode=config.ssh_exec_mode)
    except TypeError:
        return {
            "success": False,
            "error": f"Connector type {conn.db_type!r} does not support health checks",
        }

    try:
        await connector.connect(config)
        result = await health_monitor.check_connection(connection_id, connector)
        if result["status"] == "down":
            return {"success": False, "health": result}
        return {"success": True, "health": result}
    except Exception as exc:
        logger.warning("Reconnect failed for %s: %s", connection_id, exc)
        return {"success": False, "error": str(exc)}
    finally:
        try:
            await connector.disconnect()
        except Exception:
            pass
