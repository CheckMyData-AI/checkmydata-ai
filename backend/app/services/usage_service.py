import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.token_usage import TokenUsage

logger = logging.getLogger(__name__)


class UsageService:
    async def record_usage(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        project_id: str,
        session_id: str | None = None,
        message_id: str | None = None,
        provider: str = "unknown",
        model: str = "unknown",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int | None = None,
        estimated_cost_usd: float | None = None,
    ) -> TokenUsage:
        if total_tokens is None:
            total_tokens = prompt_tokens + completion_tokens

        row = TokenUsage(
            user_id=user_id,
            project_id=project_id,
            session_id=session_id,
            message_id=message_id,
            provider=provider,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=estimated_cost_usd,
        )
        db.add(row)
        await db.commit()
        return row

    async def get_period_comparison(
        self,
        db: AsyncSession,
        user_id: str,
        days: int = 30,
    ) -> dict:
        now = datetime.now(timezone.utc)
        current_start = now - timedelta(days=days)
        previous_start = current_start - timedelta(days=days)

        current = await self._aggregate_period(db, user_id, current_start, now)
        previous = await self._aggregate_period(db, user_id, previous_start, current_start)

        change: dict[str, float | None] = {}
        for key in ("prompt_tokens", "completion_tokens", "total_tokens", "estimated_cost_usd", "request_count"):
            cur_val = current.get(key, 0) or 0
            prev_val = previous.get(key, 0) or 0
            if prev_val > 0:
                change[key] = round(((cur_val - prev_val) / prev_val) * 100, 1)
            elif cur_val > 0:
                change[key] = 100.0
            else:
                change[key] = 0.0

        daily = await self._daily_breakdown(db, user_id, current_start, now)

        return {
            "current_period": current,
            "previous_period": previous,
            "change_percent": change,
            "daily_breakdown": daily,
            "period_days": days,
        }

    async def _aggregate_period(
        self,
        db: AsyncSession,
        user_id: str,
        start: datetime,
        end: datetime,
    ) -> dict:
        stmt = select(
            func.coalesce(func.sum(TokenUsage.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(TokenUsage.completion_tokens), 0).label("completion_tokens"),
            func.coalesce(func.sum(TokenUsage.total_tokens), 0).label("total_tokens"),
            func.sum(TokenUsage.estimated_cost_usd).label("estimated_cost_usd"),
            func.count(TokenUsage.id).label("request_count"),
        ).where(
            TokenUsage.user_id == user_id,
            TokenUsage.created_at >= start,
            TokenUsage.created_at < end,
        )
        row = (await db.execute(stmt)).one()
        return {
            "prompt_tokens": int(row.prompt_tokens),
            "completion_tokens": int(row.completion_tokens),
            "total_tokens": int(row.total_tokens),
            "estimated_cost_usd": round(float(row.estimated_cost_usd), 6) if row.estimated_cost_usd else None,
            "request_count": int(row.request_count),
        }

    async def _daily_breakdown(
        self,
        db: AsyncSession,
        user_id: str,
        start: datetime,
        end: datetime,
    ) -> list[dict]:
        date_col = func.date(TokenUsage.created_at).label("date")
        stmt = (
            select(
                date_col,
                func.coalesce(func.sum(TokenUsage.prompt_tokens), 0).label("prompt_tokens"),
                func.coalesce(func.sum(TokenUsage.completion_tokens), 0).label("completion_tokens"),
                func.coalesce(func.sum(TokenUsage.total_tokens), 0).label("total_tokens"),
                func.sum(TokenUsage.estimated_cost_usd).label("estimated_cost_usd"),
                func.count(TokenUsage.id).label("request_count"),
            )
            .where(
                TokenUsage.user_id == user_id,
                TokenUsage.created_at >= start,
                TokenUsage.created_at < end,
            )
            .group_by(date_col)
            .order_by(date_col)
        )
        rows = (await db.execute(stmt)).all()
        return [
            {
                "date": str(r.date),
                "prompt_tokens": int(r.prompt_tokens),
                "completion_tokens": int(r.completion_tokens),
                "total_tokens": int(r.total_tokens),
                "estimated_cost_usd": round(float(r.estimated_cost_usd), 6) if r.estimated_cost_usd else None,
                "request_count": int(r.request_count),
            }
            for r in rows
        ]
