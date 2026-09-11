"""The paid tiers had no token ceiling, and their own descriptions said they did.

`base` ($199) and `scale` ($599) shipped with `daily_token_limit = 0` and
`monthly_token_limit = 0`, where `0` means **unlimited** — while the same rows described
"$30/month of LLM credit at cost" and "$90/month". Nothing downstream caught it:
`USER_*_TOKEN_LIMIT` are unset in production, `effective_token_limits` takes the strictest
**non-zero** of plan and config, and `trialing` is an active status. A 14-day trial that had
paid nothing ran the agent against the operator's single provider key with no gate at all.

**Then the fix was written into the wrong file, and this test certified it anyway.**
Migration `c3d4e5f6a7b8` wrote 2 500 000 / 7 500 000 into `plans`; `PAID_TIERS` still
declared `0`; and `plan_catalogue_reconcile` — a blind field-by-field overwrite running in
the FastAPI lifespan — reset the column seconds later, on every boot. Two writers, and the
one that runs last held zeros. The earlier version of this file loaded the migration with
`importlib` and asserted against its `LIMITS` dict, so it never read `PAID_TIERS` and never
touched the `plans` table: it certified a constant nothing in production ever resolves
against (DATA-01, audit 2026-09-09).

These tests hold the ceiling *and its derivation together*, and they read the value from
the place a request actually resolves against — the table, after the reconcile. A constant
nobody can recompute is the failure mode this remediation pass keeps meeting; a constant
nobody can *reach* is the one it met next.
"""

from __future__ import annotations

import pathlib

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.billing import Plan
from app.ops.plan_catalogue_reconcile import reconcile_plan_catalogue
from app.services import plan_catalogue as cat

#: The heaviest real user-day and user-month measured on production over the 30 days to
#: 2026-09-11. A cap below an **observed** figure is a false cut-off by construction, not a
#: risk of one — the first calibration of this ceiling set `base` at 16 200 000 tokens a
#: month against a real month of 16 464 277, and would have refused the workload `base` is
#: sold for. The earlier floor here was a 95th-percentile day of 2 111 241 measured
#: 2026-08-31; the peak has roughly doubled since, which is why the check is now against
#: the peak rather than a percentile of it.
PEAK_USER_DAY_TOKENS = 3_968_564
PEAK_USER_MONTH_TOKENS = 16_464_277

#: Tiers that are sold with a bounded allowance. `enterprise` is deliberately absent: its
#: own description promises "LLM credit at cost with no monthly cap", so `0` there is the
#: honest value rather than a forgotten one.
BOUNDED_TIERS = ["base", "scale", "team"]


def _tier(plan_id: str) -> dict:
    return next(t for t in cat.PAID_TIERS if t["id"] == plan_id)


@pytest.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=[Plan.__table__]))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.parametrize("plan_id", BOUNDED_TIERS)
def test_every_sold_tier_carries_a_ceiling(plan_id: str) -> None:
    tier = _tier(plan_id)
    assert tier["monthly_token_limit"] > 0, (
        f"{plan_id} is still unlimited in PAID_TIERS — 0 does not mean 'no ceiling', it "
        "means no gate, and PAID_TIERS is what the reconcile writes into the table"
    )
    assert tier["daily_token_limit"] > 0, f"{plan_id} can burn its whole month in an hour"


def test_enterprise_is_unlimited_on_purpose() -> None:
    """Not an omission: the tier's own description sells "no monthly cap"."""
    tier = _tier("enterprise")
    assert tier["monthly_token_limit"] == 0
    assert "no monthly cap" in tier["description"]


@pytest.mark.parametrize("plan_id", BOUNDED_TIERS)
def test_the_ceiling_matches_the_credit_the_plan_promises(plan_id: str) -> None:
    """Recomputed from the measured blend, so the constant cannot drift from its reason."""
    tier = _tier(plan_id)
    promised = cat.PROMISED_CREDIT_USD[plan_id]
    implied_usd = tier["monthly_token_limit"] / 1_000_000 * cat.BLENDED_USD_PER_MILLION_TOKENS
    assert implied_usd == pytest.approx(promised, rel=0.05), (
        f"{plan_id}: {tier['monthly_token_limit']:,} tokens is ${implied_usd:.2f} at "
        f"${cat.BLENDED_USD_PER_MILLION_TOKENS}/M, but the plan promises ${promised}"
    )


@pytest.mark.parametrize("plan_id", BOUNDED_TIERS)
def test_the_promise_in_the_description_is_the_promise_in_the_table(plan_id: str) -> None:
    """The dollar figure is written twice — in prose and in the derivation. Pin them."""
    tier = _tier(plan_id)
    assert f"${cat.PROMISED_CREDIT_USD[plan_id]:g}/month of LLM credit" in tier["description"], (
        f"{plan_id}: PROMISED_CREDIT_USD and the tier description disagree about the "
        "credit the customer is sold"
    )


