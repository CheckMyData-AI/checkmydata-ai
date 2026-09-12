"""Board row 1b: the promise is dollars, and the gate counted tokens.

`PROMISED_CREDIT_USD` says `base` includes $30 of LLM credit a month. That promise
reached the gate by division: `$30 / BLENDED_USD_PER_MILLION_TOKENS` gave a token
ceiling, and the constant carries a **2.2x margin** over the $0.1145/M actually
measured on production. The margin is not caution — it is the cost of the wrong unit.
`agent_llm_model` is a per-project field the customer sets (`projects.py:52,97`), so
the customer picks the price per token and **no token figure can bound dollars**: at
the priciest stream the same ceiling is worth ~$221 against a $199 subscription, and
calibrating on that stream instead would cap `base` below a real account's measured
month (16 464 277 tokens in 30 days).

`token_usage.estimated_cost_usd` has been 100% populated since #285 (2026-09-04),
which is what makes the right unit available at last.

**Three things this had to settle, each a decision rather than a mechanism:**

- *What an unpriced row costs.* `_estimate_cost` returns `None` when the model is not
  in the live OpenRouter catalogue — a native OpenAI/Anthropic model, or a withdrawn
  one. Charging zero would be DATA-01's shape again: a figure computed from an
  absence. It is priced at a **conservative** rate and counted, and how much of the
  total was estimated is reported, so "the gate is guessing" is visible rather than
  implicit.
- *Whether the token ceiling survives.* It does, as a backstop for the case where cost
  accounting itself breaks. It is no longer the instrument, so the margin on
  `BLENDED_USD_PER_MILLION_TOKENS` becomes the backstop's slack rather than the
  enforcement.
- *Float.* DATA-06 is the precondition, not scope creep: summing IEEE-754 doubles is
  order-dependent, and this change turns that sum from a report into a gate.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest_asyncio.fixture
async def budget_db():
    import app.models  # noqa: F401  — registers every table on the metadata
    from app.models.base import Base

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _spend(svc, db, user_id: str, *, cost: Decimal | None, tokens: int = 1000) -> None:
    await svc.record_usage(
        db,
        user_id=user_id,
        project_id="p1",
        prompt_tokens=tokens // 2,
        completion_tokens=tokens - tokens // 2,
        total_tokens=tokens,
        provider="openrouter",
        model="test/model",
        estimated_cost_usd=float(cost) if cost is not None else None,
    )


class TestThePromiseReachesThePlanUndivided:
    def test_each_tier_carries_the_dollars_it_sells(self) -> None:
        from app.services.plan_catalogue import PAID_TIERS, PROMISED_CREDIT_USD

        by_id = {t["id"]: t for t in PAID_TIERS}
        for tier_id, promised in PROMISED_CREDIT_USD.items():
            assert by_id[tier_id]["monthly_cost_limit_usd"] == pytest.approx(promised), (
                f"{tier_id} sells ${promised} of credit and its ceiling says otherwise. "
                "The promise used to reach the gate only after a division by a blended "
                "rate carrying a 2.2x margin"
            )

    def test_enterprise_is_unlimited(self) -> None:
        from app.services.plan_catalogue import PAID_TIERS

        ent = next(t for t in PAID_TIERS if t["id"] == "enterprise")
        assert ent["monthly_cost_limit_usd"] == 0, "'no monthly cap' has no ceiling"
        assert ent["daily_cost_limit_usd"] == 0

    def test_a_day_is_a_third_of_a_month(self) -> None:
        """Same shape as the token ceilings: a runaway is bounded within a day."""
        from app.services.plan_catalogue import PAID_TIERS

        for tier in PAID_TIERS:
            monthly = tier["monthly_cost_limit_usd"]
            if not monthly:
                continue
            assert tier["daily_cost_limit_usd"] == pytest.approx(monthly / 3, rel=0.01)


class TestTheGateCountsDollars:
    async def test_spend_past_the_monthly_ceiling_is_refused(self, budget_db) -> None:
        from app.services.usage_service import BudgetExceededError, UsageService

        svc = UsageService()
        await _spend(svc, budget_db, "u1", cost=Decimal("31.00"))
        with pytest.raises(BudgetExceededError) as exc:
            await svc.check_budget(
                budget_db, "u1", daily_limit=0, monthly_limit=0, monthly_cost_limit=30.0
            )
        assert "$" in str(exc.value), f"a dollar ceiling must say dollars: {exc.value}"

    async def test_spend_inside_the_ceiling_is_allowed(self, budget_db) -> None:
        from app.services.usage_service import UsageService

        svc = UsageService()
        await _spend(svc, budget_db, "u1", cost=Decimal("29.00"))
        result = await svc.check_budget(
            budget_db, "u1", daily_limit=0, monthly_limit=0, monthly_cost_limit=30.0
        )
        assert result["allowed"]
        assert result["monthly_cost_remaining"] == pytest.approx(1.0, abs=0.01)

    async def test_a_zero_ceiling_is_unlimited(self, budget_db) -> None:
        """Every other column on `plans` reads 0 as unlimited; this must not differ."""
        from app.services.usage_service import UsageService

        svc = UsageService()
        await _spend(svc, budget_db, "u1", cost=Decimal("9999.00"))
        result = await svc.check_budget(
            budget_db, "u1", daily_limit=0, monthly_limit=0, monthly_cost_limit=0.0
        )
        assert result["allowed"]
        assert result["monthly_cost_remaining"] is None

    async def test_the_daily_ceiling_binds_too(self, budget_db) -> None:
        from app.services.usage_service import BudgetExceededError, UsageService

        svc = UsageService()
        await _spend(svc, budget_db, "u1", cost=Decimal("11.00"))
        with pytest.raises(BudgetExceededError):
            await svc.check_budget(
                budget_db, "u1", daily_limit=0, monthly_limit=0, daily_cost_limit=10.0
            )

    async def test_the_token_ceiling_still_binds_as_a_backstop(self, budget_db) -> None:
        """Cost accounting can itself break; the coarse net stays behind it."""
        from app.services.usage_service import BudgetExceededError, UsageService

        svc = UsageService()
        await _spend(svc, budget_db, "u1", cost=Decimal("0.01"), tokens=5_000_000)
        with pytest.raises(BudgetExceededError) as exc:
            await svc.check_budget(
                budget_db,
                "u1",
                daily_limit=0,
                monthly_limit=1_000_000,
                monthly_cost_limit=30.0,
            )
        assert "token" in str(exc.value).lower()


class TestAnUnpricedRowIsNotFree:
    def test_a_missing_price_is_estimated_conservatively(self) -> None:
        from app.services.plan_catalogue import (
            BLENDED_USD_PER_MILLION_TOKENS,
            UNPRICED_USD_PER_MILLION_TOKENS,
            price_unpriced_tokens,
        )

        assert UNPRICED_USD_PER_MILLION_TOKENS > BLENDED_USD_PER_MILLION_TOKENS, (
            "for a CEILING the blend was wrong because it applied to every token; for "
            "a FALLBACK on a row nobody could price, under-counting is the hole — an "
            "account routing everything through an unpriced model would escape"
        )
        assert price_unpriced_tokens(1_000_000) == pytest.approx(UNPRICED_USD_PER_MILLION_TOKENS)
        assert price_unpriced_tokens(0) == 0.0

    async def test_an_unpriced_row_counts_against_the_ceiling(self, budget_db) -> None:
        from app.services.usage_service import UsageService

        svc = UsageService()
        await _spend(svc, budget_db, "u1", cost=None, tokens=1_000_000)
        result = await svc.check_budget(
            budget_db, "u1", daily_limit=0, monthly_limit=0, monthly_cost_limit=1000.0
        )
        assert result["monthly_cost_used"] > 0, (
            "charging zero for a row whose price could not be resolved is DATA-01's "
            "shape again: a figure computed from an absence"
        )

    async def test_how_much_was_estimated_is_reported(self, budget_db) -> None:
        """'The gate is guessing' must be visible, not implicit."""
        from app.services.usage_service import UsageService

        svc = UsageService()
        await _spend(svc, budget_db, "u1", cost=Decimal("1.00"), tokens=1000)
        await _spend(svc, budget_db, "u1", cost=None, tokens=1_000_000)
        result = await svc.check_budget(
            budget_db, "u1", daily_limit=0, monthly_limit=0, monthly_cost_limit=1000.0
        )
        assert result["monthly_cost_estimated"] > 0
        assert result["monthly_cost_estimated"] < result["monthly_cost_used"]


class TestMoneyIsNotAFloat:
    """DATA-06 — the precondition, because this change makes the sum a GATE."""

    def test_the_money_columns_are_numeric(self) -> None:
        from sqlalchemy import Numeric

        from app.models.billing import Plan
        from app.models.request_trace import RequestTrace
        from app.models.token_usage import TokenUsage

        for model, column in (
            (TokenUsage, "estimated_cost_usd"),
            (RequestTrace, "estimated_cost_usd"),
            (Plan, "price_usd_month"),
            (Plan, "daily_cost_limit_usd"),
            (Plan, "monthly_cost_limit_usd"),
        ):
            kind = type(model.__table__.c[column].type)
            assert issubclass(kind, Numeric), (
                f"{model.__name__}.{column} is {kind.__name__}. `llm_credit.py` states "
                "the rule — summing thousands of IEEE-754 doubles is order-dependent, "
                "so the same month's spend differs between two calls that see the rows "
                "in a different plan order — and this column is now a GATE (DATA-06)"
            )

    def test_a_float_column_is_not_reintroduced(self) -> None:
        """Discovered, so a new money column joins the rule by being named like one."""
        from sqlalchemy import Float

        import app.models  # noqa: F401  — registers every table
        from app.models.base import Base

        offenders: list[str] = []
        for table in Base.metadata.tables.values():
            for column in table.columns:
                looks_like_money = column.name.endswith(("_usd", "_usd_month", "_cost"))
                if looks_like_money and isinstance(column.type, Float):
                    offenders.append(f"{table.name}.{column.name}")
        assert not offenders, f"{offenders} store money as a float (DATA-06)"


class TestTheCatalogueStillReconcilesIdempotently:
    """A `Numeric` column comes back as `Decimal`, and the reconcile compares fields.

    `Decimal("10.0000") == 10.0` is True, so every price the ladder holds today
    happens to survive a plain `!=`. `Decimal("199.9900") == 199.99` is **False** —
    199.99 has no exact binary form — so the first tier priced with real cents would
    make this reconcile rewrite the whole catalogue on every boot of every dyno,
    silently and for ever. A reconcile that always writes is not idempotent.
    """

    async def test_a_second_run_changes_nothing(self, budget_db) -> None:
        from app.ops.plan_catalogue_reconcile import reconcile_plan_catalogue

        factory = _factory_for(budget_db)
        first = await reconcile_plan_catalogue(factory)
        assert first.status == "reconciled"
        second = await reconcile_plan_catalogue(factory)
        assert second.status == "unchanged", (
            f"the second run rewrote {second.updated} row(s) with identical values"
        )

    async def test_a_price_with_real_cents_is_still_idempotent(self, budget_db) -> None:
        """The case a plain `!=` cannot survive, exercised rather than reasoned about."""
        from unittest.mock import patch

        from app.ops import plan_catalogue_reconcile as mod

        tiers = [dict(t) for t in mod.PAID_TIERS]
        tiers[0]["price_usd_month"] = 199.99
        tiers[0]["monthly_cost_limit_usd"] = 29.97
        factory = _factory_for(budget_db)
        with patch.object(mod, "PAID_TIERS", tiers):
            await mod.reconcile_plan_catalogue(factory)
            again = await mod.reconcile_plan_catalogue(factory)
        assert again.status == "unchanged", (
            f"$199.99 made the reconcile rewrite {again.updated} row(s) on every boot"
        )


def _factory_for(session):
    """An `async_sessionmaker`-shaped callable yielding the test's own session.

    The reconcile opens its own session; here it must reuse the in-memory one, or it
    writes to a database this test cannot see.
    """
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _cm():
        yield session

    class _Factory:
        def __call__(self):
            return _cm()

    return _Factory()
