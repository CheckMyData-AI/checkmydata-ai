"""The window between Stripe's redirect and Stripe's webhook.

Stripe redirects the moment the card clears; the webhook lands when it lands. In between,
the customer is looking at a success page while the database knows nothing about their
payment. This endpoint performs exactly the writes the webhook would and lets the
idempotency ledger arbitrate.

It is a safety net and never the primary path: a customer who closes the tab must still get
what they paid for, and only the webhook can do that. Code that grants on the redirect
alone is the failure this whole design exists to avoid.

The load-bearing check is ownership. Without it, any authenticated user who learns a `cs_…`
id claims someone else's purchase — and the refusal has to be indistinguishable from a
missing session, or the response tells a prober which ids exist.
"""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.billing_service import BillingError, BillingService


def _session(**over) -> dict:
    base = {
        "id": "cs_test_1",
        "client_reference_id": "u1",
        "status": "complete",
        "payment_status": "paid",
        "mode": "subscription",
        "customer": "cus_1",
        "subscription": None,
    }
    base.update(over)
    return base


def _svc_and_db(session: dict):
    svc = BillingService()
    stripe = MagicMock()
    stripe.checkout.Session.retrieve = MagicMock(return_value=session)
    row = MagicMock(plan_id="base", status="active", stripe_customer_id=None)
    db = MagicMock()
    db.commit = AsyncMock()
    return svc, stripe, row, db


class TestOwnershipIsChecked:
    async def test_another_users_session_is_refused(self) -> None:
        svc, stripe, row, db = _svc_and_db(_session(client_reference_id="someone_else"))
        with (
            patch("app.services.billing_service._stripe", return_value=stripe),
            patch.object(svc, "_get_or_create_subscription_row", new=AsyncMock(return_value=row)),
        ):
            with pytest.raises(BillingError):
                await svc.verify_checkout(db, MagicMock(id="u1"), "cs_test_1")

    async def test_the_refusal_is_indistinguishable_from_a_missing_session(self) -> None:
        """Different messages would turn this into an oracle for which `cs_…` ids exist."""
        svc, stripe, row, db = _svc_and_db(_session(client_reference_id="someone_else"))
        with (
            patch("app.services.billing_service._stripe", return_value=stripe),
            patch.object(svc, "_get_or_create_subscription_row", new=AsyncMock(return_value=row)),
        ):
            with pytest.raises(BillingError) as wrong_owner:
                await svc.verify_checkout(db, MagicMock(id="u1"), "cs_test_1")

        # A StripeError, not a RuntimeError: the handler is narrowed to Stripe's own
        # hierarchy, so an arbitrary exception now propagates rather than being reported as
        # a missing session — which is the intent, and which this test asserted past for
        # one revision by throwing something the code was never meant to catch.
        import stripe as _stripe_sdk

        stripe.checkout.Session.retrieve = MagicMock(
            side_effect=_stripe_sdk.InvalidRequestError("No such session", param="id")
        )
        with patch("app.services.billing_service._stripe", return_value=stripe):
            with pytest.raises(BillingError) as absent:
                await svc.verify_checkout(db, MagicMock(id="u1"), "cs_test_1")

        assert str(wrong_owner.value) == str(absent.value)

    async def test_metadata_is_accepted_when_client_reference_id_is_absent(self) -> None:
        """Both are written at checkout; a session created before `client_reference_id` was
        set still has to verify."""
        svc, stripe, row, db = _svc_and_db(
            _session(client_reference_id=None, metadata={"user_id": "u1"})
        )
        with (
            patch("app.services.billing_service._stripe", return_value=stripe),
            patch.object(svc, "_get_or_create_subscription_row", new=AsyncMock(return_value=row)),
        ):
            result = await svc.verify_checkout(db, MagicMock(id="u1"), "cs_test_1")
        assert result["settled"] is True


class TestItOnlySettlesWhatStripeCallsSettled:
    @pytest.mark.parametrize(
        "over,reason",
        [({"status": "open"}, "incomplete"), ({"payment_status": "unpaid"}, "unpaid")],
    )
    async def test_an_unsettled_session_grants_nothing(self, over, reason) -> None:
        svc, stripe, row, db = _svc_and_db(_session(**over))
        with (
            patch("app.services.billing_service._stripe", return_value=stripe),
            patch.object(svc, "_get_or_create_subscription_row", new=AsyncMock(return_value=row)),
        ):
            result = await svc.verify_checkout(db, MagicMock(id="u1"), "cs_test_1")
        assert result == {"settled": False, "reason": reason}
        db.commit.assert_not_awaited()

    async def test_a_settled_session_links_the_customer(self) -> None:
        svc, stripe, row, db = _svc_and_db(_session())
        with (
            patch("app.services.billing_service._stripe", return_value=stripe),
            patch.object(svc, "_get_or_create_subscription_row", new=AsyncMock(return_value=row)),
        ):
            await svc.verify_checkout(db, MagicMock(id="u1"), "cs_test_1")
        assert row.stripe_customer_id == "cus_1"
        db.commit.assert_awaited()


class TestItRefusesAnythingThatIsNotASessionId:
    @pytest.mark.parametrize("bad", ["", "sub_123", "../../etc/passwd", "pi_123"])
    async def test_a_non_session_id_is_refused_before_stripe_is_called(self, bad) -> None:
        """Cheap, and it keeps a URL-supplied string from reaching a paid API call."""
        svc = BillingService()
        stripe = MagicMock()
        with patch("app.services.billing_service._stripe", return_value=stripe):
            with pytest.raises(BillingError):
                await svc.verify_checkout(MagicMock(), MagicMock(id="u1"), bad)
        stripe.checkout.Session.retrieve.assert_not_called()


def test_it_is_documented_as_a_net_rather_than_the_path() -> None:
    """Recorded in the docstring because the next reader's temptation is to drop the
    webhook once this exists — and a customer who closes the tab would then pay for
    nothing."""
    doc = inspect.getdoc(BillingService.verify_checkout) or ""
    assert "never the primary path" in doc
