"""The eight seams where a Stripe integration loses money, checked against ours.

Reviewed 2026-08-31 against `sheleg-dev:stripe-billing` and Stripe's own documentation.
The integration has never executed — `STRIPE_SECRET_KEY` has never been set — so every
defect below is latent rather than observed, and would first appear on a real payment.

Three things the existing code already gets right, pinned here so a refactor cannot lose
them:

- the idempotency claim is taken BEFORE the work and released on failure, so a retry
  neither double-grants nor finds the event "processed" with the work lost;
- the signature is verified against the RAW body, not a re-serialized parse;
- `invoice.paid` does not grant product. Entitlements are derived from plan and status
  rather than credited per period, which makes the `billing_reason` trap — four months of
  product for four proration invoices — structurally impossible here.
"""

from __future__ import annotations

import inspect

from app.services import billing_service


def _src(obj) -> str:
    return inspect.getsource(obj)


class TestTheApiVersionIsPinned:
    """Unpinned, response shapes change on Stripe's schedule rather than ours — and that
    is what makes the period defect below live rather than theoretical."""

    def test_the_client_sets_an_api_version(self) -> None:
        assert "api_version" in _src(billing_service._stripe), (
            "the Stripe client pins no API version, so the account default governs and "
            "response shapes move under us"
        )

    def test_the_pinned_version_is_a_constant_not_a_literal_at_the_call_site(self) -> None:
        assert hasattr(billing_service, "STRIPE_API_VERSION")
        assert billing_service.STRIPE_API_VERSION >= "2025-09-30", (
            "flexible billing_mode and item-level periods both require a recent version"
        )


class TestThePeriodIsReadFromTheSubscriptionItem:
    """`current_period_start` / `current_period_end` moved from the subscription to its
    ITEM in `2025-07-30.basil`. Code reading the old top-level fields gets nothing and
    stores NULL, with no error anywhere — which is why this is asserted on behaviour
    rather than by grepping the sync method: the first version of this test looked for the
    word `items` in `_sync_subscription` and broke the moment the logic moved into a
    helper, while the behaviour was correct."""

    def test_the_item_period_is_used(self) -> None:
        payload = {
            "id": "sub_1",
            "items": {"data": [{"current_period_start": 1000, "current_period_end": 2000}]},
        }
        assert billing_service._period_from(payload) == (1000, 2000)

    def test_the_item_wins_over_a_stale_top_level_value(self) -> None:
        payload = {
            "current_period_start": 1,
            "current_period_end": 2,
            "items": {"data": [{"current_period_start": 1000, "current_period_end": 2000}]},
        }
        assert billing_service._period_from(payload) == (1000, 2000)

    def test_an_older_api_version_still_syncs(self) -> None:
        """A subscription created before the move carries the period at the top level.
        Refusing to read it would strand every row written under the old shape."""
        assert billing_service._period_from(
            {"current_period_start": 5, "current_period_end": 6}
        ) == (5, 6)

    def test_a_subscription_without_items_does_not_raise(self) -> None:
        """A deleted or malformed subscription has no items. Losing the period is
        acceptable; losing the whole webhook is not."""
        assert billing_service._period_from({}) == (None, None)
        assert billing_service._period_from({"items": {"data": []}}) == (None, None)
        assert billing_service._period_from({"items": None}) == (None, None)


class TestBillingModeIsChosenRatherThanInherited:
    """The choice is irreversible and made at creation. Leaving it to the account's API
    version default means it is decided by whoever last upgraded the account."""

    def test_checkout_sets_billing_mode(self) -> None:
        assert "billing_mode" in _src(billing_service.BillingService.create_checkout_session)


