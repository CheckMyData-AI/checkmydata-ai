import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.audit import audit_log
from app.core.rate_limit import limiter
from app.services.membership_service import MembershipService
from app.services.rule_service import RuleService

logger = logging.getLogger(__name__)

router = APIRouter()
_svc = RuleService()
_membership_svc = MembershipService()


async def _regenerate_overview_for_project(project_id: str | None) -> None:
    """Best-effort regenerate the project knowledge overview after rules change."""
    if not project_id:
        return
    from app.models.base import async_session_factory
    from app.services.project_overview_service import ProjectOverviewService

    try:
        async with async_session_factory() as session:
            svc = ProjectOverviewService()
            await svc.save_overview(session, project_id)
        logger.info("Project overview regenerated after rules change: project=%s", project_id[:8])
    except Exception:
        logger.warning("Failed to regenerate project overview after rules change", exc_info=True)


class RuleCreate(BaseModel):
    project_id: str | None = None
    name: str = Field(max_length=255)
    content: str = Field(max_length=50000)
    format: Literal["markdown", "yaml", "text"] = "markdown"


class RuleUpdate(BaseModel):
    name: str | None = Field(None, max_length=255)
    content: str | None = Field(None, max_length=50000)
    format: Literal["markdown", "yaml", "text"] | None = None


class RuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str | None
    name: str
    content: str
    format: str
    is_default: bool = False


@router.post("", response_model=RuleResponse)
@limiter.limit("20/minute")
async def create_rule(
    request: Request,
    body: RuleCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    if body.project_id:
        await _membership_svc.require_role(db, body.project_id, user["user_id"], "editor")
    rule = await _svc.create(db, **body.model_dump())
    audit_log(
        "rule.create",
        user_id=user["user_id"],
        project_id=rule.project_id,
        resource_type="rule",
        resource_id=rule.id,
    )
    await _regenerate_overview_for_project(rule.project_id)
    return rule


@router.get("", response_model=list[RuleResponse])
@limiter.limit("60/minute")
async def list_rules(
    request: Request,
    project_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    if project_id:
        await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")
    return await _svc.list_all(db, project_id=project_id)


@router.get("/{rule_id}", response_model=RuleResponse)
async def get_rule(
    rule_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    rule = await _svc.get(db, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    if rule.project_id:
        await _membership_svc.require_role(db, rule.project_id, user["user_id"], "viewer")
    return rule


@router.patch("/{rule_id}", response_model=RuleResponse)
@limiter.limit("20/minute")
async def update_rule(
    request: Request,
    rule_id: str,
    body: RuleUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    rule = await _svc.get(db, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    if rule.project_id:
        await _membership_svc.require_role(db, rule.project_id, user["user_id"], "editor")
    elif rule.is_default:
        raise HTTPException(status_code=403, detail="Default rules cannot be modified")
    updates = body.model_dump(exclude_unset=True)
    updated_rule = await _svc.update(db, rule_id, **updates)
    if not updated_rule:
        raise HTTPException(status_code=404, detail="Rule not found after update")
    audit_log(
        "rule.update",
        user_id=user["user_id"],
        project_id=updated_rule.project_id,
        resource_type="rule",
        resource_id=rule_id,
    )
    await _regenerate_overview_for_project(updated_rule.project_id)
    return updated_rule


@router.delete("/{rule_id}")
@limiter.limit("20/minute")
async def delete_rule(
    request: Request,
    rule_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    rule = await _svc.get(db, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    if rule.project_id:
        await _membership_svc.require_role(db, rule.project_id, user["user_id"], "editor")
    elif rule.is_default:
        raise HTTPException(status_code=403, detail="Default rules cannot be deleted")
    project_id = rule.project_id
    await _svc.delete(db, rule_id)
    audit_log(
        "rule.delete",
        user_id=user["user_id"],
        project_id=project_id,
        resource_type="rule",
        resource_id=rule_id,
    )
    await _regenerate_overview_for_project(project_id)
    return {"ok": True}
