import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.services.usage_service import UsageService

logger = logging.getLogger(__name__)

router = APIRouter()
_usage_svc = UsageService()


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
async def get_usage_stats(
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Return aggregated token usage stats for the authenticated user."""
    data = await _usage_svc.get_period_comparison(db, user["user_id"], days=days)
    return UsageStatsResponse(
        current_period=UsagePeriod(**data["current_period"]),
        previous_period=UsagePeriod(**data["previous_period"]),
        change_percent=ChangePercent(**data["change_percent"]),
        daily_breakdown=[DailyUsage(**d) for d in data["daily_breakdown"]],
        period_days=data["period_days"],
    )
