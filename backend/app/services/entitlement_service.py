"""Plan-based entitlements (T-BILL-3).

Resolves the effective limits for a user: their subscription's plan when
billing is enabled, otherwise the global config token limits. All gates
(token budget, connection count, project count) read entitlements through
this service so there is a single source of truth.
"""

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.entitlements.base import QuotaExceededError as _QuotaExceededError
from app.models.billing import Plan, Subscription
from app.models.connection import Connection
from app.models.project import Project
from app.models.user import User

logger = logging.getLogger(__name__)


# Re-exported, not redefined. The routes catch the one in `app.entitlements`, and a
# second class with the same name would sail straight past their `except` — which is
# exactly what happened for the length of one commit while the seam was being built.
QuotaExceededError = _QuotaExceededError


# Subscription statuses that grant paid-plan entitlements.
ACTIVE_STATUSES = {"active", "trialing"}
# past_due keeps access for the grace period Stripe manages; canceled/unpaid
# fall back to free.
GRACE_STATUSES = {"past_due"}

#: What an account WITHOUT a subscription resolves to. It is not a catalogue row and
#: never was meant to be one: `free` was retired from sale on 2026-08-31 but stayed the
#: fallback, so every unsubscribed user kept inheriting its 100 000-token daily ceiling.
#: On 2026-09-06 that refused a production code<->DB sync behind a 1 666 411-token index
#: and told the operator to upgrade at /pricing, which cannot take payment.
NO_PLAN_ID = "none"


@dataclass
class Entitlements:
    plan_id: str
    plan_name: str
    status: str
    daily_token_limit: int  # 0 = unlimited
    monthly_token_limit: int
    max_connections: int
    max_projects: int
    seats: int
    #: Bytes of index this plan allows per project; 0 = unlimited. The tier copy has
    #: promised "1 GB index" since 2026-08-31 with no column to hold it.
    max_index_bytes: int = 0
    cancel_at_period_end: bool = False
    current_period_end: str | None = None

    def as_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "plan_name": self.plan_name,
            "status": self.status,
            "daily_token_limit": self.daily_token_limit or None,
            "monthly_token_limit": self.monthly_token_limit or None,
            "max_connections": self.max_connections or None,
            "max_projects": self.max_projects or None,
            "max_index_bytes": self.max_index_bytes or None,
            "seats": self.seats,
            "cancel_at_period_end": self.cancel_at_period_end,
            "current_period_end": self.current_period_end,
        }


