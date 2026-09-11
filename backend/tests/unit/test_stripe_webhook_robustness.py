"""Six ways a Stripe webhook lost money or resurrected a cancelled account.

P0-6; BILL-03, BILL-04, BILL-05, BILL-06, BILL-07, BILL-08.

`handle_event` already does the right thing: it claims the event id in a ledger row, applies
the event, and on an exception **rolls back and re-raises** — so the claim disappears, the
endpoint answers non-2xx, and Stripe redelivers. Four handlers underneath it swallowed their
failures and returned normally, so `handle_event` committed the claim and Stripe never
retried. The fix for two of them is to stop swallowing; the reason they swallowed is real
and is answered with a claim rather than with silence.

- **BILL-03** — a refund or chargeback whose reversal fails is committed as processed. The
  comment said "never raise: the money has already moved, and a failed webhook makes Stripe
  retry something that cannot be un-done". Retrying the *webhook* does not retry the
  *refund*; it retries **taking the credit back**, which is the thing that did not happen.
  What the comment was right about is double-application, and that is what the claim is for.
- **BILL-08** — a failed renewal is committed as processed, and the damage is not a skipped
  grant. `renew()` computes `spent = usage − usage_at_period_start` and bills the excess to
  the purchased pocket; a missed renewal leaves the watermark behind, so the *next* renewal
  charges purchased credit for spend the included allowance already covered.
- **BILL-04** — subscription events are applied unconditionally. Stripe does not guarantee
  order, and the `deleted` branch is a full teardown: an `updated` delivered after it
  resurrects a cancelled account and mints it a fresh spending key.
- **BILL-05** — the duplicate-subscription guard reads `stripe_subscription_id`, which is
  NULL until a webhook lands minutes later. Its own comment says it exists to stop the
  second charge *before* the money moves, and it cannot see a checkout that is in flight.
- **BILL-06** — the stale-catalogue fallback writes `metadata.plan_id` into a foreign-key
  column without checking it exists, so the recovery path 500s the webhook forever.
- **BILL-07** — `Charge.retrieve` is a blocking HTTP call made on the event loop, against
  the module's own stated invariant that every Stripe call is wrapped in `to_thread`.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import billing_service as mod
from app.services.billing_service import BillingService


def _db() -> MagicMock:
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.rollback = AsyncMock()
    db.begin_nested = MagicMock()
    return db


class TestAFailedReversalIsRetried:
    """BILL-03."""

    @pytest.mark.asyncio
    async def test_a_failed_debit_raises_so_the_claim_rolls_back(self) -> None:
        svc = BillingService()
        db = _db()
        with (
            patch.object(svc, "_claim_once", AsyncMock(return_value=True)),
            patch(
                "app.services.openrouter_credit_service.OpenRouterCreditService.debit",
                AsyncMock(side_effect=RuntimeError("provider down")),
            ),
            patch.object(svc, "_charge_owner", AsyncMock(return_value="u1")),
        ):
            with pytest.raises(Exception):
                await svc._reverse_purchased_credit(
                    db, charge_id="ch_1", amount_cents=1000, reason="refund", ref="re_1"
                )

    @pytest.mark.asyncio
    async def test_a_second_delivery_of_the_same_reversal_is_a_no_op(self) -> None:
        """The claim is what makes raising safe: a redelivery must not debit twice."""
        svc = BillingService()
        db = _db()
        debit = AsyncMock()
        with (
            patch.object(svc, "_claim_once", AsyncMock(return_value=False)),
            patch("app.services.openrouter_credit_service.OpenRouterCreditService.debit", debit),
            patch.object(svc, "_charge_owner", AsyncMock(return_value="u1")),
        ):
            await svc._reverse_purchased_credit(
                db, charge_id="ch_1", amount_cents=1000, reason="refund", ref="re_1"
            )
        debit.assert_not_awaited()


class TestAFailedRenewalIsRetried:
    """BILL-08."""

    def test_renew_credit_does_not_swallow(self) -> None:
        import textwrap

        src = textwrap.dedent(inspect.getsource(BillingService._renew_credit))
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            reraises = any(isinstance(n, ast.Raise) for n in ast.walk(node))
            assert reraises, (
                "_renew_credit swallows its failure, so handle_event commits the ledger "
                "row and Stripe never redelivers — and the next renewal then bills "
                "purchased credit for spend the missed allowance already covered"
            )


class TestOrderingIsGuarded:
    """BILL-04. Stripe does not promise delivery order; the teardown branch is total."""

    @pytest.mark.asyncio
    async def test_an_older_event_does_not_overwrite_a_newer_state(self) -> None:
        svc = BillingService()
        db = _db()
        row = SimpleNamespace(
            user_id="u1",
            plan_id="base",
            status="canceled",
            stripe_subscription_id="sub_1",
            last_event_created=2000,
            stripe_customer_id="cus_1",
            cancel_at_period_end=False,
            current_period_start=None,
            current_period_end=None,
            trial_end=None,
        )
        with patch.object(svc, "_find_by_customer", AsyncMock(return_value=row)):
            await svc._sync_subscription(
                db,
                {"customer": "cus_1", "id": "sub_1", "status": "active"},
                deleted=False,
                event_created=1000,
            )
        assert row.status == "canceled", (
            "an event older than the stored watermark resurrected a cancelled account"
        )

    @pytest.mark.asyncio
    async def test_a_newer_event_is_applied(self) -> None:
        svc = BillingService()
        db = _db()
        row = SimpleNamespace(
            user_id="u1",
            plan_id="base",
            status="past_due",
            stripe_subscription_id="sub_1",
            last_event_created=1000,
            stripe_customer_id="cus_1",
            cancel_at_period_end=False,
            current_period_start=None,
            current_period_end=None,
            trial_end=None,
        )
        with (
            patch.object(svc, "_find_by_customer", AsyncMock(return_value=row)),
            patch.object(svc, "_resolve_plan_id", AsyncMock(return_value="base")),
            patch.object(svc, "_provision_key", AsyncMock()),
        ):
            await svc._sync_subscription(
                db,
                {"customer": "cus_1", "id": "sub_1", "status": "active"},
                deleted=False,
                event_created=3000,
            )
        assert row.status == "active"
        assert row.last_event_created == 3000, "the watermark did not move"


class TestAnUnknownPlanIsNotWritten:
    """BILL-06. The recovery path wrote a foreign key it never checked."""

    @pytest.mark.asyncio
    async def test_a_metadata_plan_id_that_does_not_exist_is_refused(self) -> None:
        svc = BillingService()
        db = _db()
        db.execute = AsyncMock(return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: [])))
        obj = {
            "items": {"data": [{"price": {"id": "price_live"}}]},
            "metadata": {"plan_id": "ghost"},
        }
        resolved = await svc._resolve_plan_id(db, obj)
        assert resolved != "ghost", (
            "an unvalidated plan id goes into a foreign-key column and 500s every "
            "redelivery of this event, forever"
        )


class TestNoStripeCallBlocksTheLoop:
    """BILL-07, against the module's own stated invariant."""

    def test_every_stripe_sdk_call_is_threaded(self) -> None:
        source = pathlib.Path(inspect.getfile(mod)).read_text(encoding="utf-8")
        tree = ast.parse(source)
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            # `_stripe().X.Y(...)` — a direct SDK call, not wrapped in to_thread
            if not isinstance(func, ast.Attribute):
                continue
            root = func
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Call) and getattr(root.func, "id", "") == "_stripe":
                offenders.append(f"line {node.lineno}: {ast.unparse(node)[:60]}")
        assert not offenders, (
            "these call the Stripe SDK directly on the event loop; the module's own "
            f"docstring says every such call is wrapped in asyncio.to_thread: {offenders}"
        )


