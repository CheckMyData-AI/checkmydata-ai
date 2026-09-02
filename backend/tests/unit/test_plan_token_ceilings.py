"""The paid tiers had no token ceiling, and their own descriptions said they did.

`base` ($199) and `scale` ($599) shipped with `daily_token_limit = 0` and
`monthly_token_limit = 0`, where `0` means **unlimited** — while the same rows described
"$30/month of LLM credit at cost" and "$90/month". Nothing downstream caught it:
`USER_*_TOKEN_LIMIT` are unset in production, `effective_token_limits` takes the strictest
**non-zero** of plan and config, and `trialing` is an active status. A 14-day trial that had
paid nothing ran the agent against the operator's single provider key with no gate at all.

These tests hold the ceiling *and its derivation together*. A constant nobody can recompute
is the failure mode this remediation pass keeps meeting — `hybrid_min_score = 0.03` was a
number tuned against an `rrf_k` nobody re-read.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

MIGRATION = "c3d4e5f6a7b8_paid_tier_token_ceilings.py"


def _migration():
    path = pathlib.Path(__file__).parents[2] / "alembic" / "versions" / MIGRATION
    spec = importlib.util.spec_from_file_location("_ceiling_migration", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("plan_id", ["base", "scale"])
def test_both_paid_tiers_carry_a_ceiling(plan_id: str) -> None:
    lim = _migration().LIMITS[plan_id]
    assert lim["monthly"] > 0, f"{plan_id} is still unlimited — 0 does not mean 'no ceiling'"
    assert lim["daily"] > 0, f"{plan_id} can burn its whole month in an hour"


@pytest.mark.parametrize("plan_id", ["base", "scale"])
def test_the_ceiling_matches_the_credit_the_plan_promises(plan_id: str) -> None:
    """Recomputed from the measured blend, so the constant cannot drift from its reason."""
    mod = _migration()
    lim = mod.LIMITS[plan_id]
    implied_usd = lim["monthly"] / 1_000_000 * mod.BLENDED_USD_PER_MILLION_TOKENS
    assert implied_usd == pytest.approx(lim["promised_usd"], rel=0.05), (
        f"{plan_id}: {lim['monthly']:,} tokens is ${implied_usd:.2f} at "
        f"${mod.BLENDED_USD_PER_MILLION_TOKENS}/M, but the plan promises "
        f"${lim['promised_usd']}"
    )


@pytest.mark.parametrize("plan_id", ["base", "scale"])
def test_the_daily_cap_bounds_a_runaway_without_rationing(plan_id: str) -> None:
    """Above the measured p95 user-day (2 111 241), below the month it protects."""
    lim = _migration().LIMITS[plan_id]
    assert lim["daily"] >= 2_111_241, "the daily cap sits under a real user's 95th-percentile day"
    assert lim["daily"] < lim["monthly"], "a daily cap at or above the monthly one bounds nothing"


def test_scale_buys_three_times_base() -> None:
    """$599 vs $199 is not the ratio; $90 vs $30 of credit is, and it must stay legible."""
    lim = _migration().LIMITS
    assert lim["scale"]["monthly"] == 3 * lim["base"]["monthly"]


def test_the_migration_updates_rather_than_reinserts() -> None:
    path = pathlib.Path(__file__).parents[2] / "alembic" / "versions" / MIGRATION
    src = path.read_text(encoding="utf-8")
    assert "DELETE FROM plans" not in src.upper()
    assert "INSERT INTO plans" not in src.upper(), (
        "re-inserting would strand every subscription pointing at the old row"
    )


def test_zero_still_means_unlimited_everywhere_it_is_read() -> None:
    """The whole defect rests on this convention, so it is asserted rather than assumed."""
    import inspect

    from app.services.usage_service import UsageService

    src = inspect.getsource(UsageService.check_token_budget)
    assert "if not daily and not monthly" in src, (
        "the early return on unset limits changed shape; the ceilings above may no longer "
        "be what stands between a trial account and an unbounded provider bill"
    )
