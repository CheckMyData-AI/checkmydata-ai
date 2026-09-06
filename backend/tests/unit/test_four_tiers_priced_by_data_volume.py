"""Four paid tiers, priced by how much data we index — and no free tier under them.

Three separate defects are pinned here, and the first one was live in production.

**1. A retired plan was still the fallback.** `free` was deactivated on 2026-08-31 so it
could not be BOUGHT, but `get_plan` deliberately does not filter on `is_active` (see
`test_plan_catalogue_transition.py` — sold subscriptions must keep resolving). So every
user without a subscription still resolved to `free` and inherited its 100 000-token daily
ceiling. Measured 2026-09-06 on production: the owner of the one real project burned
1 666 411 tokens on a full repository index, and the code<->DB sync queued behind it was
refused with "Daily token budget exceeded (1,666,411/100,000) — upgrade your plan at
/pricing", a page that cannot take payment because no Stripe keys are set. A 3 h 37 m index
completed and the step it exists to feed was turned away.

The fix is not to un-retire `free` and not to make `get_plan` filter — both break the sold
subscriptions the other test protects. It is that **no subscription means no plan**, which
is a different thing from "the cheapest plan".

**2. The catalogue promised a limit it had no column for.** `base` is described as "1 GB
index" and `scale` as "2 GB index per project"; nothing measured or enforced either,
because `plans` had no such column. A promise with no meter is not a tier boundary.

**3. Two tiers were missing.** The catalogue held base and scale; the product sells four.
"""

from __future__ import annotations

import inspect
import pathlib
from unittest.mock import AsyncMock, patch

import pytest

from app.models.billing import Plan
from app.services.entitlement_service import EntitlementService

VERSIONS = pathlib.Path(__file__).parents[2] / "alembic" / "versions"


def _migration_source() -> str:
    return next(VERSIONS.glob("*_plan_index_ceiling.py")).read_text(encoding="utf-8")


class TestNoSubscriptionIsNotTheCheapestPlan:
    """The production defect: an unsubscribed user inherited a retired plan's ceiling."""

    @pytest.mark.asyncio
    async def test_no_subscription_does_not_resolve_to_free(self) -> None:
        svc = EntitlementService()
        db = AsyncMock()
        with (
            patch("app.services.entitlement_service.settings") as s,
            patch.object(svc, "get_subscription", AsyncMock(return_value=None)),
            patch.object(svc, "get_plan", AsyncMock()) as get_plan,
        ):
            s.billing_enabled = True
            ent = await svc.get_entitlements(db, "u1")
        assert ent.plan_id != "free", (
            "an unsubscribed user resolved to the retired free plan; on production that "
            "meant a 100k daily ceiling and a refused code<->DB sync"
        )
        get_plan.assert_not_called(), "no subscription must not hit the plan catalogue at all"

    @pytest.mark.asyncio
    async def test_no_subscription_carries_no_plan_derived_ceiling(self) -> None:
        """0 means unlimited here, as it does everywhere else in this service.

        The operator's lever for an unpaid account is the global
        ``user_daily_token_limit`` config cap, which ``effective_token_limits``
        applies on top. Whether an unpaid project should be BLOCKED outright is a
        product decision nobody has made; until it is, this degrades open rather
        than reproducing the outage above.
        """
        svc = EntitlementService()
        with (
            patch("app.services.entitlement_service.settings") as s,
            patch.object(svc, "get_subscription", AsyncMock(return_value=None)),
        ):
            s.billing_enabled = True
            ent = await svc.get_entitlements(AsyncMock(), "u1")
        assert ent.daily_token_limit == 0
        assert ent.monthly_token_limit == 0
        assert ent.max_index_bytes == 0

    @pytest.mark.asyncio
    async def test_a_cancelled_subscription_also_lands_on_no_plan(self) -> None:
        """It used to land on `free`. With no free tier there is nothing below the
        paid ones, so a cancellation leaves the catalogue rather than descending it."""
        svc = EntitlementService()
        sub = type("S", (), {})()
        sub.status, sub.plan_id, sub.cancel_at_period_end, sub.current_period_end = (
            "canceled",
            "base",
            False,
            None,
        )
        with (
            patch("app.services.entitlement_service.settings") as s,
            patch.object(svc, "get_subscription", AsyncMock(return_value=sub)),
            patch.object(svc, "get_plan", AsyncMock()) as get_plan,
        ):
            s.billing_enabled = True
            ent = await svc.get_entitlements(AsyncMock(), "u1")
        assert ent.plan_id != "free"
        assert ent.status == "canceled"
        get_plan.assert_not_called()


