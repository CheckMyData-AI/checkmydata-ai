"""`check_budget` runs once per LLM call, and row 1b made it six queries (review).

The dollar ceiling was the right unit — that decision stands (ADR-0004). The
implementation was not: `check_budget` ran two token sums and then `_spend_since`
twice, each of which ran a priced sum and an unpriced-token sum. **Six round trips per
LLM call**, where there had been two, on a function the gating `DbUsageSink` calls after
*every* completion. A twenty-step orchestrator run went from 40 queries to 120.

The six figures come from one table, one user and one outer window, so they are one
query with conditional aggregates — fewer round trips than before the ceiling existed.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest_asyncio.fixture
async def counted_db():
    """A session that counts the SELECTs issued against `token_usage`."""
    import app.models  # noqa: F401
    from app.models.base import Base

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    counter = {"selects": 0}

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _count(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        if statement.lstrip().upper().startswith("SELECT") and "token_usage" in statement:
            counter["selects"] += 1

    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        session.info["counter"] = counter
        yield session
    await engine.dispose()


class TestTheGateIsOneQuery:
    async def test_a_budget_check_costs_one_round_trip(self, counted_db) -> None:
        from app.services.usage_service import UsageService

        svc = UsageService()
        await svc.record_usage(
            counted_db,
            user_id="u1",
            project_id="p1",
            prompt_tokens=10,
            completion_tokens=10,
            total_tokens=20,
            provider="openrouter",
            model="m",
            estimated_cost_usd=0.5,
        )
        counter = counted_db.info["counter"]
        counter["selects"] = 0

        await svc.check_budget(
            counted_db,
            "u1",
            daily_limit=1_000_000,
            monthly_limit=1_000_000,
            daily_cost_limit=10.0,
            monthly_cost_limit=30.0,
        )

        assert counter["selects"] == 1, (
            f"{counter['selects']} queries over `token_usage` for one budget check. "
            "This runs after EVERY LLM completion through the gating sink, so a "
            "twenty-step orchestrator run multiplies it by twenty"
        )

    async def test_the_figures_are_unchanged_by_the_collapse(self, counted_db) -> None:
        """One query must produce exactly what six did."""
        from app.services.usage_service import UsageService

        svc = UsageService()
        for cost, tokens in ((Decimal("2.00"), 100), (None, 1_000_000)):
            await svc.record_usage(
                counted_db,
                user_id="u1",
                project_id="p1",
                prompt_tokens=tokens // 2,
                completion_tokens=tokens - tokens // 2,
                total_tokens=tokens,
                provider="openrouter",
                model="m",
                estimated_cost_usd=float(cost) if cost is not None else None,
            )

        result = await svc.check_budget(
            counted_db, "u1", daily_limit=0, monthly_limit=0, monthly_cost_limit=1000.0
        )
        assert result["monthly_used"] == 1_000_100
        # 2.00 measured + 1M tokens priced at the unpriced fallback.
        from app.services.plan_catalogue import price_unpriced_tokens

        expected = 2.0 + price_unpriced_tokens(1_000_000)
        assert result["monthly_cost_used"] == pytest.approx(expected, rel=1e-6)
        assert result["monthly_cost_estimated"] == pytest.approx(
            price_unpriced_tokens(1_000_000), rel=1e-6
        )

    async def test_the_daily_window_is_still_a_subset_of_the_monthly_one(self, counted_db) -> None:
        """The collapse folds two windows into one scan; they must not become equal."""
        import datetime as dt

        from sqlalchemy import update

        from app.models.token_usage import TokenUsage
        from app.services.usage_service import UsageService

        svc = UsageService()
        await svc.record_usage(
            counted_db,
            user_id="u1",
            project_id="p1",
            prompt_tokens=5,
            completion_tokens=5,
            total_tokens=10,
            provider="openrouter",
            model="m",
            estimated_cost_usd=7.0,
        )
        # Move it to earlier this month but before today.
        earlier = dt.datetime.now(dt.UTC).replace(day=1, hour=0, minute=5, second=0, microsecond=0)
        if earlier.date() == dt.datetime.now(dt.UTC).date():
            pytest.skip("today is the first of the month; the two windows coincide")
        await counted_db.execute(update(TokenUsage).values(created_at=earlier.replace(tzinfo=None)))
        await counted_db.commit()

        result = await svc.check_budget(
            counted_db, "u1", daily_limit=0, monthly_limit=0, monthly_cost_limit=1000.0
        )
        # All four daily figures, not just the dollars: a planted defect that dropped
        # the day condition from `daily_tokens` alone passed a version of this test
        # that checked only `daily_cost_used`.
        assert result["monthly_used"] == 10
        assert result["monthly_cost_used"] == pytest.approx(7.0)
        assert result["daily_used"] == 0, (
            "a row from earlier in the month counted against TODAY's token total — the "
            "conditional aggregate lost its window"
        )
        assert result["daily_cost_used"] == pytest.approx(0.0), "the same for the dollar total"
        assert result["daily_cost_estimated"] == pytest.approx(0.0)
