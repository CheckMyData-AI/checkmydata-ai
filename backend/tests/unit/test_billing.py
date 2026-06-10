"""Unit tests for the billing layer (T-BILL-1..5): entitlements + webhook sync."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.billing import Plan, Subscription
from app.services.billing_service import BillingService
from app.services.entitlement_service import (
    Entitlements,
    EntitlementService,
    QuotaExceededError,
    _strictest,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _plan(**kw) -> Plan:
    defaults = dict(
        id="pro",
        name="Pro",
        description="",
        stripe_price_id="price_pro_123",
        price_usd_month=49.0,
        daily_token_limit=1_000_000,
        monthly_token_limit=15_000_000,
        max_connections=5,
        max_projects=5,
        seats=3,
        trial_days=14,
        is_active=True,
        sort_order=1,
    )
    defaults.update(kw)
    return Plan(**defaults)


def _sub(**kw) -> Subscription:
    defaults = dict(
        user_id="u1",
        plan_id="pro",
        status="active",
        stripe_customer_id="cus_123",
        stripe_subscription_id="sub_123",
        cancel_at_period_end=False,
    )
    defaults.update(kw)
    return Subscription(**defaults)


def _db_returning(*results):
    """AsyncMock db whose execute() yields scalar_one_or_none results in order."""
    db = AsyncMock()
    mocks = []
    for r in results:
        m = MagicMock()
        m.scalar_one_or_none.return_value = r
        m.scalar_one.return_value = r
        mocks.append(m)
    db.execute = AsyncMock(side_effect=mocks)
    return db


# ---------------------------------------------------------------------------
# _strictest
# ---------------------------------------------------------------------------


class TestStrictest:
    def test_both_zero_is_unlimited(self):
        assert _strictest(0, 0) == 0

    def test_lowest_nonzero_wins(self):
        assert _strictest(100, 50) == 50
        assert _strictest(50, 100) == 50

    def test_zero_means_unlimited_not_strictest(self):
        assert _strictest(0, 100) == 100
        assert _strictest(100, 0) == 100


# ---------------------------------------------------------------------------
# EntitlementService
# ---------------------------------------------------------------------------


class TestEntitlements:
    @pytest.mark.asyncio
    async def test_billing_disabled_falls_back(self):
        with patch("app.services.entitlement_service.settings") as s:
            s.billing_enabled = False
            ent = await EntitlementService().get_entitlements(AsyncMock(), "u1")
        assert ent.plan_id == "free"
        assert ent.daily_token_limit == 0  # unlimited; config caps applied separately

    @pytest.mark.asyncio
    async def test_active_subscription_gets_plan_limits(self):
        svc = EntitlementService()
        db = _db_returning(_sub(status="active"), _plan())
        with patch("app.services.entitlement_service.settings") as s:
            s.billing_enabled = True
            ent = await svc.get_entitlements(db, "u1")
        assert ent.plan_id == "pro"
        assert ent.daily_token_limit == 1_000_000
        assert ent.max_connections == 5

    @pytest.mark.asyncio
    async def test_canceled_subscription_falls_to_free_plan(self):
        svc = EntitlementService()
        free = _plan(id="free", name="Free", daily_token_limit=100_000, max_connections=1)
        db = _db_returning(_sub(status="canceled"), free)
        with patch("app.services.entitlement_service.settings") as s:
            s.billing_enabled = True
            ent = await svc.get_entitlements(db, "u1")
        assert ent.plan_id == "free"
        assert ent.status == "canceled"

    @pytest.mark.asyncio
    async def test_past_due_keeps_paid_plan(self):
        svc = EntitlementService()
        db = _db_returning(_sub(status="past_due"), _plan())
        with patch("app.services.entitlement_service.settings") as s:
            s.billing_enabled = True
            ent = await svc.get_entitlements(db, "u1")
        assert ent.plan_id == "pro"

    @pytest.mark.asyncio
    async def test_missing_catalog_fails_open(self):
        svc = EntitlementService()
        db = _db_returning(None, None)  # no subscription, no plan row
        with patch("app.services.entitlement_service.settings") as s:
            s.billing_enabled = True
            ent = await svc.get_entitlements(db, "u1")
        assert ent.daily_token_limit == 0  # never lock users out

    @pytest.mark.asyncio
    async def test_effective_limits_strictest_of_plan_and_config(self):
        svc = EntitlementService()
        with (
            patch.object(
                svc,
                "get_entitlements",
                AsyncMock(
                    return_value=Entitlements(
                        plan_id="pro",
                        plan_name="Pro",
                        status="active",
                        daily_token_limit=1_000_000,
                        monthly_token_limit=0,
                        max_connections=5,
                        max_projects=5,
                        seats=3,
                    )
                ),
            ),
            patch("app.services.entitlement_service.settings") as s,
        ):
            s.user_daily_token_limit = 500_000
            s.user_monthly_token_limit = 2_000_000
            daily, monthly = await svc.effective_token_limits(AsyncMock(), "u1")
        assert daily == 500_000  # config stricter
        assert monthly == 2_000_000  # plan unlimited -> config applies

    @pytest.mark.asyncio
    async def test_connection_quota_blocks_at_limit(self):
        svc = EntitlementService()
        ent = Entitlements(
            plan_id="free",
            plan_name="Free",
            status="free",
            daily_token_limit=0,
            monthly_token_limit=0,
            max_connections=1,
            max_projects=1,
            seats=1,
        )
        db = _db_returning(1)  # already 1 connection
        with patch.object(svc, "get_entitlements", AsyncMock(return_value=ent)):
            with pytest.raises(QuotaExceededError) as exc_info:
                await svc.enforce_connection_quota(db, "u1")
        payload = exc_info.value.as_payload()
        assert payload["error"] == "plan_limit_reached"
        assert payload["resource"] == "connections"
        assert payload["upgrade_url"] == "/pricing"

    @pytest.mark.asyncio
    async def test_connection_quota_unlimited_is_noop(self):
        svc = EntitlementService()
        ent = Entitlements(
            plan_id="team",
            plan_name="Team",
            status="active",
            daily_token_limit=0,
            monthly_token_limit=0,
            max_connections=0,
            max_projects=0,
            seats=10,
        )
        db = AsyncMock()
        with patch.object(svc, "get_entitlements", AsyncMock(return_value=ent)):
            await svc.enforce_connection_quota(db, "u1")
        db.execute.assert_not_called()


# ---------------------------------------------------------------------------
# BillingService webhook sync
# ---------------------------------------------------------------------------


class TestWebhookSync:
    @pytest.mark.asyncio
    async def test_duplicate_event_ignored(self):
        from sqlalchemy.exc import IntegrityError

        svc = BillingService()
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock(side_effect=IntegrityError("dup", None, Exception()))
        processed = await svc.handle_event(
            db, {"id": "evt_1", "type": "invoice.paid", "data": {"object": {}}}
        )
        assert processed is False
        db.rollback.assert_awaited_once()
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unhandled_event_recorded_and_committed(self):
        svc = BillingService()
        db = AsyncMock()
        db.add = MagicMock()
        processed = await svc.handle_event(
            db, {"id": "evt_2", "type": "charge.refunded", "data": {"object": {}}}
        )
        assert processed is True
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_subscription_updated_syncs_state(self):
        svc = BillingService()
        sub = _sub(status="trialing")
        db = AsyncMock()
        db.add = MagicMock()
        with patch.object(svc, "_find_by_customer", AsyncMock(return_value=sub)):
            await svc.handle_event(
                db,
                {
                    "id": "evt_3",
                    "type": "customer.subscription.updated",
                    "data": {
                        "object": {
                            "id": "sub_999",
                            "customer": "cus_123",
                            "status": "active",
                            "cancel_at_period_end": True,
                            "current_period_start": 1750000000,
                            "current_period_end": 1752600000,
                            "trial_end": None,
                            "metadata": {"plan_id": "pro"},
                            "items": {"data": []},
                        }
                    },
                },
            )
        assert sub.status == "active"
        assert sub.stripe_subscription_id == "sub_999"
        assert sub.cancel_at_period_end is True
        assert sub.plan_id == "pro"

    @pytest.mark.asyncio
    async def test_subscription_deleted_downgrades_to_free(self):
        svc = BillingService()
        sub = _sub(status="active")
        db = AsyncMock()
        db.add = MagicMock()
        with patch.object(svc, "_find_by_customer", AsyncMock(return_value=sub)):
            await svc.handle_event(
                db,
                {
                    "id": "evt_4",
                    "type": "customer.subscription.deleted",
                    "data": {"object": {"customer": "cus_123"}},
                },
            )
        assert sub.status == "canceled"
        assert sub.plan_id == "free"
        assert sub.stripe_subscription_id is None

    @pytest.mark.asyncio
    async def test_payment_failed_sets_past_due(self):
        svc = BillingService()
        sub = _sub(status="active")
        db = AsyncMock()
        db.add = MagicMock()
        with patch.object(svc, "_find_by_customer", AsyncMock(return_value=sub)):
            await svc.handle_event(
                db,
                {
                    "id": "evt_5",
                    "type": "invoice.payment_failed",
                    "data": {"object": {"customer": "cus_123"}},
                },
            )
        assert sub.status == "past_due"

    @pytest.mark.asyncio
    async def test_payment_failed_does_not_resurrect_canceled(self):
        svc = BillingService()
        sub = _sub(status="canceled")
        db = AsyncMock()
        db.add = MagicMock()
        with patch.object(svc, "_find_by_customer", AsyncMock(return_value=sub)):
            await svc.handle_event(
                db,
                {
                    "id": "evt_6",
                    "type": "invoice.payment_failed",
                    "data": {"object": {"customer": "cus_123"}},
                },
            )
        assert sub.status == "canceled"
