"""Give named accounts a plan without Stripe, at boot.

**Why this exists at all.** The scheduled-work gate of `SCN-146` withholds unattended
work from any account with no plan behind it. On a deployment where `BILLING_ENABLED` is
true and no Stripe key was ever configured, *every* account is in that state — including
the operator's own, which cannot buy a plan because there is nothing to buy it from. The
gate without this would be a self-inflicted outage on the one real project, which is why
the two ship in the same change.

**Why not a row written by hand.** A `psql` INSERT is lost to the next restore, recorded
in no diff, and invisible to anybody reading the configuration. A grant is a statement
about a deployment, so it lives where the deployment's other statements live and is
reapplied every boot.

Same shape as `plan_catalogue_reconcile`, `embedding_reconcile` and
`encryption_reconcile`: idempotent, advisory-locked so concurrent dynos do not both
write, best-effort so a failure never blocks boot.

**A granted row carries no Stripe id, and that is load-bearing.**
`BillingService.reconcile` sweeps subscriptions against Stripe and cancels the ones
Stripe has never heard of — but it filters on `stripe_subscription_id IS NOT NULL` first,
and its docstring names comped accounts and manual grants as the reason. Writing a
placeholder id here would hand the grant to that sweep to cancel.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.base import async_session_factory
from app.models.billing import Plan, Subscription
from app.models.user import User

logger = logging.getLogger(__name__)

# Stable, arbitrary 64-bit key for pg_try_advisory_xact_lock — never change it.
_ADVISORY_LOCK_KEY = 0x504C414E47524E54

#: The status a granted subscription carries. `active` rather than a new value on purpose:
#: `ACTIVE_STATUSES` in `entitlement_service` is what decides whether a plan resolves, and
#: inventing `granted` would mean teaching that set — and every other reader of `status` —
#: about a fourth kind of alive.
_GRANTED_STATUS = "active"


@dataclass
class GrantResult:
    status: str
    granted: int = 0
    unchanged: int = 0
    refused: int = 0
    missing: int = 0


def _parse(entry: str) -> tuple[str, str] | None:
    """``email=plan_id`` → the pair, or ``None`` when the entry is not that.

    Refused rather than guessed. A half-parsed grant would resolve an account to a plan
    nobody named, and the failure mode of guessing here is handing out entitlements.
    """
    email, sep, plan_id = entry.partition("=")
    if not sep:
        return None
    email = email.strip().lower()
    plan_id = plan_id.strip()
    if not email or not plan_id:
        return None
    return email, plan_id


async def reconcile_plan_grants(
    grants: list[str] | None = None,
    session_factory: async_sessionmaker | None = None,
    session: AsyncSession | None = None,
) -> GrantResult:
    """Ensure each configured ``email=plan_id`` grant has an active subscription row.

    Never raises. ``session`` is for tests and for a caller that already has one; in the
    lifespan the factory is used so the advisory lock scopes to this transaction.
    """
    from app.config import settings

    entries = grants if grants is not None else list(settings.plan_grants)
    entries = [e for e in entries if e and e.strip()]
    if not entries:
        return GrantResult("skipped_empty")

    result = GrantResult("ok")
    try:
        if session is not None:
            await _apply(session, entries, result)
            await session.flush()
            return result

        factory = session_factory or async_session_factory
        async with factory() as db:
            if db.get_bind().dialect.name == "postgresql":
                locked = await db.scalar(
                    text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": _ADVISORY_LOCK_KEY}
                )
                if not locked:
                    return GrantResult("skipped_locked")
            await _apply(db, entries, result)
            await db.commit()
    except Exception:
        # Boot must not fail because a comped plan could not be written. The account
        # degrades to no-plan, which withholds automation rather than granting it — the
        # safe direction for a grant that did not happen.
        logger.warning("plan grants: reconcile failed; no grant applied", exc_info=True)
        return GrantResult("error")

    logger.info(
        "plan grants: %d granted, %d unchanged, %d refused, %d account(s) not found",
        result.granted,
        result.unchanged,
        result.refused,
        result.missing,
    )
    return result


async def _apply(db: AsyncSession, entries: list[str], result: GrantResult) -> None:
    for entry in entries:
        parsed = _parse(entry)
        if parsed is None:
            result.refused += 1
            logger.warning(
                "plan grants: ignoring malformed entry %r (expected email=plan_id)", entry
            )
            continue
        email, plan_id = parsed

        plan = (await db.execute(select(Plan).where(Plan.id == plan_id))).scalar_one_or_none()
        if plan is None:
            # Refused, not defaulted. A grant that resolves to something unintended is
            # worse than one that does not resolve: the account gets entitlements nobody
            # chose, and the log line is the only place it would ever have been visible.
            result.refused += 1
            logger.error(
                "plan grants: %r names plan %r, which is not in the catalogue; not granted",
                email,
                plan_id,
            )
            continue

        user = (
            await db.execute(select(User).where(func.lower(User.email) == email))
        ).scalar_one_or_none()
        if user is None:
            result.missing += 1
            logger.warning("plan grants: no account for %r; nothing granted", email)
            continue

        sub = (
            await db.execute(select(Subscription).where(Subscription.user_id == user.id))
        ).scalar_one_or_none()

        if sub is None:
            db.add(
                Subscription(
                    user_id=user.id,
                    plan_id=plan_id,
                    status=_GRANTED_STATUS,
                    # Left NULL deliberately — see the module docstring.
                    stripe_customer_id=None,
                    stripe_subscription_id=None,
                )
            )
            result.granted += 1
            logger.info("plan grants: granted %r to %r", plan_id, email)
            continue

        if sub.stripe_subscription_id is not None:
            # A real, paid subscription outranks a grant. Overwriting it would detach the
            # account from the thing Stripe is still billing, and the next reconcile sweep
            # would fight this one every boot.
            result.unchanged += 1
            logger.info(
                "plan grants: %r already has a Stripe subscription; grant not applied", email
            )
            continue

        if sub.plan_id == plan_id and sub.status == _GRANTED_STATUS:
            result.unchanged += 1
            continue

        sub.plan_id = plan_id
        sub.status = _GRANTED_STATUS
        result.granted += 1
        logger.info("plan grants: updated %r to %r", email, plan_id)
