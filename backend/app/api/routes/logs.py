"""Owner-only request logs API for the trace/observability screen."""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.rate_limit import limiter
from app.services.logs_service import LogsService
from app.services.membership_service import MembershipService

logger = logging.getLogger(__name__)

router = APIRouter()
_logs_svc = LogsService()
_membership_svc = MembershipService()


@router.get("/{project_id}/users")
@limiter.limit("30/minute")
async def get_log_users(
    request: Request,
    project_id: str,
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """List users who made requests in this project (owner-only)."""
    await _membership_svc.require_role(db, project_id, user["user_id"], "owner")
    return await _logs_svc.get_users(db, project_id, days=days)


@router.get("/{project_id}/requests")
@limiter.limit("30/minute")
async def list_log_requests(
    request: Request,
    project_id: str,
    user_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Paginated list of request traces (owner-only)."""
    await _membership_svc.require_role(db, project_id, user["user_id"], "owner")

    dt_from = None
    dt_to = None
    if date_from:
        try:
            dt_from = datetime.fromisoformat(date_from).replace(tzinfo=UTC)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid date_from format") from exc
    if date_to:
        try:
            dt_to = datetime.fromisoformat(date_to).replace(tzinfo=UTC)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid date_to format") from exc

    return await _logs_svc.list_requests(
        db,
        project_id,
        user_id=user_id,
        status=status,
        date_from=dt_from,
        date_to=dt_to,
        page=page,
        page_size=page_size,
    )


@router.get("/{project_id}/requests/{trace_id}")
@limiter.limit("60/minute")
async def get_trace_detail(
    request: Request,
    project_id: str,
    trace_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Full trace detail with all spans (owner-only)."""
    await _membership_svc.require_role(db, project_id, user["user_id"], "owner")
    result = await _logs_svc.get_trace_detail(db, project_id, trace_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Trace not found")
    return result


@router.get("/{project_id}/summary")
@limiter.limit("30/minute")
async def get_logs_summary(
    request: Request,
    project_id: str,
    days: int = Query(default=7, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Dashboard-level summary of request traces (owner-only)."""
    await _membership_svc.require_role(db, project_id, user["user_id"], "owner")
    return await _logs_svc.get_summary(db, project_id, days=days)
