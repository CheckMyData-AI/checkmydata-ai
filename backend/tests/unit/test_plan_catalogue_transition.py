"""Deactivating the old plans must not strand anyone standing on them.

The catalogue moved from free/pro/team to base/scale on 2026-08-31 because the old tiers
priced token allowances that cost more than the tier — Pro at $49 included 15M tokens worth
~$61, Team at $199 included 75M worth ~$306.

Two ways that migration could have broken production, both checked here:

- **The free fallback.** Every user without a subscription resolves to plan `free`. If
  deactivation had removed the row, or if `get_plan` filtered on `is_active`, every
  unsubscribed user would fall to `_fallback()`. Writing this file, I assumed that meant a
  lockout — it does not: the quota check reads `if not ent.max_connections: return`, so the
  fallback's zeros mean *unlimited* there exactly as they do for token limits, and the
  degrade is open. The last test in this file records that reading, because `0` meaning
  "no limit" in one place and "no allowance" in another is the kind of thing each reader
  otherwise re-derives, and one of them gets it backwards.
- **Sold subscriptions.** A live subscription may still point at `pro`. Deleting the row it
  references would leave it resolving to nothing.

`is_active` governs only what can be BOUGHT, which is why `create_checkout_session` filters
on it and `get_plan` does not. That asymmetry is load-bearing and easy to "tidy" away.
"""

from __future__ import annotations

import inspect

from app.services.entitlement_service import EntitlementService


def test_get_plan_does_not_filter_on_is_active() -> None:
    """A deactivated plan must still RESOLVE. Adding `is_active` here would lock out every
    unsubscribed user the moment the free plan is retired from sale."""
    src = inspect.getsource(EntitlementService.get_plan)
    assert "is_active" not in src, (
        "get_plan now filters on is_active, so a retired plan resolves to None — the free "
        "fallback and every already-sold subscription break together"
    )


def test_checkout_does_filter_on_is_active() -> None:
    """The other half of the asymmetry: a retired plan must not be purchasable."""
    from app.services.billing_service import BillingService

    src = inspect.getsource(BillingService.create_checkout_session)
    assert "is_active" in src


def test_the_migration_deactivates_rather_than_deletes() -> None:
    import pathlib

    versions = pathlib.Path(__file__).parents[2] / "alembic" / "versions"
    migration = next(p for p in versions.glob("*_plans_base_and_scale.py"))
    src = migration.read_text(encoding="utf-8")
    assert "is_active" in src
    assert "DELETE FROM plans" not in src.upper(), (
        "the migration deletes plan rows; a subscription pointing at one would resolve to nothing"
    )


def test_the_fallback_is_a_lockout_and_therefore_must_stay_unreachable() -> None:
    """Naming what `_fallback` actually means, because its zeros read like "unlimited"
    elsewhere in this codebase and here they mean the opposite.

    `0` is unlimited for TOKEN limits. For `max_connections` / `max_projects` the quota
    check reads `if not ent.max_connections: return` — so 0 is unlimited there too. The
    fallback is therefore permissive, not a lockout, and this test records that reading so
    the next person does not have to re-derive it.
    """
    ent = EntitlementService._fallback()
    assert ent.max_connections == 0
    assert ent.max_projects == 0

    src = inspect.getsource(EntitlementService.enforce_connection_quota)
    assert "if not ent.max_connections" in src, (
        "the quota check no longer treats 0 as unlimited, which turns _fallback() from a "
        "degrade-open into a lockout for every user when the catalogue is missing"
    )
