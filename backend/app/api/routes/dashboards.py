import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
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


#: The viewer issues one note fetch per card, so this bounds work rather than bytes. The
#: 500 KB payload cap allows roughly thirty thousand `{"note_id":"x"}` entries and says
#: nothing about how many requests that becomes.
MAX_DASHBOARD_CARDS = 200


def _validate_cards_json(value: str | None) -> str | None:
    """Check `cards_json` against the shape the viewer actually reads (F-VIZ-02).

    It was stored verbatim, and the consequence is quieter than a rejected write:

        function parseCards(json) { try { return JSON.parse(json) } catch { return [] } }

    A malformed string — or valid JSON of the wrong shape — renders as an **empty
    dashboard**. Dashboards are shared by default, so one bad write shows everyone else a
    page with nothing on it and no sign that anything is wrong.

    The contract comes from the consumer rather than from imagination
    (`frontend/src/lib/api/types.ts:502`): `note_id` required and a string, `viz_config`
    an optional object, `refresh_interval` an optional number. `viz_config`'s interior is
    deliberately not inspected — the viewer treats it as opaque and hands it to the chart
    layer, so validating it here would invent a contract nobody wrote.

    Only writes are checked. Rows already stored are read as they always were: making a
    legacy row fail to *load* would turn a cosmetic problem into an outage.
    """
    if value is None:
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"cards_json is not valid JSON: {exc}") from exc
    if not isinstance(parsed, list):
        raise ValueError("cards_json must be a JSON array of cards")
    if len(parsed) > MAX_DASHBOARD_CARDS:
        raise ValueError(
            f"a dashboard may hold at most {MAX_DASHBOARD_CARDS} cards, got {len(parsed)}"
        )
    for i, card in enumerate(parsed):
        if not isinstance(card, dict):
            raise ValueError(f"cards_json[{i}] must be an object")
        note_id = card.get("note_id")
        if not isinstance(note_id, str) or not note_id.strip():
            raise ValueError(f"cards_json[{i}] needs a non-empty string note_id")
        if "viz_config" in card and not isinstance(card["viz_config"], dict):
            raise ValueError(f"cards_json[{i}].viz_config must be an object")
        if "refresh_interval" in card and not isinstance(card["refresh_interval"], (int, float)):
            raise ValueError(f"cards_json[{i}].refresh_interval must be a number")
        if isinstance(card.get("refresh_interval"), bool):
            raise ValueError(f"cards_json[{i}].refresh_interval must be a number")
    return value


class _DashboardCardRules(BaseModel):
    """Shared so the rule cannot be added to create and forgotten on update — the shape
    this codebase produced five times in two days."""

    @field_validator("cards_json", check_fields=False)
    @classmethod
    def _check_cards(cls, v: str | None) -> str | None:
        return _validate_cards_json(v)


class DashboardCreate(_DashboardCardRules):
    project_id: str = Field(..., max_length=64)
    title: str = Field(max_length=200)
    layout_json: str | None = Field(None, max_length=100_000)
    cards_json: str | None = Field(None, max_length=500_000)
    is_shared: bool = True


class DashboardUpdate(_DashboardCardRules):
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
    user_role: str | None = None


@router.post("", response_model=DashboardResponse)
@limiter.limit("20/minute")
async def create_dashboard(
    request: Request,
    body: DashboardCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, body.project_id, user["user_id"], "editor")
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
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")
    dashboards = await _svc.list_for_project(db, project_id, user["user_id"])
    return dashboards[offset : offset + limit]


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
    role = await _membership_svc.require_role(db, dashboard.project_id, user["user_id"], "viewer")
    if dashboard.creator_id != user["user_id"] and not dashboard.is_shared:
        raise HTTPException(status_code=403, detail="Dashboard is private")
    resp = DashboardResponse.model_validate(dashboard)
    resp.user_role = role
    return resp


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
    await _membership_svc.require_role(db, dashboard.project_id, user["user_id"], "editor")
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
    await _membership_svc.require_role(db, dashboard.project_id, user["user_id"], "editor")
    await _svc.delete(db, dashboard.id)
    audit_log(
        "dashboard.delete",
        user_id=user["user_id"],
        project_id=dashboard.project_id,
        resource_type="dashboard",
        resource_id=dashboard.id,
    )
    return {"ok": True}
