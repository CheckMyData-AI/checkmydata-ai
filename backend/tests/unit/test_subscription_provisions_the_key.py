"""The billing model's whole ceiling was never armed for a single account.

`b48fcfc1524b` created `llm_credit` — two pockets over one OpenRouter counter, an
`included_grant_usd` that expires monthly and a `purchased_balance_usd` that does not —
and `OpenRouterCreditService.provision` fills it, creating a per-account key with a
dollar limit. **Nothing called `provision`.** Not `_sync_subscription`, not checkout, not
the reconcile sweep; `grep` found no caller in `backend/`, `frontend/` or `scripts/`.

So every request ran against one shared operator key with no per-account ceiling, and
`create_topup_session` refused every top-up with "no LLM key to credit yet" — the feature
was unreachable because the thing it depends on was never created.

`revoke` had the mirror problem: cancelling a subscription left the key alive and
spending.

Both are wired to the subscription's own transitions here, and both are allowed to raise.
That is deliberate and follows the top-up fix: `handle_event` rolls its idempotency claim
back on an exception, so Stripe redelivers and the provisioning is retried. Swallowing
would leave a paying customer with no key and no second attempt.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.billing import Plan, Subscription
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
        session.add(Plan(id="base", name="Base", price_usd_month=199, is_active=True))
        session.add(Plan(id="scale", name="Scale", price_usd_month=599, is_active=True))
        session.add(
            Subscription(
                user_id="user-1", stripe_customer_id="cus_1", plan_id="free", status="free"
            )
        )
        await session.commit()
        yield session
    await engine.dispose()


class _Credit:
    def __init__(self, *, fail: bool = False) -> None:
        self.provisioned: list[tuple[str, float]] = []
        self.revoked: list[str] = []
        self.sessions: list = []
        self._fail = fail

    async def provision(self, db, user_id, *, included_usd):
        # The session is recorded, not ignored. A stub that shrugs at `db` let the first
        # version of this wiring pass `None` — which reads fine and dies in production at
        # `self._row(db, …)`, because the real service needs the session to find the row
        # and to commit.
        self.sessions.append(db)
        if self._fail:
            raise RuntimeError("OpenRouter is down")
        self.provisioned.append((user_id, included_usd))
        return "sk-or-test"

    async def revoke(self, db, user_id):
        self.sessions.append(db)
        if self._fail:
            raise RuntimeError("OpenRouter is down")
        self.revoked.append(user_id)
        return True


@pytest.fixture
def credit(monkeypatch):
    c = _Credit()
    monkeypatch.setattr("app.services.openrouter_credit_service.OpenRouterCreditService", lambda: c)
    return c


def _sub_obj(status: str = "active", price: str = "price_base") -> dict:
    return {
        "id": "sub_1",
        "customer": "cus_1",
        "status": status,
        "items": {"data": [{"price": {"id": price}}]},
        "metadata": {"plan_id": "base"},
    }


@pytest.fixture(autouse=True)
def _prices(monkeypatch):
    monkeypatch.setattr("app.config.settings.stripe_price_base", "price_base", raising=False)
    monkeypatch.setattr("app.config.settings.stripe_price_scale", "price_scale", raising=False)


class TestActivationArmsTheCeiling:
    async def test_an_active_subscription_provisions_a_key(self, db, credit) -> None:
        await BillingService()._sync_subscription(db, _sub_obj("active"), deleted=False)
        assert credit.provisioned == [("user-1", 30.0)], (
            "no per-account key was created, so the ceiling the billing model is built on "
            "does not exist and every request runs on the shared operator key"
        )

    async def test_a_trial_is_armed_too(self, db, credit) -> None:
        """A 14-day trial has paid nothing and is exactly the account that must not run
        against the operator's key without a ceiling."""
        await BillingService()._sync_subscription(db, _sub_obj("trialing"), deleted=False)
        assert credit.provisioned == [("user-1", 30.0)]

    async def test_the_grant_follows_the_tier(self, db, credit) -> None:
        await BillingService()._sync_subscription(
            db, _sub_obj("active", price="price_scale"), deleted=False
        )
        assert credit.provisioned == [("user-1", 90.0)]

    async def test_a_past_due_subscription_is_not_armed(self, db, credit) -> None:
        """Only an active or trialing subscription earns a ceiling; `past_due` has not
        paid and `incomplete` may never."""
        await BillingService()._sync_subscription(db, _sub_obj("past_due"), deleted=False)
        assert credit.provisioned == []


class TestTheRealSessionIsHandedOver:
    async def test_provision_receives_the_session_not_none(self, db, credit) -> None:
        await BillingService()._sync_subscription(db, _sub_obj("active"), deleted=False)
        assert credit.sessions == [db], (
            "the credit service was called without the database session; it needs it to "
            "find the llm_credit row and to commit"
        )

    async def test_revoke_receives_the_session_too(self, db, credit) -> None:
        await BillingService()._sync_subscription(db, _sub_obj("canceled"), deleted=True)
        assert credit.sessions == [db]


class TestCancellationTakesTheKeyBack:
    async def test_deleting_a_subscription_revokes_the_key(self, db, credit) -> None:
        await BillingService()._sync_subscription(db, _sub_obj("canceled"), deleted=True)
        assert credit.revoked == ["user-1"], "the cancelled account's key is still spending"

    async def test_it_still_records_the_cancellation(self, db, credit) -> None:
        await BillingService()._sync_subscription(db, _sub_obj("canceled"), deleted=True)
        sub = await BillingService()._find_by_customer(db, "cus_1")
        assert sub is not None
        assert sub.status == "canceled"
        assert sub.plan_id == "free"


class TestAFailureIsRetriedRatherThanSwallowed:
    async def test_provisioning_failure_propagates(self, db, monkeypatch) -> None:
        """`handle_event` rolls its claim back on an exception, so Stripe redelivers.
        Swallowing would leave a paying customer with no key and no second attempt."""
        c = _Credit(fail=True)
        monkeypatch.setattr(
            "app.services.openrouter_credit_service.OpenRouterCreditService", lambda: c
        )
        with pytest.raises(Exception, match="OpenRouter is down"):
            await BillingService()._sync_subscription(db, _sub_obj("active"), deleted=False)

    async def test_revocation_failure_propagates(self, db, monkeypatch) -> None:
        c = _Credit(fail=True)
        monkeypatch.setattr(
            "app.services.openrouter_credit_service.OpenRouterCreditService", lambda: c
        )
        with pytest.raises(Exception, match="OpenRouter is down"):
            await BillingService()._sync_subscription(db, _sub_obj("canceled"), deleted=True)
