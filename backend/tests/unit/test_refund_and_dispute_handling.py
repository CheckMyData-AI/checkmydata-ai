"""Money could leave without the credit it bought leaving with it.

`_HANDLED_EVENTS` listed six events and none of them was a reversal. A customer buys
$200 of LLM credit, the money lands in `purchased_balance_usd` via `_credit_top_up`, and
then the charge is refunded — by the operator, or by the customer's bank as a
chargeback. Stripe takes the money back; the credit stays. The account keeps both.

Three events close it, and the first one is **not** the obvious one. `charge.refunded`
carries the charge, whose `amount_refunded` is **cumulative** — two partial refunds emit
two events reading 5.00 and then 17.00, and debiting that field twice takes 22.00 for a
17.00 refund. Stripe's own guidance is explicit: *"During each partial refund, we send a
`refund.created` event"*, and *"Listen to the `refund.created` event instead of
`charge.refunded` to accurately process individual refunds."* So:

- `refund.created` — one event per refund, `amount` is that refund alone. `charge.refunded`
  stays deliberately unhandled, because handling both would double every reversal.
- `charge.dispute.created` — the bank has already pulled the funds. Same reversal, and
  the subscription's own fate arrives separately as `customer.subscription.deleted`,
  so this handler must not duplicate it.
- `charge.dispute.closed` — restore only when it was **won**, because a lost dispute is
  a refund that already happened.

The one distinction that matters and is easy to get backwards: a refunded *subscription
invoice* is not a refunded *top-up*. Only a one-time payment has `invoice = None`, and
only that one bought `purchased_balance_usd`. Debiting the purchased pocket for a
refunded month of subscription would take credit the customer never bought with it.
"""

from __future__ import annotations

import inspect

from app.services.billing_service import _HANDLED_EVENTS, BillingService


class TestTheReversalEventsAreHandledAtAll:
    def test_a_refund_is_handled(self) -> None:
        assert "refund.created" in _HANDLED_EVENTS, (
            "a refunded top-up leaves the purchased credit in place — the customer keeps "
            "the money and the credit"
        )

    def test_the_cumulative_event_stays_unhandled(self) -> None:
        """`charge.refunded` carries a cumulative `amount_refunded`. Handling it beside
        `refund.created` would debit every partial refund twice."""
        assert "charge.refunded" not in _HANDLED_EVENTS

    def test_a_dispute_is_handled(self) -> None:
        assert "charge.dispute.created" in _HANDLED_EVENTS, (
            "a chargeback pulls the funds and leaves the credit; nothing reverses it"
        )

    def test_a_closed_dispute_is_handled(self) -> None:
        assert "charge.dispute.closed" in _HANDLED_EVENTS


class TestTheReversalIsScopedToWhatTheMoneyBought:
    def test_only_a_non_invoice_charge_touches_purchased_credit(self) -> None:
        """A refunded subscription invoice must not debit the purchased pocket."""
        src = inspect.getsource(BillingService)
        assert '"invoice"' in src or 'get("invoice")' in src, (
            "nothing distinguishes a refunded top-up from a refunded subscription invoice"
        )

    def test_a_lost_dispute_does_not_restore_credit(self) -> None:
        src = inspect.getsource(BillingService)
        assert '"won"' in src, (
            "charge.dispute.closed restores credit regardless of outcome; a lost dispute "
            "is a refund that already happened"
        )


class TestTheDebitCannotInventMoney:
    """Behavioural, not a grep. This is the money path, and a source pattern proves
    nothing about what the arithmetic does."""

    @staticmethod
    def _svc_and_row(balance: float):
        from decimal import Decimal

        from app.models.llm_credit import LlmCredit
        from app.services.openrouter_credit_service import OpenRouterCreditService

        row = LlmCredit(user_id="u1", purchased_balance_usd=Decimal(str(balance)))
        row.key_hash = None  # no remote key: the ledger must still move

        svc = OpenRouterCreditService()

        async def _row(db, user_id):
            return row

        svc._row = _row  # type: ignore[method-assign]
        return svc, row

    class _Db:
        async def commit(self) -> None:
            return None

    async def test_a_debit_reduces_the_purchased_balance(self) -> None:
        svc, row = self._svc_and_row(200.0)
        out = await svc.debit(self._Db(), "u1", amount_usd=50.0, reason="refund")
        assert out["purchased_balance_usd"] == 150.0
        assert out["shortfall_usd"] == 0.0

    async def test_it_floors_at_zero_rather_than_inventing_a_debt(self) -> None:
        """A negative balance would make the next top-up silently pay off a debt the
        customer never agreed to."""
        svc, row = self._svc_and_row(20.0)
        out = await svc.debit(self._Db(), "u1", amount_usd=50.0, reason="chargeback")
        assert out["purchased_balance_usd"] == 0.0

    async def test_it_reports_what_it_could_not_take(self) -> None:
        """Credit already spent cannot be clawed back — the operator ate it, and a silent
        floor is how that loss stops being visible."""
        svc, _ = self._svc_and_row(20.0)
        out = await svc.debit(self._Db(), "u1", amount_usd=50.0, reason="chargeback")
        assert out["shortfall_usd"] == 30.0

    async def test_the_shortfall_is_logged_at_error(self, caplog) -> None:
        import logging

        svc, _ = self._svc_and_row(0.0)
        with caplog.at_level(logging.ERROR):
            await svc.debit(self._Db(), "u1", amount_usd=99.0, reason="chargeback")
        assert any("short by 99.00" in r.getMessage() for r in caplog.records)

    async def test_a_won_dispute_puts_the_credit_back(self) -> None:
        svc, _ = self._svc_and_row(10.0)
        out = await svc.restore(self._Db(), "u1", amount_usd=40.0)
        assert out["purchased_balance_usd"] == 50.0

    async def test_a_debit_before_provisioning_still_moves_the_ledger(self) -> None:
        """`top_up` refuses without a key; a reversal must not, or the credit survives
        the money going back."""
        svc, row = self._svc_and_row(75.0)
        assert row.key_hash is None
        out = await svc.debit(self._Db(), "u1", amount_usd=25.0, reason="refund")
        assert out["purchased_balance_usd"] == 50.0
