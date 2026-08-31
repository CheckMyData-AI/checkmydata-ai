"""Stripe billing integration (T-BILL-4/5): Checkout, Portal, webhook sync.

Design:
- The webhook is the single writer of subscription state. Checkout success
  redirect never grants entitlements directly.
- ``stripe_events`` rows dedupe webhook deliveries (unique event id).
- All Stripe SDK calls are synchronous; they are wrapped in
  ``asyncio.to_thread`` so the event loop is never blocked.
"""

import asyncio
import json
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.billing import Plan, StripeEvent, Subscription
from app.models.user import User

logger = logging.getLogger(__name__)

#: Pinned deliberately. Unpinned, the account's default governs and Stripe moves response
#: shapes on its schedule rather than ours — which is not hypothetical here: the
#: subscription period moved onto the subscription ITEM in `2025-07-30.basil`, and code
#: reading the old top-level fields gets nothing and stores NULL without an error.
#:
#: `2025-09-30.clover` or later also makes `flexible` the default `billing_mode`; we set
#: that explicitly below rather than inherit it, because the choice cannot be reversed.
#: Upgrading this is a task with its own test run, never a deploy-day surprise.
STRIPE_API_VERSION = "2025-09-30.clover"

# Events we act on; everything else is recorded and ignored.
_HANDLED_EVENTS = {
    "checkout.session.completed",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "invoice.payment_failed",
    "invoice.paid",
}


class BillingError(Exception):
    """Raised for user-facing billing failures (bad plan, no Stripe config)."""


def _stripe():
    """Import stripe lazily so the app runs without the SDK when billing is off."""
    import stripe as _s

    if not settings.stripe_secret_key:
        raise BillingError("Stripe is not configured (STRIPE_SECRET_KEY missing)")
    _s.api_key = settings.stripe_secret_key
    _s.api_version = STRIPE_API_VERSION
    return _s


def _price_id_for(plan: Plan) -> str:
    """Plan's Stripe price: DB column first, env override second."""
    if plan.stripe_price_id:
        return plan.stripe_price_id
    env_price = getattr(settings, f"stripe_price_{plan.id}", "")
    if env_price:
        return env_price
    raise BillingError(f"Plan {plan.id!r} has no Stripe price configured")


def _period_from(obj: dict) -> tuple[int | None, int | None]:
    """(start, end) of the current period, from the subscription ITEM.

    They lived on the subscription until `2025-07-30.basil` and moved to the item, so a
    subscription can now carry items on different cadences and there is no single period
    at the top level to read. We take the first item's, which is right for our
    one-item-per-subscription model and would need revisiting the day it stops being one.

    Falls back to the old top-level fields so a subscription created under an older
    version still syncs, and answers `(None, None)` rather than raising when a payload has
    no items at all — losing a period is survivable, losing the webhook is not.
    """
    items = (obj.get("items") or {}).get("data") or []
    if items:
        first = items[0] or {}
        start, end = first.get("current_period_start"), first.get("current_period_end")
        if start or end:
            return start, end
    return obj.get("current_period_start"), obj.get("current_period_end")


def _ts_to_dt(ts: int | None) -> datetime | None:
    return datetime.fromtimestamp(ts, tz=UTC) if ts else None


