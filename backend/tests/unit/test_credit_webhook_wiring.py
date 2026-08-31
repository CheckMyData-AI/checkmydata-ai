"""Where the credit ledger meets the webhook, and the two events that must not be confused.

`invoice.paid` fires for several different things, and granting on all of them is the most
expensive mistake available here. A quantity or plan change emits `subscription_update`
immediately, so a customer who upgraded and downgraded four times would be handed four
months of LLM allowance for four proration invoices. `billing_reason` is the only field
that separates them.

`checkout.session.completed` fires for both a new subscription and a credit top-up; `mode`
separates those. The amount comes from `amount_total` rather than from what we asked for,
because Stripe's page lets the customer name it — `custom_unit_amount` is how "no markup"
is expressed, and it means the figure we requested is not the figure they paid.
"""

from __future__ import annotations

import inspect

from app.services.billing_service import BillingService, _included_credit_for


class TestOnlyTheRenewalRollsThePeriod:
    def test_the_handler_gates_on_billing_reason(self) -> None:
        src = inspect.getsource(BillingService._apply_event)
        after = src[src.index('"invoice.paid"') :]
        assert "subscription_cycle" in after[:600], (
            "invoice.paid rolls the credit period unconditionally; a mid-cycle proration "
            "would grant a month of allowance"
        )

    def test_the_first_invoice_does_not_grant(self) -> None:
        """`subscription_create` is the checkout's own invoice. Checkout already
        provisioned; granting again would double the first month."""
        src = inspect.getsource(BillingService._apply_event)
        after = src[src.index('"invoice.paid"') :]
        assert "subscription_create" not in after[:600]


class TestATopUpIsSeparatedFromASubscription:
    def test_the_handler_gates_on_mode(self) -> None:
        src = inspect.getsource(BillingService._apply_event)
        after = src[src.index('"checkout.session.completed"') :]
        assert '"payment"' in after[:900], (
            "a subscription checkout and a credit top-up are handled alike; one of them "
            "would credit an account for buying a plan"
        )

    def test_the_amount_comes_from_what_was_paid(self) -> None:
        """Not from our requested figure. `custom_unit_amount` lets the customer set it on
        Stripe's page, which is the whole mechanism behind "no markup on tokens"."""
        src = inspect.getsource(BillingService._credit_top_up)
        assert "amount_total" in src


class TestAPaidTopUpIsNeverLostQuietly:
    def test_the_failure_path_logs_at_error_with_the_amount(self) -> None:
        """The charge has already succeeded. Raising would make Stripe retry a payment that
        cannot be un-taken, so the only honest outcome is a loud record a human can finish
        — and it has to carry the amount and the session id to be actionable."""
        src = inspect.getsource(BillingService._credit_top_up)
        assert "logger.error" in src
        assert "PAID BUT NOT CREDITED" in src
        assert "amount" in src and "session" in src

    def test_it_does_not_raise(self) -> None:
        src = inspect.getsource(BillingService._credit_top_up)
        body = src[src.index("try:") :]
        assert "raise" not in body


class TestTheGrantScalesWithTheTier:
    def test_base_and_scale_differ(self) -> None:
        base = type("P", (), {"id": "base"})()
        scale = type("P", (), {"id": "scale"})()
        assert _included_credit_for(base) == 30.0
        assert _included_credit_for(scale) == 90.0

    def test_an_unknown_or_missing_plan_grants_nothing(self) -> None:
        """A retired tier or a null plan must not silently grant the base allowance —
        crediting a tier nobody sells is money out for revenue that never came in."""
        assert _included_credit_for(None) == 0.0
        assert _included_credit_for(type("P", (), {"id": "team"})()) == 0.0
        assert _included_credit_for(type("P", (), {})()) == 0.0
