"""Setup is open; unattended work is not.

The decision of 2026-09-07 (SCN-146/147/148, and the record in `CLAUDE.md` beside
`_no_plan`) is neither of the two options that were on the table. An unpaid account is
**not** blocked and **not** fully served: creating a project, connecting sources,
describing them, indexing by hand and asking questions all stay open, and **scheduled**
work needs a subscription. Blocking makes the product unevaluable; running unattended
nightly LLM work for accounts that pay nothing is the cost the tier exists to meter.

Two halves that must ship together, and this file guards the seam between them:

* the gate — a fourth entitlement question, asked through the **registry** so a
  `billing_enabled=False` self-hosted build keeps its automation;
* the grant — a comped plan for named accounts, without Stripe, so the day the gate
  lands the operator's own account does not stop syncing.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import app.models.billing  # noqa: F401
from app.entitlements import (
    UnlimitedEntitlements,
    may_run_scheduled_work,
    reset_entitlements,
    set_entitlements,
)
from app.models.base import Base


@pytest.fixture(autouse=True)
def _clean_registry():
    reset_entitlements()
    yield
    reset_entitlements()


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()


class TestTheGateIsAskedThroughTheRegistry:
    async def test_the_permissive_default_allows_scheduled_work(self) -> None:
        """The open-source build has no billing concept, so it must not withhold
        automation. This is the branch that keeps a clone working."""
        assert await UnlimitedEntitlements().may_run_scheduled_work(MagicMock(), "u1") is True

    async def test_the_module_helper_uses_whatever_provider_is_installed(self) -> None:
        class Deny:
            async def may_run_scheduled_work(self, db, user_id):  # noqa: ANN001, ANN201
                return False

        set_entitlements(Deny())
        assert await may_run_scheduled_work(MagicMock(), "u1") is False

    async def test_a_provider_that_cannot_answer_degrades_to_allowed(self) -> None:
        """`Entitlements` is a structural Protocol whose whole point is that a private
        cloud package satisfies it without importing this repository. A package built
        against the three-method surface therefore has no fourth method, and the choice
        of default is the choice between an outage and an unmetered night.

        Allowed, for the reason `reset_entitlements` already states: a cloud image that
        has lost part of its billing configuration should degrade to working rather than
        to broken. An unmetered night is recoverable; a paying customer whose nightly
        sync silently stopped is the failure nobody notices for a week.
        """

        class OldProvider:
            async def enforce_project_quota(self, db, user_id):  # noqa: ANN001, ANN201
                return None

            async def enforce_connection_quota(self, db, user_id):  # noqa: ANN001, ANN201
                return None

            async def effective_token_limits(self, db, user_id):  # noqa: ANN001, ANN201
                return (0, 0)

        set_entitlements(OldProvider())
        assert await may_run_scheduled_work(MagicMock(), "u1") is True


class TestTheCommercialProviderAnswersFromThePlan:
    """`EntitlementService` is only ever registered when `billing_enabled` is true
    (`main.py`), so `_no_plan()` inside it means exactly one thing: billing is on and
    this account has not paid."""

    @pytest.fixture(autouse=True)
    def _billing_on(self, monkeypatch):
        """This provider answers `_no_plan()` to everything while billing is off, so its
        plan behaviour is only observable with it on — which is also the only state it is
        ever registered in."""
        from app.config import settings

        monkeypatch.setattr(settings, "billing_enabled", True)

    async def test_billing_off_allows_scheduled_work_even_here(
        self, db_session, monkeypatch
    ) -> None:
        """The defensive branch, reachable through the two direct instantiations that
        bypass the registry (`billing.py`, `usage_service.py`). It must not withhold
        automation, or a self-hosted build that reaches this class by either of those
        routes loses its nightly sync."""
        from app.config import settings
        from app.services.entitlement_service import EntitlementService

        monkeypatch.setattr(settings, "billing_enabled", False)
        assert await EntitlementService().may_run_scheduled_work(db_session, "anyone") is True

    async def test_no_subscription_may_not_run_scheduled_work(self, db_session) -> None:
        from app.services.entitlement_service import EntitlementService

        assert await EntitlementService().may_run_scheduled_work(db_session, "nobody") is False

    async def test_a_real_plan_may_run_scheduled_work(self, db_session) -> None:
        from app.models.billing import Plan, Subscription
        from app.models.user import User
        from app.services.entitlement_service import EntitlementService

        db_session.add(Plan(id="ent-test", name="Ent", max_projects=0, max_connections=0))
        db_session.add(User(id="u-paid", email="paid@test.com"))
        await db_session.flush()
        db_session.add(Subscription(user_id="u-paid", plan_id="ent-test", status="active"))
        await db_session.flush()

        assert await EntitlementService().may_run_scheduled_work(db_session, "u-paid") is True

    async def test_a_cancelled_subscription_may_not(self, db_session) -> None:
        from app.models.billing import Plan, Subscription
        from app.models.user import User
        from app.services.entitlement_service import EntitlementService

        db_session.add(Plan(id="ent-c", name="Ent", max_projects=0, max_connections=0))
        db_session.add(User(id="u-cancelled", email="cancelled@test.com"))
        await db_session.flush()
        db_session.add(Subscription(user_id="u-cancelled", plan_id="ent-c", status="canceled"))
        await db_session.flush()

        assert await EntitlementService().may_run_scheduled_work(db_session, "u-cancelled") is False

    async def test_a_grace_period_still_runs(self, db_session) -> None:
        """`past_due` is a payment problem, not a decision to stop paying. Cutting the
        nightly sync on the first failed charge punishes an expired card."""
        from app.models.billing import Plan, Subscription
        from app.models.user import User
        from app.services.entitlement_service import EntitlementService

        db_session.add(Plan(id="ent-g", name="Ent", max_projects=0, max_connections=0))
        db_session.add(User(id="u-grace", email="grace@test.com"))
        await db_session.flush()
        db_session.add(Subscription(user_id="u-grace", plan_id="ent-g", status="past_due"))
        await db_session.flush()

        assert await EntitlementService().may_run_scheduled_work(db_session, "u-grace") is True


class TestTheGrant:
    """A comped plan is operator configuration reconciled at boot, not a hand-edited row.
    A row written by hand is lost to the next restore and recorded nowhere."""

    async def test_it_grants_the_named_plan(self, db_session) -> None:
        from sqlalchemy import select

        from app.models.billing import Plan, Subscription
        from app.models.user import User
        from app.ops.plan_grant_reconcile import reconcile_plan_grants

        db_session.add(Plan(id="enterprise", name="Enterprise", max_projects=0))
        db_session.add(User(id="u-g", email="Owner@Test.com"))
        await db_session.flush()

        result = await reconcile_plan_grants(
            grants=["owner@test.com=enterprise"], session=db_session
        )
        assert result.granted == 1

        sub = (
            await db_session.execute(select(Subscription).where(Subscription.user_id == "u-g"))
        ).scalar_one()
        assert sub.plan_id == "enterprise"
        assert sub.status == "active"

    async def test_a_granted_row_carries_no_stripe_id(self, db_session) -> None:
        """This is what keeps `BillingService.reconcile` from cancelling it: that sweep
        filters on `stripe_subscription_id IS NOT NULL` and names manual grants as the
        reason. A granted row with a Stripe id would be cancelled on the next sweep."""
        from sqlalchemy import select

        from app.models.billing import Plan, Subscription
        from app.models.user import User
        from app.ops.plan_grant_reconcile import reconcile_plan_grants

        db_session.add(Plan(id="enterprise", name="Enterprise", max_projects=0))
        db_session.add(User(id="u-ns", email="ns@test.com"))
        await db_session.flush()
        await reconcile_plan_grants(grants=["ns@test.com=enterprise"], session=db_session)

        sub = (
            await db_session.execute(select(Subscription).where(Subscription.user_id == "u-ns"))
        ).scalar_one()
        assert sub.stripe_subscription_id is None
        assert sub.stripe_customer_id is None

    async def test_it_is_idempotent(self, db_session) -> None:
        from sqlalchemy import func, select

        from app.models.billing import Plan, Subscription
        from app.models.user import User
        from app.ops.plan_grant_reconcile import reconcile_plan_grants

        db_session.add(Plan(id="enterprise", name="Enterprise", max_projects=0))
        db_session.add(User(id="u-i", email="i@test.com"))
        await db_session.flush()

        await reconcile_plan_grants(grants=["i@test.com=enterprise"], session=db_session)
        second = await reconcile_plan_grants(grants=["i@test.com=enterprise"], session=db_session)

        rows = (
            await db_session.execute(
                select(func.count(Subscription.id)).where(Subscription.user_id == "u-i")
            )
        ).scalar_one()
        assert rows == 1
        assert second.granted == 0 and second.unchanged == 1

    async def test_an_unknown_plan_is_refused_and_nothing_is_written(self, db_session) -> None:
        """Resolving a grant to something unintended is worse than not granting it."""
        from sqlalchemy import select

        from app.models.billing import Subscription
        from app.models.user import User
        from app.ops.plan_grant_reconcile import reconcile_plan_grants

        db_session.add(User(id="u-bad", email="bad@test.com"))
        await db_session.flush()

        result = await reconcile_plan_grants(
            grants=["bad@test.com=no-such-plan"], session=db_session
        )
        assert result.refused == 1 and result.granted == 0
        assert (
            await db_session.execute(select(Subscription).where(Subscription.user_id == "u-bad"))
        ).scalar_one_or_none() is None

    async def test_an_unknown_email_is_skipped_without_raising(self, db_session) -> None:
        from app.models.billing import Plan
        from app.ops.plan_grant_reconcile import reconcile_plan_grants

        db_session.add(Plan(id="enterprise", name="Enterprise", max_projects=0))
        await db_session.flush()

        result = await reconcile_plan_grants(
            grants=["ghost@test.com=enterprise"], session=db_session
        )
        assert result.missing == 1 and result.granted == 0

    async def test_a_malformed_entry_is_refused_not_guessed(self, db_session) -> None:
        from app.ops.plan_grant_reconcile import reconcile_plan_grants

        result = await reconcile_plan_grants(
            grants=["no-equals-sign", "=enterprise", "a@b.com="], session=db_session
        )
        assert result.refused == 3 and result.granted == 0

    async def test_it_never_raises(self) -> None:
        """Boot must not fail because a grant could not be written."""
        from app.ops.plan_grant_reconcile import reconcile_plan_grants

        broken = MagicMock()
        broken.execute.side_effect = RuntimeError("database is on fire")
        result = await reconcile_plan_grants(grants=["a@b.com=enterprise"], session=broken)
        assert result.status == "error"

    async def test_no_grants_configured_is_a_no_op(self, db_session) -> None:
        from app.ops.plan_grant_reconcile import reconcile_plan_grants

        result = await reconcile_plan_grants(grants=[], session=db_session)
        assert result.status == "skipped_empty"


class TestTheTwoHalvesShipTogether:
    """The sequencing is not advisory. On the day the gate lands, every account without a
    subscription stops syncing — this deployment's owner included, whose account has no
    subscription because no Stripe key was ever configured. A gate without a grant is a
    self-inflicted outage on the one real project."""

    def test_the_gate_and_the_grant_both_exist(self) -> None:
        import app.ops.plan_grant_reconcile as grant
        from app.entitlements import may_run_scheduled_work as gate

        assert callable(gate) and hasattr(grant, "reconcile_plan_grants")

    def test_the_grant_is_reconciled_at_boot(self) -> None:
        import inspect

        import app.main as main

        src = inspect.getsource(main)
        assert "reconcile_plan_grants" in src, (
            "the grant must run in the FastAPI lifespan beside the other reconciles, or "
            "it is documentation rather than a mechanism"
        )

    @staticmethod
    def _code_of(fn) -> str:  # noqa: ANN001
        """Source with comment lines removed.

        The naive version of this guard grepped raw source and tripped on the *comment*
        that names the anti-pattern next to the correct call — so a rule could not be
        explained where it applies without breaking the test that enforces it. A guard
        that punishes documenting itself gets the documentation deleted.
        """
        import inspect

        return "\n".join(
            line for line in inspect.getsource(fn).splitlines() if not line.lstrip().startswith("#")
        )

    def test_every_scheduled_wave_asks_the_gate(self) -> None:
        """All three unattended paths, and each by name so a fourth cannot be added
        silently: the nightly knowledge sync, the analytics collection wave, and the
        scheduled-query loop."""
        import app.main as main

        for fn in (
            main._dispatch_daily_knowledge_sync_wave,
            main._dispatch_analytics_collect_wave,
            main._scheduler_loop,
        ):
            assert "may_run_scheduled_work" in self._code_of(fn), fn.__name__

    def test_no_wave_asks_the_commercial_service_directly(self) -> None:
        """Asking `EntitlementService()` instead of the registry would withhold
        automation from every `billing_enabled=False` self-hosted build, because the
        registry is what keeps the commercial provider out of that build."""
        import app.main as main

        for fn in (
            main._dispatch_daily_knowledge_sync_wave,
            main._dispatch_analytics_collect_wave,
            main._scheduler_loop,
        ):
            assert "EntitlementService(" not in self._code_of(fn), fn.__name__