class TestTheCatalogueHasFourPaidTiers:
    """The ladder lives in ONE place and reaches the database by reconcile, not by a
    literal seed inside a migration.

    A migration is a snapshot frozen at its revision; a price list is a living value. Seed
    the tiers in a migration and the two drift the first time a price changes — the code
    says $900, the row a customer resolves against says $199, and nothing compares them.
    The repository already carries this pattern for embeddings
    (`app/ops/embedding_reconcile.py`), so the tiers use it too: the migration adds the
    column, and boot upserts the catalogue.
    """

    def test_all_four_tiers_at_their_prices(self) -> None:
        from app.services.plan_catalogue import PAID_TIERS

        priced = {p["id"]: p["price_usd_month"] for p in PAID_TIERS}
        assert priced == {"base": 199, "scale": 599, "team": 900, "enterprise": 1500}

    def test_there_is_no_free_tier(self) -> None:
        from app.services.plan_catalogue import PAID_TIERS

        assert "free" not in {p["id"] for p in PAID_TIERS}
        assert all(p["price_usd_month"] > 0 for p in PAID_TIERS)

    def test_retired_tiers_are_deactivated_never_deleted(self) -> None:
        """A sold subscription may still reference one; deleting the row strands it."""
        import app.ops.plan_catalogue_reconcile as mod

        src = inspect.getsource(mod)
        assert "DELETE FROM plans" not in src.upper()
        assert "RETIRED_TIER_IDS" in src, "nothing deactivates the retired tiers"

    def test_the_retired_free_row_is_load_bearing_as_a_foreign_key(self) -> None:
        """`free` cannot simply be dropped, and the reason is not only sold subscriptions.

        `BillingService` writes `plan_id="free"` in two places — when it creates a
        subscription row for a new Stripe customer (`_get_or_create_subscription_row`)
        and when Stripe reports a subscription deleted. `Subscription.plan_id` is a
        foreign key onto `plans.id`, so deleting the row turns both writes into an
        integrity error at exactly the moment a cancellation is being processed.

        Neither write is a problem for entitlements: status `free` and `canceled` are in
        neither ACTIVE_STATUSES nor GRACE_STATUSES, so the resolution never reads the
        plan. The row is a foreign-key target and nothing more.
        """
        from app.services.plan_catalogue import RETIRED_TIER_IDS

        src = inspect.getsource(
            __import__("app.services.billing_service", fromlist=["x"]).BillingService
        )
        for slug in ("free",):
            if f'plan_id="{slug}"' in src or f'plan_id = "{slug}"' in src:
                assert slug in RETIRED_TIER_IDS, (
                    f"billing_service writes plan_id={slug!r} as a foreign key, but the "
                    f"catalogue neither sells it nor keeps it retired — the row would "
                    f"have to exist and nothing guarantees it does"
                )

    def test_the_migration_only_adds_the_column(self) -> None:
        src = _migration_source()
        assert "max_index_bytes" in src
        assert "price_usd_month" not in src, (
            "the migration seeds prices; that snapshot drifts from plan_catalogue.py "
            "the first time a tier is repriced"
        )

    def test_get_plan_still_does_not_filter_on_is_active(self) -> None:
        """Guarding the seam the previous transition established, because this change
        is exactly the kind that would 'tidy' it away."""
        assert "is_active" not in inspect.getsource(EntitlementService.get_plan)


class TestTheDataDimensionIsMeasurable:
    def test_plan_carries_an_index_ceiling(self) -> None:
        assert hasattr(Plan, "max_index_bytes"), (
            "the tier copy promises '1 GB index' / '2 GB index per project' and the "
            "catalogue has no column to hold it"
        )

    def test_every_tier_states_its_ceiling(self) -> None:
        from app.services.plan_catalogue import PAID_TIERS

        for tier in PAID_TIERS:
            assert "max_index_bytes" in tier, f"{tier['id']} is priced on an axis it does not carry"

    def test_the_ceilings_ascend_with_price(self) -> None:
        """A higher tier that bought less data would be a pricing bug nobody notices
        until a customer reads the table."""
        from app.services.plan_catalogue import PAID_TIERS

        ordered = sorted(PAID_TIERS, key=lambda p: p["price_usd_month"])
        ceilings = [p["max_index_bytes"] for p in ordered]
        unlimited_seen = False
        for prev, nxt in zip(ceilings, ceilings[1:], strict=False):
            if nxt == 0:  # 0 = unlimited, only ever the top of the ladder
                unlimited_seen = True
                continue
            assert not unlimited_seen, "a bounded tier sits above an unlimited one"
            assert nxt > prev, f"a dearer tier has the smaller data ceiling ({prev} -> {nxt})"

    def test_the_anchor_project_fits_the_entry_tier(self) -> None:
        """esim-php is the one real project and the operator places it on `base`.
        Measured 2026-09-06: 213 tables, 51 218 504 estimated rows, 759 knowledge
        documents, 25 695 code symbols. If `base` cannot hold it the ladder is wrong
        at its first rung."""
        from app.services.plan_catalogue import PAID_TIERS, estimate_index_bytes

        base = next(p for p in PAID_TIERS if p["id"] == "base")
        anchor = estimate_index_bytes(docs_bytes=3_500_000, symbols=25_695, edges=17_286)
        assert anchor < base["max_index_bytes"], (
            f"the anchor project measures {anchor} bytes against base's {base['max_index_bytes']}"
        )