class BillingService:
    # ------------------------------------------------------------------
    # Catalog
    # ------------------------------------------------------------------

    async def list_plans(self, db: AsyncSession) -> list[Plan]:
        stmt = select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.sort_order)
        return list((await db.execute(stmt)).scalars().all())

    # ------------------------------------------------------------------
    # Customer / Checkout / Portal
    # ------------------------------------------------------------------

    async def _get_or_create_subscription_row(self, db: AsyncSession, user_id: str) -> Subscription:
        sub = (
            await db.execute(select(Subscription).where(Subscription.user_id == user_id))
        ).scalar_one_or_none()
        if sub is None:
            sub = Subscription(user_id=user_id, plan_id="free", status="free")
            db.add(sub)
            await db.flush()
        return sub

    async def _ensure_customer(self, db: AsyncSession, user: User) -> str:
        sub = await self._get_or_create_subscription_row(db, user.id)
        if sub.stripe_customer_id:
            return sub.stripe_customer_id

        stripe = _stripe()
        customer = await asyncio.to_thread(
            stripe.Customer.create,
            email=user.email,
            name=user.display_name or user.email,
            metadata={"user_id": user.id},
        )
        sub.stripe_customer_id = customer["id"]
        await db.commit()
        return customer["id"]

    async def create_checkout_session(self, db: AsyncSession, user: User, plan_id: str) -> str:
        """Create a Stripe Checkout session for ``plan_id`` and return its URL."""
        plan = (
            await db.execute(select(Plan).where(Plan.id == plan_id, Plan.is_active.is_(True)))
        ).scalar_one_or_none()
        if plan is None or plan.price_usd_month <= 0:
            raise BillingError(f"Unknown or non-purchasable plan: {plan_id!r}")

        # Guard the duplicate BEFORE the money moves. A second active subscription for one
        # account is a refund conversation, and by the time the webhook could notice it
        # the card has already been charged.
        existing = await self._active_subscription_id(db, user.id)
        if existing:
            raise BillingError(
                f"This account already has an active subscription ({existing}). "
                "Change the plan from the billing portal instead of buying a second one."
            )

        price_id = _price_id_for(plan)
        customer_id = await self._ensure_customer(db, user)
        stripe = _stripe()

        # Written TWICE, deliberately. Session metadata does not propagate to the
        # subscription: a year from now the session is gone and every renewal invoice and
        # `customer.subscription.*` event carries only what went into `subscription_data`.
        # `_find_by_customer` is the fallback, not the design.
        metadata = {"user_id": user.id, "plan_id": plan.id}
        subscription_data: dict = {
            "metadata": metadata,
            # Irreversible, and chosen rather than inherited from whatever API version the
            # account happens to sit on. Flexible is what Stripe recommends for new
            # subscriptions and what the pinned version defaults to; saying it out loud
            # means an account-level change cannot silently move it.
            "billing_mode": {"type": "flexible"},
        }
        if plan.trial_days:
            subscription_data["trial_period_days"] = plan.trial_days

        base = settings.app_url.rstrip("/")
        session = await asyncio.to_thread(
            stripe.checkout.Session.create,
            customer=customer_id,
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            subscription_data=subscription_data,
            # Stripe substitutes the id. Without it the success page has nothing to verify
            # against, and the window between the redirect and the webhook cannot be
            # closed at all.
            success_url=f"{base}{settings.billing_success_path}"
            f"{'&' if '?' in settings.billing_success_path else '?'}"
            "session_id={CHECKOUT_SESSION_ID}",
            cancel_url=f"{base}{settings.billing_cancel_path}",
            client_reference_id=user.id,
            metadata=metadata,
            allow_promotion_codes=True,
        )
        return session["url"]

    async def _active_subscription_id(self, db: AsyncSession, user_id: str) -> str | None:
        """The account's live Stripe subscription id, or None.

        `trialing` counts as live: a trial is a subscription that will bill, and selling a
        second one during it produces two.
        """
        sub = (
            await db.execute(select(Subscription).where(Subscription.user_id == user_id))
        ).scalar_one_or_none()
        if sub is None or not sub.stripe_subscription_id:
            return None
        return (
            sub.stripe_subscription_id if sub.status in ("active", "trialing", "past_due") else None
        )

    async def create_portal_session(self, db: AsyncSession, user: User) -> str:
        """Create a Stripe Customer Portal session and return its URL."""
        sub = (
            await db.execute(select(Subscription).where(Subscription.user_id == user.id))
        ).scalar_one_or_none()
        if sub is None or not sub.stripe_customer_id:
            raise BillingError("No billing account yet — subscribe to a plan first")

        stripe = _stripe()
        base = settings.app_url.rstrip("/")
        session = await asyncio.to_thread(
            stripe.billing_portal.Session.create,
            customer=sub.stripe_customer_id,
            return_url=f"{base}/dashboard",
        )
        return session["url"]

    # ------------------------------------------------------------------
    # Webhook
    # ------------------------------------------------------------------

    def verify_webhook(self, payload: bytes, signature: str) -> dict:
        """Verify the Stripe signature and return the parsed event."""
        import stripe as _s

        if not settings.stripe_webhook_secret:
            raise BillingError("STRIPE_WEBHOOK_SECRET is not configured")
        return _s.Webhook.construct_event(payload, signature, settings.stripe_webhook_secret)

    async def handle_event(self, db: AsyncSession, event: dict) -> bool:
        """Apply a verified Stripe event. Returns False if it was a duplicate."""
        event_id = event.get("id", "")
        event_type = event.get("type", "")

        # Idempotency: insert the ledger row first; a unique violation means
        # this delivery was already processed.
        ledger = StripeEvent(
            stripe_event_id=event_id,
            event_type=event_type,
            payload=json.dumps(event.get("data", {}).get("object", {}), default=str)[:65536],
        )
        db.add(ledger)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            logger.info("billing: duplicate stripe event %s ignored", event_id)
            return False

        if event_type in _HANDLED_EVENTS:
            obj = event.get("data", {}).get("object", {})
            try:
                await self._apply_event(db, event_type, obj)
            except Exception:
                await db.rollback()
                raise
        await db.commit()
        return True

    async def reconcile(self, db: AsyncSession, *, limit: int = 100) -> dict:
        """Re-read Stripe and repair rows the webhooks did not.

        Webhooks are best-effort and outages are not hypothetical: a delivery that never
        arrives leaves a paying customer without access, and nothing in the logs says so.
        This is the only path that finds that.

        The guard that matters is the last one. Rows with no `stripe_subscription_id` were
        never Stripe's — comped accounts, manual grants, the free tier — and cancelling
        them because Stripe has never heard of them would be a self-inflicted outage. They
        are skipped, not reconciled.
        """
        stripe = _stripe()
        rows = list(
            (
                await db.execute(
                    select(Subscription)
                    .where(Subscription.stripe_subscription_id.is_not(None))
                    .limit(limit)
                )
            ).scalars()
        )
        checked = repaired = orphaned = 0
        for sub in rows:
            checked += 1
            try:
                remote = await asyncio.to_thread(
                    stripe.Subscription.retrieve, sub.stripe_subscription_id
                )
            except Exception as exc:  # noqa: BLE001 - one bad row must not stop the sweep
                if "resource_missing" in str(exc):
                    # Stripe has no such subscription. It carried a Stripe id, so it was
                    # ours to cancel — unlike the rows filtered out above.
                    sub.status = "canceled"
                    orphaned += 1
                    logger.warning(
                        "billing: reconcile found no Stripe subscription %s; marked canceled",
                        sub.stripe_subscription_id,
                    )
                else:
                    logger.warning(
                        "billing: reconcile could not read %s",
                        sub.stripe_subscription_id,
                        exc_info=True,
                    )
                continue

            period_start, period_end = _period_from(dict(remote))
            changed = False
            for attr, value in (
                ("status", remote.get("status")),
                ("cancel_at_period_end", bool(remote.get("cancel_at_period_end"))),
                ("current_period_start", _ts_to_dt(period_start)),
                ("current_period_end", _ts_to_dt(period_end)),
                ("trial_end", _ts_to_dt(remote.get("trial_end"))),
            ):
                if value is not None and getattr(sub, attr) != value:
                    setattr(sub, attr, value)
                    changed = True
            plan_id = await self._resolve_plan_id(db, dict(remote))
            if plan_id and sub.plan_id != plan_id:
                sub.plan_id = plan_id
                changed = True
            if changed:
                repaired += 1
                logger.info("billing: reconcile repaired subscription %s", sub.id)

        await db.commit()
        result = {"checked": checked, "repaired": repaired, "orphaned": orphaned}
        logger.info("billing: reconcile %s", result)
        return result

    async def _apply_event(self, db: AsyncSession, event_type: str, obj: dict) -> None:
        if event_type == "checkout.session.completed":
            # Subscription state arrives via customer.subscription.* events;
            # here we only make sure the customer id is linked to the user.
            user_id = obj.get("client_reference_id") or obj.get("metadata", {}).get("user_id")
            customer_id = obj.get("customer")
            if user_id and customer_id:
                sub = await self._get_or_create_subscription_row(db, user_id)
                sub.stripe_customer_id = customer_id
            return

        if event_type.startswith("customer.subscription."):
            await self._sync_subscription(db, obj, deleted=event_type.endswith(".deleted"))
            return

        if event_type == "invoice.payment_failed":
            await self._set_status_by_customer(db, obj.get("customer"), "past_due")
            return

        if event_type == "invoice.paid":
            await self._set_status_by_customer(db, obj.get("customer"), "active")
            return

    async def _sync_subscription(self, db: AsyncSession, obj: dict, *, deleted: bool) -> None:
        customer_id = obj.get("customer")
        sub = await self._find_by_customer(db, customer_id)
        if sub is None:
            # Try metadata fallback (subscription created straight from Checkout).
            user_id = obj.get("metadata", {}).get("user_id")
            if not user_id:
                logger.warning("billing: subscription event for unknown customer %s", customer_id)
                return
            sub = await self._get_or_create_subscription_row(db, user_id)
            sub.stripe_customer_id = customer_id

        if deleted:
            sub.status = "canceled"
            sub.plan_id = "free"
            sub.stripe_subscription_id = None
            sub.cancel_at_period_end = False
            return

        sub.stripe_subscription_id = obj.get("id")
        sub.status = obj.get("status") or sub.status
        sub.cancel_at_period_end = bool(obj.get("cancel_at_period_end"))
        period_start, period_end = _period_from(obj)
        sub.current_period_start = _ts_to_dt(period_start)
        sub.current_period_end = _ts_to_dt(period_end)
        sub.trial_end = _ts_to_dt(obj.get("trial_end"))

        plan_id = await self._resolve_plan_id(db, obj)
        if plan_id:
            sub.plan_id = plan_id

    async def _resolve_plan_id(self, db: AsyncSession, obj: dict) -> str | None:
        """Map the subscription's Stripe price back to a catalog plan.

        F-BILL-01. This used to read `metadata.plan_id` first and return it immediately.
        Stripe's `metadata` is written once, when our Checkout session creates the
        subscription, and **does not change when the price on that subscription changes** —
        so a customer who upgrades or downgrades through the Customer Portal kept the plan
        they originally bought. Downgrade Team → Pro: they pay Pro and keep Team's limits.
        Upgrade Pro → Team: they pay Team and keep Pro's. Both directions are wrong and
        both are money.

        The price is what Stripe actually charges, so the price is the authority. Metadata
        is a statement of intent that ages badly, and it is consulted for exactly one
        situation: the price is real but no catalog row matches it, which means the catalog
        is behind Stripe. Falling back there beats returning `None`, because the caller
        leaves `sub.plan_id` untouched on `None` and a paying customer would silently keep
        whatever they had — and it warns, because a stale catalog otherwise surfaces only
        as somebody's wrong entitlement.
        """
        items = obj.get("items", {}).get("data", [])
        price_id = items[0].get("price", {}).get("id") if items else None
        meta_plan = obj.get("metadata", {}).get("plan_id")

        if price_id:
            plans = list((await db.execute(select(Plan))).scalars().all())
            for plan in plans:
                db_price = plan.stripe_price_id or getattr(settings, f"stripe_price_{plan.id}", "")
                if db_price == price_id:
                    return plan.id
            if meta_plan:
                logger.warning(
                    "billing: no catalog plan matches stripe price %s; falling back to "
                    "metadata plan_id=%s, which is what was bought and may not be what is "
                    "being charged. Add the price to the plan catalog.",
                    price_id,
                    meta_plan,
                )
                return meta_plan
            logger.warning(
                "billing: no catalog plan matches stripe price %s and the subscription "
                "carries no metadata plan_id — the subscription's plan is left unchanged",
                price_id,
            )
            return None

        # No expanded items on this payload. Metadata is all there is.
        return meta_plan or None

    async def _find_by_customer(
        self, db: AsyncSession, customer_id: str | None
    ) -> Subscription | None:
        if not customer_id:
            return None
        return (
            await db.execute(
                select(Subscription).where(Subscription.stripe_customer_id == customer_id)
            )
        ).scalar_one_or_none()

    async def _set_status_by_customer(
        self, db: AsyncSession, customer_id: str | None, status: str
    ) -> None:
        sub = await self._find_by_customer(db, customer_id)
        if sub is not None and sub.status != "canceled":
            sub.status = status
