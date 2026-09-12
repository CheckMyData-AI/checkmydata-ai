import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.token_usage import TokenUsage
from app.services.plan_catalogue import price_unpriced_tokens

logger = logging.getLogger(__name__)

DEFAULT_DAILY_TOKEN_LIMIT = 0
DEFAULT_MONTHLY_TOKEN_LIMIT = 0


class BudgetExceededError(Exception):
    """Raised when a user or project exceeds their token budget."""

    def __init__(self, message: str, *, used: int, limit: int):
        super().__init__(message)
        self.used = used
        self.limit = limit


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
        # Falsy, not `is None`. Measured on production 2026-09-09: rows carrying
        # prompt=175 669 / completion=4 587 and `total_tokens = 0`, because no adapter
        # reports a total and every caller reads `usage.get("total_tokens", 0)` — which
        # produces a NUMBER where there was an ABSENCE, so an `is None` check never fired.
        #
        # `check_budget` sums exactly this column, so those calls charged **nothing**
        # against the user's daily, monthly and plan-derived limits, with billing on.
        # The same defect was fixed in `router.py::_usage_total` on 2026-08-28 for the
        # per-call sink; the four request-level writers in `chat.py` were left behind.
        # The derivation belongs here instead — the one funnel every writer passes,
        # including the next one somebody adds.
        #
        # A provider-reported total is never zero, so this never overrides one: prompt
        # caching makes the billed total differ from the sum and the provider is the
        # authority on what it charged. And a call with no prompt and no completion
        # stays at zero, which is also the truth.
        if not total_tokens:
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

    async def _spend_since(self, db: AsyncSession, user_id: str, since: datetime) -> tuple:
        """(dollars spent, dollars that were ESTIMATED) since *since* — row 1b.

        Two sums over the same window, because a row whose model carried no price is
        charged rather than forgiven and the reader is entitled to know how much of
        the total that was. `_estimate_cost` returns ``None`` for a model absent from
        the live OpenRouter catalogue, which is usually a NATIVE provider model — the
        expensive kind — so charging zero would let an account escape by picking one.
        """
        priced_stmt = select(func.coalesce(func.sum(TokenUsage.estimated_cost_usd), 0)).where(
            TokenUsage.user_id == user_id,
            TokenUsage.created_at >= since,
            TokenUsage.estimated_cost_usd.is_not(None),
        )
        priced = float((await db.execute(priced_stmt)).scalar_one() or 0)

        unpriced_stmt = select(func.coalesce(func.sum(TokenUsage.total_tokens), 0)).where(
            TokenUsage.user_id == user_id,
            TokenUsage.created_at >= since,
            TokenUsage.estimated_cost_usd.is_(None),
        )
        unpriced_tokens = int((await db.execute(unpriced_stmt)).scalar_one() or 0)
        estimated = price_unpriced_tokens(unpriced_tokens)
        return priced + estimated, estimated

    async def check_budget(
        self,
        db: AsyncSession,
        user_id: str,
        *,
        daily_limit: int = DEFAULT_DAILY_TOKEN_LIMIT,
        monthly_limit: int = DEFAULT_MONTHLY_TOKEN_LIMIT,
        daily_cost_limit: float = 0.0,
        monthly_cost_limit: float = 0.0,
    ) -> dict:
        """Check if user is within budget.  Limits of 0 mean unlimited.

        **Dollars are the gate; tokens are the backstop (row 1b).** Every tier sells
        dollars of LLM credit, and that promise used to reach this function only after
        being divided by a blended $/M rate carrying a 2.2x margin — a margin that is
        the cost of the wrong unit, not caution: `agent_llm_model` is a per-project
        field the customer sets, so the customer picks the price per token and no token
        figure can bound dollars. `estimated_cost_usd` has been 100% populated since
        2026-09-04, which is what made the right unit available.

        The token ceilings stay behind the dollar ones, for the case where cost
        accounting itself breaks — an unreachable price table over a long window would
        otherwise remove the gate rather than loosen it. The stricter breach raises
        first, and the dollar one is checked first because it is the one the customer
        was sold.

        Returns ``allowed``, the used/limit/remaining triple in BOTH units, and
        ``*_cost_estimated`` — how much of the spend was priced by fallback rather than
        measured, so "the gate is guessing" is visible rather than implicit.
        Raises ``BudgetExceededError`` when a non-zero limit is breached.
        """
        now = datetime.now(UTC)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        daily_stmt = select(func.coalesce(func.sum(TokenUsage.total_tokens), 0)).where(
            TokenUsage.user_id == user_id,
            TokenUsage.created_at >= today_start,
        )
        daily_used = int((await db.execute(daily_stmt)).scalar_one())

        monthly_stmt = select(func.coalesce(func.sum(TokenUsage.total_tokens), 0)).where(
            TokenUsage.user_id == user_id,
            TokenUsage.created_at >= month_start,
        )
        monthly_used = int((await db.execute(monthly_stmt)).scalar_one())

        daily_cost, daily_estimated = await self._spend_since(db, user_id, today_start)
        monthly_cost, monthly_estimated = await self._spend_since(db, user_id, month_start)

        result = {
            "allowed": True,
            "daily_used": daily_used,
            "monthly_used": monthly_used,
            "daily_limit": daily_limit or None,
            "monthly_limit": monthly_limit or None,
            "daily_remaining": (daily_limit - daily_used) if daily_limit else None,
            "monthly_remaining": (monthly_limit - monthly_used) if monthly_limit else None,
            "daily_cost_used": round(daily_cost, 6),
            "monthly_cost_used": round(monthly_cost, 6),
            "daily_cost_limit": daily_cost_limit or None,
            "monthly_cost_limit": monthly_cost_limit or None,
            "daily_cost_remaining": (
                round(daily_cost_limit - daily_cost, 6) if daily_cost_limit else None
            ),
            "monthly_cost_remaining": (
                round(monthly_cost_limit - monthly_cost, 6) if monthly_cost_limit else None
            ),
            "daily_cost_estimated": round(daily_estimated, 6),
            "monthly_cost_estimated": round(monthly_estimated, 6),
        }

        if daily_cost_limit and daily_cost >= daily_cost_limit:
            result["allowed"] = False
            raise BudgetExceededError(
                f"Daily spend limit exceeded (${daily_cost:,.2f}/${daily_cost_limit:,.2f})",
                used=int(daily_used),
                limit=int(daily_limit or 0),
            )

        if monthly_cost_limit and monthly_cost >= monthly_cost_limit:
            result["allowed"] = False
            raise BudgetExceededError(
                f"Monthly spend limit exceeded (${monthly_cost:,.2f}/${monthly_cost_limit:,.2f})",
                used=int(monthly_used),
                limit=int(monthly_limit or 0),
            )

        if daily_limit and daily_used >= daily_limit:
            result["allowed"] = False
            raise BudgetExceededError(
                f"Daily token budget exceeded ({daily_used:,}/{daily_limit:,})",
                used=daily_used,
                limit=daily_limit,
            )

        if monthly_limit and monthly_used >= monthly_limit:
            result["allowed"] = False
            raise BudgetExceededError(
                f"Monthly token budget exceeded ({monthly_used:,}/{monthly_limit:,})",
                used=monthly_used,
                limit=monthly_limit,
            )

        return result

    async def check_token_budget(self, db: AsyncSession, user_id: str) -> str | None:
        """Return an error message when the user's token budget is exhausted,
        else ``None``. Budget *checks* fail open (infra error must not take the
        agent down); budget *breaches* always block. Limits come from plan
        entitlements with a config fallback — the strictest non-zero wins.
        """
        try:
            from app.services.entitlement_service import EntitlementService

            svc = EntitlementService()
            daily, monthly = await svc.effective_token_limits(db, user_id)
            daily_cost, monthly_cost = await svc.effective_cost_limits(db, user_id)
        except Exception:
            logger.warning("Entitlement lookup failed; using config limits", exc_info=True)
            from app.config import settings

            daily = settings.user_daily_token_limit
            monthly = settings.user_monthly_token_limit
            # No config counterpart for the dollar ceilings (row 1b): a spend cap is a
            # statement about a subscription, and this branch is the one where we could
            # not read which subscription it is. Falling back to the token brake alone
            # loosens the gate; inventing a dollar figure here would enforce one nobody
            # was sold.
            daily_cost = monthly_cost = 0.0
        if not daily and not monthly and not daily_cost and not monthly_cost:
            return None
        try:
            await self.check_budget(
                db,
                user_id,
                daily_limit=daily,
                monthly_limit=monthly,
                daily_cost_limit=daily_cost,
                monthly_cost_limit=monthly_cost,
            )
        except BudgetExceededError as exc:
            logger.warning("Token budget exceeded for user=%s: %s", user_id[:8], exc)
            return str(exc) + " — upgrade your plan at /pricing to continue."
        except Exception:
            logger.warning("Token budget check failed; allowing request", exc_info=True)
        return None

    async def get_period_comparison(
        self,
        db: AsyncSession,
        user_id: str,
        days: int = 30,
        *,
        project_id: str | None = None,
    ) -> dict:
        """Aggregate token usage for a user over the last ``days``.

        When ``project_id`` is passed, aggregation is further scoped to that
        project. This is what :mod:`app.api.routes.usage` passes when the
        caller supplies a ``project_id`` query param (membership is enforced
        upstream).
        """
        now = datetime.now(UTC)
        current_start = now - timedelta(days=days)
        previous_start = current_start - timedelta(days=days)

        current = await self._aggregate_period(
            db, user_id, current_start, now, project_id=project_id
        )
        previous = await self._aggregate_period(
            db, user_id, previous_start, current_start, project_id=project_id
        )

        change: dict[str, float | None] = {}
        _keys = (
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "estimated_cost_usd",
            "request_count",
        )
        for key in _keys:
            cur_val = current.get(key, 0) or 0
            prev_val = previous.get(key, 0) or 0
            if prev_val > 0:
                change[key] = round(((cur_val - prev_val) / prev_val) * 100, 1)
            elif cur_val > 0:
                change[key] = 100.0
            else:
                change[key] = 0.0

        daily = await self._daily_breakdown(db, user_id, current_start, now, project_id=project_id)

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
        *,
        project_id: str | None = None,
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
        if project_id is not None:
            stmt = stmt.where(TokenUsage.project_id == project_id)
        row = (await db.execute(stmt)).one()
        return {
            "prompt_tokens": int(row.prompt_tokens),
            "completion_tokens": int(row.completion_tokens),
            "total_tokens": int(row.total_tokens),
            "estimated_cost_usd": (
                round(float(row.estimated_cost_usd), 6) if row.estimated_cost_usd else None
            ),
            "request_count": int(row.request_count),
        }

    async def _daily_breakdown(
        self,
        db: AsyncSession,
        user_id: str,
        start: datetime,
        end: datetime,
        *,
        project_id: str | None = None,
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
        if project_id is not None:
            stmt = stmt.where(TokenUsage.project_id == project_id)
        rows = (await db.execute(stmt)).all()
        return [
            {
                "date": str(r.date),
                "prompt_tokens": int(r.prompt_tokens),
                "completion_tokens": int(r.completion_tokens),
                "total_tokens": int(r.total_tokens),
                "estimated_cost_usd": (
                    round(float(r.estimated_cost_usd), 6) if r.estimated_cost_usd else None
                ),
                "request_count": int(r.request_count),
            }
            for r in rows
        ]