class TestMetadataIsWrittenTwice:
    """Session metadata does not propagate to the subscription. A year later the session
    is gone and every `customer.subscription.*` event carries only what was written into
    `subscription_data.metadata`."""

    async def test_subscription_data_carries_metadata(self) -> None:
        """Asserted on the built value, not on the source text. The first version of this
        test sliced 400 characters after the word `subscription_data` and found the
        SESSION's metadata sitting two arguments later — it passed while the defect was
        untouched."""
        captured: dict = {}

        class _Sessions:
            @staticmethod
            def create(**kwargs):
                captured.update(kwargs)
                return {"url": "https://stripe.test/s"}

        from unittest.mock import AsyncMock, MagicMock, patch

        svc = billing_service.BillingService()
        plan = MagicMock(id="pro", price_usd_month=49, trial_days=14, stripe_price_id="price_x")
        db = MagicMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: plan))
        stripe = MagicMock()
        stripe.checkout.Session = _Sessions
        user = MagicMock(id="u1", email="a@b.c", display_name="A")

        with (
            patch.object(billing_service, "_stripe", return_value=stripe),
            patch.object(svc, "_ensure_customer", new=AsyncMock(return_value="cus_1")),
            patch.object(svc, "_active_subscription_id", new=AsyncMock(return_value=None)),
        ):
            # Awaited, not driven through a nested loop: the first version called
            # `run_until_complete` inside pytest-asyncio's own loop, which passed alone
            # and failed in the full run — an order-dependent green.
            await svc.create_checkout_session(db, user, "pro")

        assert "metadata" in captured.get("subscription_data", {}), (
            "subscription_data carries no metadata; every later customer.subscription.* "
            "event will arrive with no way to identify the user"
        )
        assert captured["subscription_data"]["metadata"].get("user_id") == "u1"


class TestCheckoutRefusesToSellTwice:
    """A second active subscription for one account is a refund conversation, and the
    guard has to run before the money moves rather than after."""

    def test_an_active_subscription_blocks_a_new_checkout(self) -> None:
        """Named on the guard, not on the word "active" — which the first version of this
        test matched against `Plan.is_active.is_(True)` and passed on."""
        assert hasattr(billing_service.BillingService, "_active_subscription_id")
        src = _src(billing_service.BillingService.create_checkout_session)
        assert "_active_subscription_id" in src


class TestTheSuccessUrlCanBeVerified:
    """Stripe redirects when the card clears; the webhook lands when it lands. Without the
    session id on the return URL there is no way to close that window at all."""

    def test_success_url_carries_the_session_id(self) -> None:
        assert "{CHECKOUT_SESSION_ID}" in _src(
            billing_service.BillingService.create_checkout_session
        )


class TestASignatureFailureIsFourHundred:
    """A wrong signing secret answered 500, which tells Stripe to retry forever. It must
    fail loudly instead — the difference between a broken deploy you find in a minute and
    one you find in the retry queue."""

    def test_verify_failure_maps_to_a_client_error(self) -> None:
        from app.api.routes import billing as billing_routes

        src = _src(billing_routes.stripe_webhook)
        # Precisely the BillingError branch, not the generic one two lines below it —
        # the first version of this test sliced 600 characters and matched the neighbour.
        branch = src[src.index("except BillingError") :]
        branch = branch[: branch.index("except Exception")]
        assert "status_code=400" in branch, (
            "a BillingError from verify_webhook still answers 500, so a misconfigured "
            "secret makes Stripe retry forever rather than fail loudly"
        )


class TestThereIsAReconciliation:
    """Webhooks are best-effort. A delivery that never arrives leaves a paying customer
    without access and writes nothing anywhere that says so."""

    def test_the_service_exposes_a_reconcile_entrypoint(self) -> None:
        assert hasattr(billing_service.BillingService, "reconcile"), (
            "no reconciliation path exists; a missed webhook is permanent"
        )

    def test_reconcile_does_not_cancel_rows_that_were_never_stripes(self) -> None:
        """Comped and manually-granted plans carry no Stripe id. Cancelling them because
        Stripe has never heard of them is a self-inflicted outage."""
        src = _src(billing_service.BillingService.reconcile)
        assert "stripe_subscription_id" in src


class TestWhatAlreadyWorksStaysWorking:
    def test_the_idempotency_claim_precedes_the_work(self) -> None:
        src = _src(billing_service.BillingService.handle_event)
        assert src.index("db.add(ledger)") < src.index("_apply_event")

    def test_a_handler_failure_releases_the_claim(self) -> None:
        """Otherwise the retry finds the event already recorded and the work is lost for
        good — the failure mode that looks like nothing happened."""
        src = _src(billing_service.BillingService.handle_event)
        assert "rollback" in src[src.index("_apply_event") :]

    def test_invoice_paid_does_not_grant_product(self) -> None:
        src = _src(billing_service.BillingService._apply_event)
        after = src[src.index('"invoice.paid"') :]
        assert "_set_status_by_customer" in after[:200]
        assert "plan_id =" not in after[:200]
