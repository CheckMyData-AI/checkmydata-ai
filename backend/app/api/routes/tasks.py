"""Endpoint for querying currently running background tasks.

Tenancy: non-admin users only see workflows they initiated or that belong
to a project they are a member of. Admins (``settings.admin_emails``)
see everything.
"""

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.config import settings
from app.core.rate_limit import limiter
from app.core.workflow_tracker import tracker
from app.services.membership_service import MembershipService
from app.services.pipeline_status_service import PipelineStatusService

router = APIRouter()
_membership_svc = MembershipService()
_pipeline_status_svc = PipelineStatusService()


def _merge_active_tasks(
    in_memory: list[dict[str, Any]],
    synthetic: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    seen = {t["workflow_id"] for t in in_memory}
    merged = list(in_memory)
    for entry in synthetic:
        if entry["workflow_id"] not in seen:
            merged.append(entry)
            seen.add(entry["workflow_id"])
    return merged


@router.get("/active", response_model=list[dict[str, Any]])
@limiter.limit("60/minute")
async def get_active_tasks(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Return currently running background workflows visible to this user."""
    if settings.is_admin_email(user.get("email")):
        in_memory = tracker.get_active()
        projects = await _membership_svc.get_accessible_projects(db, user["user_id"])
        accessible = {p.id for p in projects}
        synthetic = await _pipeline_status_svc.list_synthetic_active_tasks(
            db,
            accessible_project_ids=accessible,
        )
        return _merge_active_tasks(in_memory, synthetic)

    projects = await _membership_svc.get_accessible_projects(db, user["user_id"])
    accessible = {p.id for p in projects}
    in_memory = tracker.get_active(
        user_id=user["user_id"],
        accessible_project_ids=accessible,
    )
    synthetic = await _pipeline_status_svc.list_synthetic_active_tasks(
        db,
        accessible_project_ids=accessible,
    )
    return _merge_active_tasks(in_memory, synthetic)