@pytest.mark.parametrize("plan_id", BOUNDED_TIERS)
def test_the_daily_cap_bounds_a_runaway_without_rationing(plan_id: str) -> None:
    """Above the heaviest measured user-day, below the month it protects."""
    tier = _tier(plan_id)
    assert tier["daily_token_limit"] >= PEAK_USER_DAY_TOKENS, (
        "the daily cap sits under a real user's heaviest measured day"
    )
    assert tier["daily_token_limit"] < tier["monthly_token_limit"], (
        "a daily cap at or above the monthly one bounds nothing"
    )


@pytest.mark.parametrize("plan_id", BOUNDED_TIERS)
def test_the_monthly_cap_clears_the_heaviest_month_anyone_has_run(plan_id: str) -> None:
    """The cheapest tier must not refuse the workload it is sold for.

    `base` is "1 project, 5 data sources, 1 GB index" — which is exactly the production
    project that used 16 464 277 tokens in 30 days. A ceiling under that number turns the
    gate from a runaway bound into a refusal of ordinary use, and the first draft of this
    calibration did precisely that by 264 277 tokens.
    """
    tier = _tier(plan_id)
    assert tier["monthly_token_limit"] > PEAK_USER_MONTH_TOKENS, (
        f"{plan_id} caps at {tier['monthly_token_limit']:,} tokens/month, under the "
        f"{PEAK_USER_MONTH_TOKENS:,} a real account already used in 30 days"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("plan_id", BOUNDED_TIERS)
async def test_the_reconcile_carries_the_ceiling_into_the_table(
    session_factory, plan_id: str
) -> None:
    """DATA-01 itself: what a request resolves against is the row, after the lifespan ran.

    The reconcile is the *last* writer — it runs in the FastAPI lifespan, after the release
    phase's `alembic upgrade head`. So a ceiling that exists only in a migration is a
    ceiling that exists only between two log lines.
    """
    result = await reconcile_plan_catalogue(session_factory)
    assert result.status in {"reconciled", "unchanged"}, result

    async with session_factory() as session:
        row = (await session.execute(select(Plan).where(Plan.id == plan_id))).scalar_one()

    assert row.monthly_token_limit > 0, (
        f"after the reconcile, {plan_id} resolves to an unlimited monthly ceiling — this "
        "is the state production was in on every boot"
    )
    assert row.daily_token_limit > 0


@pytest.mark.asyncio
async def test_a_second_reconcile_does_not_move_the_ceiling(session_factory) -> None:
    """Idempotence, because this runs on every dyno start and every restart."""
    await reconcile_plan_catalogue(session_factory)
    async with session_factory() as session:
        first = (await session.execute(select(Plan).where(Plan.id == "base"))).scalar_one()
        first_monthly = first.monthly_token_limit

    second = await reconcile_plan_catalogue(session_factory)
    assert second.status == "unchanged", second
    async with session_factory() as session:
        again = (await session.execute(select(Plan).where(Plan.id == "base"))).scalar_one()
    assert again.monthly_token_limit == first_monthly


def test_the_migration_is_no_longer_a_second_writer() -> None:
    """One home. The migration ran; it must not keep writing a number PAID_TIERS owns.

    Read as an AST rather than as text: the first draft of this guard grepped the file for
    ``UPDATE plans SET`` and went red against the comment that *explains* why the statement
    was removed. A guard that matches prose is the shape the same audit files as TEST-04.
    """
    import ast

    path = (
        pathlib.Path(__file__).parents[2]
        / "alembic"
        / "versions"
        / "c3d4e5f6a7b8_paid_tier_token_ceilings.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    upgrade = next(
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and n.name == "upgrade"
    )
    calls = [n for n in ast.walk(upgrade) if isinstance(n, ast.Call)]
    assert not calls, (
        f"the migration's upgrade() still executes {len(calls)} call(s); two writers for "
        "plans.*_token_limit is how the ceiling was erased on every boot (DATA-01)"
    )


def test_the_catalogue_docstring_no_longer_justifies_zero_ceilings() -> None:
    """The docstring was the *reason* the zeros survived review: it argued that the

    OpenRouter key's dollar balance was "the only place that can enforce it mid-request".
    The key is never presented to the provider (BILL-01), so that sentence justified an
    unarmed gate with an unarmed gate.
    """
    doc = cat.__doc__ or ""
    assert "Token ceilings stay 0" not in doc, (
        "the docstring still tells the next reader to keep the ceilings at zero"
    )