class EntitlementService:
    """Resolve effective entitlements for a user."""

    async def get_plan(self, db: AsyncSession, plan_id: str) -> Plan | None:
        return (await db.execute(select(Plan).where(Plan.id == plan_id))).scalar_one_or_none()

    async def get_subscription(self, db: AsyncSession, user_id: str) -> Subscription | None:
        return (
            await db.execute(select(Subscription).where(Subscription.user_id == user_id))
        ).scalar_one_or_none()

    async def get_entitlements(self, db: AsyncSession, user_id: str) -> Entitlements:
        """Effective entitlements for ``user_id``.

        Billing disabled → unlimited plan limits; the global
        ``user_daily_token_limit`` / ``user_monthly_token_limit`` config caps
        are applied by :meth:`effective_token_limits` regardless.
        """
        if not settings.billing_enabled:
            return self._no_plan()

        sub = await self.get_subscription(db, user_id)
        if sub is None:
            # No subscription is NOT the cheapest plan. There is no tier below `base`,
            # so there is nothing to descend to and the catalogue is not consulted.
            return self._no_plan()

        status = sub.status
        cancel_at_period_end = bool(sub.cancel_at_period_end)
        period_end: str | None = None
        if sub.current_period_end is not None:
            period_end = sub.current_period_end.isoformat()

        if status not in ACTIVE_STATUSES and status not in GRACE_STATUSES:
            # canceled / unpaid / incomplete: the subscription no longer entitles
            # anything. It used to fall to `free`; with no free tier it leaves the ladder.
            return self._no_plan(
                status=status,
                cancel_at_period_end=cancel_at_period_end,
                period_end=period_end,
            )

        plan = await self.get_plan(db, sub.plan_id)
        if plan is None:
            # Catalog missing (e.g. migration not run) — never lock users out.
            logger.warning("billing: plan %r not found, falling back to config limits", sub.plan_id)
            return self._no_plan(
                status=status,
                cancel_at_period_end=cancel_at_period_end,
                period_end=period_end,
            )

        return Entitlements(
            plan_id=plan.id,
            plan_name=plan.name,
            status=status,
            daily_token_limit=plan.daily_token_limit,
            monthly_token_limit=plan.monthly_token_limit,
            max_connections=plan.max_connections,
            max_projects=plan.max_projects,
            max_index_bytes=plan.max_index_bytes,
            seats=plan.seats,
            cancel_at_period_end=cancel_at_period_end,
            current_period_end=period_end,
        )

    async def effective_token_limits(self, db: AsyncSession, user_id: str) -> tuple[int, int]:
        """(daily, monthly) limits combining plan and global config caps.

        The stricter (lowest non-zero) of plan limit and global config cap
        wins; 0 means unlimited.
        """
        ent = await self.get_entitlements(db, user_id)
        daily = _strictest(ent.daily_token_limit, settings.user_daily_token_limit)
        monthly = _strictest(ent.monthly_token_limit, settings.user_monthly_token_limit)
        return daily, monthly

    async def may_run_scheduled_work(self, db: AsyncSession, user_id: str) -> bool:
        """Unattended work needs a plan behind it (SCN-146, decided 2026-09-07).

        Derived from the resolved plan id rather than from the subscription status, so
        every way of having no plan answers the same: no row, a `canceled` or `unpaid`
        one, and a row pointing at a plan the catalogue has lost all reach `_no_plan()`
        and all mean the same thing here.

        A grace-period subscription (`past_due`) keeps running deliberately — that is an
        expired card, not a decision to stop paying, and cutting the nightly sync on the
        first failed charge is a punishment the user cannot even see the cause of.

        **Billing off is answered here too, and not by relying on the caller.** This
        service is only *registered* when `billing_enabled` is true (`main.py`), so in
        practice `NO_PLAN_ID` means "billing is on and this account has not paid". But
        two call sites instantiate the class directly and bypass the registry
        (`billing.py`, `usage_service.py`), and `get_entitlements` answers `_no_plan()`
        to everything while billing is off — so deriving the answer from the plan id
        alone would have this method withhold automation from a self-hosted build the
        moment anyone asked it directly. Caught by
        `test_billing_off_allows_scheduled_work_even_here`, which is the reason the check
        is first rather than implied.
        """
        if not settings.billing_enabled:
            return True
        ent = await self.get_entitlements(db, user_id)
        return ent.plan_id != NO_PLAN_ID

    async def _lock_owner(self, db: AsyncSession, user_id: str) -> None:
        """Serialise quota decisions for one owner (F-BILL-02).

        The check was `SELECT COUNT(…)`, compare, and then the *caller* inserted. Two
        concurrent requests both counted `N-1`, both passed, and both inserted — a plan
        allowing one connection ended up with two. Creation is rate-limited to 10/minute,
        which bounds how far it goes and does not stop it.

        A row lock on the owner is the smallest thing that fixes it: quota checks for one
        user serialise, different users never contend, and it needs no new table or
        counter to drift out of step with the rows it counts.

        **Where this works, and where it does not.** `FOR UPDATE` is a Postgres guarantee;
        SQLite's driver accepts the clause and ignores it. Production is Postgres. Dev on
        SQLite is a single-writer database, where two transactions cannot interleave the
        way this race needs — so the guard is real where the race is real and inert where
        it cannot happen. Saying that plainly is better than a test that pretends SQLite
        proved something.

        Best-effort by design: a database that cannot take the lock must not block the
        request, because the quota check that follows is still correct in the common case
        and refusing the write outright would trade a rare over-count for a hard outage.
        """
        try:
            await db.execute(select(User.id).where(User.id == user_id).with_for_update())
        except Exception:
            logger.warning(
                "Could not lock the owner row for %s before a quota check; the check "
                "still runs, but two concurrent creates could both pass it",
                user_id,
                exc_info=True,
            )

    async def enforce_connection_quota(self, db: AsyncSession, user_id: str) -> None:
        """Block creating a connection past the plan's ``max_connections``.

        Counted across all projects the user owns. No-op when billing is
        disabled or the plan is unlimited.
        """
        ent = await self.get_entitlements(db, user_id)
        if not ent.max_connections:
            # Unlimited: return before the lock. Serialising a decision that is already
            # made is contention bought for nothing.
            return
        from sqlalchemy import func as sa_func

        await self._lock_owner(db, user_id)
        stmt = (
            select(sa_func.count(Connection.id))
            .join(Project, Connection.project_id == Project.id)
            .where(Project.owner_id == user_id)
        )
        current = int((await db.execute(stmt)).scalar_one())
        if current >= ent.max_connections:
            raise QuotaExceededError(
                f"Plan '{ent.plan_name}' allows {ent.max_connections} "
                f"connection(s); you have {current}.",
                resource="connections",
                limit=ent.max_connections,
                current=current,
            )

    async def enforce_project_quota(self, db: AsyncSession, user_id: str) -> None:
        """Block creating a project past the plan's ``max_projects``."""
        ent = await self.get_entitlements(db, user_id)
        if not ent.max_projects:
            # Unlimited: return before the lock, for the same reason as connections.
            return
        from sqlalchemy import func as sa_func

        await self._lock_owner(db, user_id)
        stmt = select(sa_func.count(Project.id)).where(Project.owner_id == user_id)
        current = int((await db.execute(stmt)).scalar_one())
        if current >= ent.max_projects:
            raise QuotaExceededError(
                f"Plan '{ent.plan_name}' allows {ent.max_projects} project(s); you have {current}.",
                resource="projects",
                limit=ent.max_projects,
                current=current,
            )

    @staticmethod
    def _no_plan(
        status: str = "none",
        *,
        cancel_at_period_end: bool = False,
        period_end: str | None = None,
    ) -> Entitlements:
        """Entitlements for an account with no plan behind it.

        Every zero here means UNLIMITED, as it does everywhere else in this service:
        the quota checks read `if not ent.max_connections: return`. So this degrades
        OPEN. That is deliberate and it is not a decision about whether an unpaid
        project should be usable — it is the absence of one. The operator's lever
        meanwhile is the global `user_daily_token_limit` config cap, which
        `effective_token_limits` applies on top of whatever this returns.

        Blocking an unpaid project outright is a product decision; when it is made,
        this is the one place it belongs.
        """
        return Entitlements(
            plan_id=NO_PLAN_ID,
            plan_name="No plan",
            status=status,
            daily_token_limit=0,
            monthly_token_limit=0,
            max_connections=0,
            max_projects=0,
            max_index_bytes=0,
            seats=1,
            cancel_at_period_end=cancel_at_period_end,
            current_period_end=period_end,
        )


def _strictest(a: int, b: int) -> int:
    """Lowest non-zero of two limits; 0 = unlimited."""
    values = [v for v in (a, b) if v and v > 0]
    return min(values) if values else 0
