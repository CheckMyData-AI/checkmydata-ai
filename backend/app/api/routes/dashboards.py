import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.audit import audit_log
from app.core.rate_limit import limiter
from app.services.dashboard_service import DashboardService
from app.services.membership_service import MembershipService

logger = logging.getLogger(__name__)

router = APIRouter()
_svc = DashboardService()
_membership_svc = MembershipService()


class DashboardCreate(BaseModel):
    project_id: str = Field(..., max_length=64)
    title: str = Field(max_length=200)
    layout_json: str | None = Field(None, max_length=100_000)
    cards_json: str | None = Field(None, max_length=500_000)
    is_shared: bool = True


class DashboardUpdate(BaseModel):
    title: str | None = Field(None, max_length=200)
    layout_json: str | None = Field(None, max_length=100_000)
    cards_json: str | None = Field(None, max_length=500_000)
    is_shared: bool | None = None


class DashboardResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    creator_id: str
    title: str
    layout_json: str | None = None
    cards_json: str | None = None
    is_shared: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


@router.post("", response_model=DashboardResponse)
@limiter.limit("20/minute")
async def create_dashboard(
    request: Request,
    body: DashboardCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, body.project_id, user["user_id"], "viewer")
    dashboard = await _svc.create(
        db,
        project_id=body.project_id,
        creator_id=user["user_id"],
        title=body.title,
        layout_json=body.layout_json,
        cards_json=body.cards_json,
        is_shared=body.is_shared,
    )
    audit_log(
        "dashboard.create",
        user_id=user["user_id"],
        project_id=dashboard.project_id,
        resource_type="dashboard",
        resource_id=dashboard.id,
    )
    return dashboard


@router.get("", response_model=list[DashboardResponse])
@limiter.limit("60/minute")
async def list_dashboards(
    request: Request,
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")
    return await _svc.list_for_project(db, project_id, user["user_id"])


@router.get("/{dashboard_id}", response_model=DashboardResponse)
@limiter.limit("60/minute")
async def get_dashboard(
    request: Request,
    dashboard_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    dashboard = await _svc.get(db, dashboard_id)
    if not dashboard:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    await _membership_svc.require_role(db, dashboard.project_id, user["user_id"], "viewer")
    if dashboard.creator_id != user["user_id"] and not dashboard.is_shared:
        raise HTTPException(status_code=403, detail="Dashboard is private")
    return dashboard


@router.patch("/{dashboard_id}", response_model=DashboardResponse)
@limiter.limit("30/minute")
async def update_dashboard(
    request: Request,
    dashboard_id: str,
    body: DashboardUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    dashboard = await _svc.get(db, dashboard_id)
    if not dashboard:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    await _membership_svc.require_role(db, dashboard.project_id, user["user_id"], "viewer")
    if dashboard.creator_id != user["user_id"]:
        raise HTTPException(status_code=403, detail="Only the creator can update this dashboard")
    updates = body.model_dump(exclude_unset=True)
    updated = await _svc.update(db, dashboard.id, **updates)
    if not updated:
        raise HTTPException(status_code=404, detail="Dashboard not found after update")
    audit_log(
        "dashboard.update",
        user_id=user["user_id"],
        project_id=updated.project_id,
        resource_type="dashboard",
        resource_id=dashboard.id,
    )
    return updated


@router.delete("/{dashboard_id}")
@limiter.limit("20/minute")
async def delete_dashboard(
    request: Request,
    dashboard_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    dashboard = await _svc.get(db, dashboard_id)
    if not dashboard:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    await _membership_svc.require_role(db, dashboard.project_id, user["user_id"], "viewer")
    if dashboard.creator_id != user["user_id"]:
        raise HTTPException(status_code=403, detail="Only the creator can delete this dashboard")
    await _svc.delete(db, dashboard.id)
    audit_log(
        "dashboard.delete",
        user_id=user["user_id"],
        project_id=dashboard.project_id,
        resource_type="dashboard",
        resource_id=dashboard.id,
    )
    return {"ok": True}
