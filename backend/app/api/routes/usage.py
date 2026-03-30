import logging

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.rate_limit import limiter
from app.services.membership_service import MembershipService
from app.services.usage_service import UsageService

logger = logging.getLogger(__name__)

router = APIRouter()
_usage_svc = UsageService()
_membership_svc = MembershipService()


class UsagePeriod(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float | None = None
    request_count: int = 0


class DailyUsage(BaseModel):
    date: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float | None = None
    request_count: int = 0


class ChangePercent(BaseModel):
    prompt_tokens: float | None = 0.0
    completion_tokens: float | None = 0.0
    total_tokens: float | None = 0.0
    estimated_cost_usd: float | None = 0.0
    request_count: float | None = 0.0


class UsageStatsResponse(BaseModel):
    current_period: UsagePeriod
    previous_period: UsagePeriod
    change_percent: ChangePercent
    daily_breakdown: list[DailyUsage]
    period_days: int


@router.get("/stats", response_model=UsageStatsResponse)
@limiter.limit("30/minute")
async def get_usage_stats(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
    project_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Return aggregated token usage stats for the authenticated user.

    When project_id is provided, enforces owner-level access.
    """
    if project_id:
        await _membership_svc.require_role(db, project_id, user["user_id"], "owner")
    data = await _usage_svc.get_period_comparison(db, user["user_id"], days=days)
    return UsageStatsResponse(
        current_period=UsagePeriod(**data["current_period"]),
        previous_period=UsagePeriod(**data["previous_period"]),
        change_percent=ChangePercent(**data["change_percent"]),
        daily_breakdown=[DailyUsage(**d) for d in data["daily_breakdown"]],
        period_days=data["period_days"],
    )
