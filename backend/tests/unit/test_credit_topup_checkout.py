"""Buying credit is a payment, not a subscription, and the difference is load-bearing.

`mode` is what the webhook reads to tell a top-up from a plan purchase
(`_apply_event` → `_credit_top_up`). Sent as `subscription`, a $50 credit purchase would
create a recurring charge; handled as a subscription, it would grant a plan.

The amount is never sent. The price carries `custom_unit_amount`, so Stripe's own page asks
for the figure — which is how "we take no margin on API tokens" stays literally true rather
than true of a pack size we chose. It also means the figure we might have requested is not
the figure they paid, which is why the webhook credits `amount_total`.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.billing_service import BillingError, BillingService


def _svc(*, key_hash: str | None = "hash-1", price: str = "price_topup"):
    svc = BillingService()
    captured: dict = {}

    class _Sessions:
        @staticmethod
        def create(**kwargs):
            captured.update(kwargs)
            return {"url": "https://stripe.test/topup"}

    stripe = MagicMock()
    stripe.checkout.Session = _Sessions
    credit = MagicMock(key_hash=key_hash) if key_hash is not None else None
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: credit))
    return svc, stripe, db, captured, price


async def _run(svc, stripe, db, price):
    with (
        patch("app.services.billing_service._stripe", return_value=stripe),
        patch.object(svc, "_ensure_customer", new=AsyncMock(return_value="cus_1")),
        patch("app.services.billing_service.settings") as s,
    ):
        s.stripe_price_credit_topup = price
        s.app_url = "https://checkmydata.ai"
        s.billing_success_path = "/dashboard?billing=success"
        s.billing_cancel_path = "/pricing"
        return await svc.create_topup_session(db, MagicMock(id="u1"))


class TestItIsAPaymentNotASubscription:
    async def test_mode_is_payment(self) -> None:
        svc, stripe, db, captured, price = _svc()
        await _run(svc, stripe, db, price)
        assert captured["mode"] == "payment", (
            "a credit purchase sent as `subscription` becomes a recurring charge, and the "
            "webhook reads `mode` to tell the two apart"
        )

    async def test_no_amount_is_sent(self) -> None:
        """`custom_unit_amount` is on the price; naming a figure here would defeat it."""
        svc, stripe, db, captured, price = _svc()
        await _run(svc, stripe, db, price)
        for forbidden in ("amount", "unit_amount", "amount_total"):
            assert forbidden not in captured

    async def test_metadata_reaches_the_payment_intent(self) -> None:
        """The session is gone by the time a refund or dispute arrives; those events carry
        the PaymentIntent, so the link to the user has to be on it too."""
        svc, stripe, db, captured, price = _svc()
        await _run(svc, stripe, db, price)
        assert captured["payment_intent_data"]["metadata"]["user_id"] == "u1"
        assert captured["metadata"]["kind"] == "credit_topup"

    async def test_the_return_url_can_be_verified(self) -> None:
        svc, stripe, db, captured, price = _svc()
        await _run(svc, stripe, db, price)
        assert "{CHECKOUT_SESSION_ID}" in captured["success_url"]


class TestItRefusesWhenThereIsNothingToCredit:
    async def test_no_key_means_no_sale(self) -> None:
        """Taking the money for a balance with no key to spend from is the one failure here
        that leaves a customer paid-up with nothing."""
        svc, stripe, db, captured, price = _svc(key_hash=None)
        with pytest.raises(BillingError, match="subscription"):
            await _run(svc, stripe, db, price)
        assert captured == {}

    async def test_no_row_at_all_means_no_sale(self) -> None:
        svc = BillingService()
        db = MagicMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
        stripe = MagicMock()
        with pytest.raises(BillingError):
            await _run(svc, stripe, db, "price_topup")

    async def test_an_unconfigured_price_is_named(self) -> None:
        """The setting is named in the message: "not configured" without the key sends the
        reader to the Stripe dashboard rather than to their own env."""
        svc, stripe, db, captured, _ = _svc()
        with pytest.raises(BillingError, match="STRIPE_PRICE_CREDIT_TOPUP"):
            await _run(svc, stripe, db, "")
