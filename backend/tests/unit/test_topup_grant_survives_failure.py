"""A top-up that failed to credit was marked permanently processed.

`handle_event` claims a `StripeEvent` row **before** `_apply_event` runs, and rolls it
back only if `_apply_event` raises. `_credit_top_up` caught every exception and returned,
so it never raised — the claim committed, the customer's money was taken, nothing was
granted, and every Stripe redelivery was then refused as a duplicate.

Its docstring pointed at "the reconciliation sweep" as the recovery. `reconcile()`
iterates `Subscription` rows; a top-up is a one-time payment and appears in none of them.
The named recovery path did not exist.

The reasoning in that comment is the interesting part, because it is nearly right:
"refusing the webhook would make Stripe retry a charge that cannot be un-taken." Retrying
the **webhook** does not retry the **charge** — it redelivers the event. Redelivery is
exactly what a failed grant needs, and it is the only retry Stripe offers.

Separately, `verify_checkout` — the success-page path that exists to close the window
before the webhook lands — handled the subscription branch and returned
`{"settled": true}` for a payment-mode session it never credited.

Mirroring that branch naively would have been worse than the bug: `_credit_top_up` is
**additive**, so the webhook and the success page would both grant. The docstring's
promise that "the idempotency ledger arbitrates" was true of the subscription branch,
whose writes are idempotent, and had no mechanism behind it for a top-up. So the claim is
now real and keyed on the checkout session, which both paths hold.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.billing import StripeEvent
from app.services.billing_service import BillingService


@pytest_asyncio.fixture()
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _session_obj(session_id: str = "cs_test_1", amount_cents: int = 20000) -> dict:
    return {
        "id": session_id,
        "mode": "payment",
        "amount_total": amount_cents,
        "client_reference_id": "user-1",
        "customer": "cus_1",
        "status": "complete",
        "payment_status": "paid",
    }


def _event(session_id: str = "cs_test_1", event_id: str = "evt_1") -> dict:
    return {
        "id": event_id,
        "type": "checkout.session.completed",
        "data": {"object": _session_obj(session_id)},
    }


class _Granter:
    """Stands in for OpenRouterCreditService.top_up."""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[float] = []
        self._fail = fail

    async def top_up(self, db, user_id, *, amount_usd):
        if self._fail:
            raise RuntimeError("OpenRouter is down")
        self.calls.append(amount_usd)
        return {"purchased_balance_usd": amount_usd}


@pytest.fixture
def granter(monkeypatch):
    g = _Granter()

    def _factory():
        return g

    monkeypatch.setattr("app.services.openrouter_credit_service.OpenRouterCreditService", _factory)
    return g


@pytest.fixture
def failing_granter(monkeypatch):
    g = _Granter(fail=True)
    monkeypatch.setattr("app.services.openrouter_credit_service.OpenRouterCreditService", lambda: g)
    return g


async def _rows(db) -> list[StripeEvent]:
    return list((await db.execute(select(StripeEvent))).scalars().all())


class TestAFailedGrantIsNotRecordedAsDone:
    async def test_handle_event_raises_so_stripe_redelivers(self, db, failing_granter) -> None:
        with pytest.raises(Exception, match="OpenRouter is down"):
            await BillingService().handle_event(db, _event())

    async def test_the_ledger_keeps_no_claim_for_a_failed_grant(self, db, failing_granter) -> None:
        """The claim is what refuses the redelivery. If it survives, the retry is
        rejected as a duplicate and the money is gone for good."""
        with pytest.raises(Exception):
            await BillingService().handle_event(db, _event())
        assert await _rows(db) == [], "the failed delivery is recorded as processed"

    async def test_a_redelivery_after_a_failure_can_still_credit(self, db, monkeypatch) -> None:
        g = _Granter(fail=True)
        monkeypatch.setattr(
            "app.services.openrouter_credit_service.OpenRouterCreditService", lambda: g
        )
        with pytest.raises(Exception):
            await BillingService().handle_event(db, _event())

        g._fail = False
        assert await BillingService().handle_event(db, _event()) is True
        assert g.calls == [200.0]


class TestTheGrantIsClaimedOncePerSession:
    async def test_a_second_delivery_of_the_same_session_does_not_double_credit(
        self, db, granter
    ) -> None:
        """Two Stripe events can carry the same checkout session — a redelivery under a
        new event id, or the success page racing the webhook. The money was paid once."""
        await BillingService().handle_event(db, _event(event_id="evt_1"))
        await BillingService().handle_event(db, _event(event_id="evt_2"))
        assert granter.calls == [200.0], f"credited {len(granter.calls)} times for one payment"


class TestTheSuccessPageCreditsWhatItReportsSettled:
    async def test_verify_checkout_credits_a_payment_session(
        self, db, granter, monkeypatch
    ) -> None:
        from app.models.user import User

        user = User(id="user-1", email="u@example.com", display_name="U", auth_provider="email")
        db.add(user)
        await db.flush()

        class _Sessions:
            @staticmethod
            def retrieve(session_id, **kw):
                return _session_obj(session_id)

        class _Stripe:
            checkout = type("c", (), {"Session": _Sessions})()

        monkeypatch.setattr("app.services.billing_service._stripe", lambda: _Stripe())
        out = await BillingService().verify_checkout(db, user, "cs_test_1")
        assert out["settled"] is True
        assert granter.calls == [200.0], (
            "the success page reported the payment settled and granted nothing"
        )

    async def test_the_webhook_after_the_success_page_does_not_double_credit(
        self, db, granter, monkeypatch
    ) -> None:
        from app.models.user import User

        user = User(id="user-1", email="u@example.com", display_name="U", auth_provider="email")
        db.add(user)
        await db.flush()

        class _Sessions:
            @staticmethod
            def retrieve(session_id, **kw):
                return _session_obj(session_id)

        class _Stripe:
            checkout = type("c", (), {"Session": _Sessions})()

        monkeypatch.setattr("app.services.billing_service._stripe", lambda: _Stripe())
        await BillingService().verify_checkout(db, user, "cs_test_1")
        await BillingService().handle_event(db, _event())
        assert granter.calls == [200.0], "the success page and the webhook both granted"


class TestTheDocstringNamesARecoveryThatExists:
    def test_it_names_redelivery_rather_than_a_sweep_that_does_not_cover_it(self) -> None:
        """Positive, not a grep for the old phrase — the docstring may well mention the
        sweep in order to say it was the wrong answer, and a test that forbids the word
        would push the correction out of the file that needs it."""
        import inspect

        src = inspect.getsource(BillingService._credit_top_up)
        assert "redeliver" in src, "nothing in the docstring says how a failed grant is retried"
        assert "reconciliation sweep is what finds" not in src, (
            "the docstring still points at reconcile() as the recovery; it iterates "
            "Subscription rows and a one-time payment is in none of them"
        )


def test_decimal_amount_is_not_floated_away() -> None:
    """20000 cents is 200.00, not 199.99999. Guarding the conversion the grant uses."""
    assert Decimal(20000) / 100 == Decimal("200")
