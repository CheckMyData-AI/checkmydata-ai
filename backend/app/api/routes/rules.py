from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.audit import audit_log
from app.services.membership_service import MembershipService
from app.services.rule_service import RuleService

router = APIRouter()
_svc = RuleService()
_membership_svc = MembershipService()


class RuleCreate(BaseModel):
    project_id: str | None = None
    name: str = Field(max_length=255)
    content: str = Field(max_length=50000)
    format: str = "markdown"


class RuleUpdate(BaseModel):
    name: str | None = Field(None, max_length=255)
    content: str | None = Field(None, max_length=50000)
    format: str | None = None


class RuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str | None
    name: str
    content: str
    format: str
    is_default: bool = False


@router.post("", response_model=RuleResponse)
async def create_rule(
    body: RuleCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    if body.project_id:
        await _membership_svc.require_role(db, body.project_id, user["user_id"], "owner")
    rule = await _svc.create(db, **body.model_dump())
    audit_log(
        "rule.create",
        user_id=user["user_id"],
        project_id=rule.project_id,
        resource_type="rule",
        resource_id=rule.id,
    )
    return rule


@router.get("", response_model=list[RuleResponse])
async def list_rules(
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
async def update_rule(
    rule_id: str,
    body: RuleUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    rule = await _svc.get(db, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    if rule.project_id:
        await _membership_svc.require_role(db, rule.project_id, user["user_id"], "owner")
    updates = body.model_dump(exclude_unset=True)
    rule = await _svc.update(db, rule_id, **updates)
    audit_log(
        "rule.update",
        user_id=user["user_id"],
        project_id=rule.project_id,
        resource_type="rule",
        resource_id=rule_id,
    )
    return rule


@router.delete("/{rule_id}")
async def delete_rule(
    rule_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    rule = await _svc.get(db, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    if rule.project_id:
        await _membership_svc.require_role(db, rule.project_id, user["user_id"], "owner")
    await _svc.delete(db, rule_id)
    audit_log(
        "rule.delete",
        user_id=user["user_id"],
        project_id=rule.project_id,
        resource_type="rule",
        resource_id=rule_id,
    )
    return {"ok": True}
