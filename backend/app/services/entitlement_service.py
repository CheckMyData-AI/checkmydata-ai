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
from app.models.billing import Plan, Subscription
from app.models.connection import Connection
from app.models.project import Project

logger = logging.getLogger(__name__)


class QuotaExceededError(Exception):
    """A plan quota (connections / projects) was reached (T-BILL-2 paywall)."""

    def __init__(self, message: str, *, resource: str, limit: int, current: int):
        super().__init__(message)
        self.resource = resource
        self.limit = limit
        self.current = current

    def as_payload(self) -> dict:
        return {
            "error": "plan_limit_reached",
            "resource": self.resource,
            "limit": self.limit,
            "current": self.current,
            "message": str(self),
            "upgrade_url": "/pricing",
        }


# Subscription statuses that grant paid-plan entitlements.
ACTIVE_STATUSES = {"active", "trialing"}
# past_due keeps access for the grace period Stripe manages; canceled/unpaid
# fall back to free.
GRACE_STATUSES = {"past_due"}

FREE_PLAN_ID = "free"


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
            return self._fallback()

        sub = await self.get_subscription(db, user_id)
        plan_id = FREE_PLAN_ID
        status = "free"
        cancel_at_period_end = False
        period_end: str | None = None
        if sub is not None:
            status = sub.status
            cancel_at_period_end = bool(sub.cancel_at_period_end)
            if sub.current_period_end is not None:
                period_end = sub.current_period_end.isoformat()
            if sub.status in ACTIVE_STATUSES or sub.status in GRACE_STATUSES:
                plan_id = sub.plan_id

        plan = await self.get_plan(db, plan_id)
        if plan is None:
            # Catalog missing (e.g. migration not run) — never lock users out.
            logger.warning("billing: plan %r not found, falling back to config limits", plan_id)
            return self._fallback(status=status)

        return Entitlements(
            plan_id=plan.id,
            plan_name=plan.name,
            status=status,
            daily_token_limit=plan.daily_token_limit,
            monthly_token_limit=plan.monthly_token_limit,
            max_connections=plan.max_connections,
            max_projects=plan.max_projects,
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

    async def enforce_connection_quota(self, db: AsyncSession, user_id: str) -> None:
        """Block creating a connection past the plan's ``max_connections``.

        Counted across all projects the user owns. No-op when billing is
        disabled or the plan is unlimited.
        """
        ent = await self.get_entitlements(db, user_id)
        if not ent.max_connections:
            return
        from sqlalchemy import func as sa_func

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
            return
        from sqlalchemy import func as sa_func

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
    def _fallback(status: str = "free") -> Entitlements:
        return Entitlements(
            plan_id=FREE_PLAN_ID,
            plan_name="Free",
            status=status,
            daily_token_limit=0,
            monthly_token_limit=0,
            max_connections=0,
            max_projects=0,
            seats=1,
        )


def _strictest(a: int, b: int) -> int:
    """Lowest non-zero of two limits; 0 = unlimited."""
    values = [v for v in (a, b) if v and v > 0]
    return min(values) if values else 0