class TestASecondCheckoutIsRefusedWhileOneIsOpen:
    """BILL-05. The window between Checkout and the webhook is the whole defect."""

    @pytest.mark.asyncio
    async def test_a_checkout_in_flight_blocks_the_next_one(self) -> None:
        from datetime import UTC, datetime, timedelta

        svc = BillingService()
        db = _db()
        row = SimpleNamespace(
            user_id="u1",
            stripe_customer_id="cus_1",
            stripe_subscription_id=None,  # the webhook has not landed — the whole point
            status="free",
            checkout_pending_at=datetime.now(UTC) - timedelta(minutes=1),
        )
        plan = SimpleNamespace(
            id="base", price_usd_month=199, stripe_price_id="price_1", trial_days=14
        )
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: plan))
        with (
            patch.object(svc, "_active_subscription_id", AsyncMock(return_value=None)),
            patch.object(svc, "_get_or_create_subscription_row", AsyncMock(return_value=row)),
        ):
            with pytest.raises(mod.BillingError, match="already open"):
                await svc.create_checkout_session(db, SimpleNamespace(id="u1"), "base")

    @pytest.mark.asyncio
    async def test_a_stale_pending_marker_does_not_lock_the_account_out(self) -> None:
        """An abandoned checkout must not cost the customer a day of not being able to buy."""
        from datetime import UTC, datetime, timedelta

        assert mod.CHECKOUT_PENDING_WINDOW < timedelta(hours=1), (
            "the window only has to cover Checkout -> webhook, which is seconds to minutes"
        )
        svc = BillingService()
        db = _db()
        row = SimpleNamespace(
            user_id="u1",
            stripe_customer_id="cus_1",
            stripe_subscription_id=None,
            status="free",
            checkout_pending_at=datetime.now(UTC) - mod.CHECKOUT_PENDING_WINDOW * 2,
        )
        # A plan with no Stripe price makes this fail LATER, at `_price_id_for` — which is
        # what proves the pending guard let it through rather than stopping it.
        plan = SimpleNamespace(id="base", price_usd_month=199, stripe_price_id=None, trial_days=14)
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: plan))
        with (
            patch.object(svc, "_active_subscription_id", AsyncMock(return_value=None)),
            patch.object(svc, "_get_or_create_subscription_row", AsyncMock(return_value=row)),
        ):
            with pytest.raises(mod.BillingError) as exc:
                await svc.create_checkout_session(db, SimpleNamespace(id="u1"), "base")
        assert "already open" not in str(exc.value)
