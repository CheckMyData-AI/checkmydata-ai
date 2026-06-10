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
    return _s


def _price_id_for(plan: Plan) -> str:
    """Plan's Stripe price: DB column first, env override second."""
    if plan.stripe_price_id:
        return plan.stripe_price_id
    env_price = getattr(settings, f"stripe_price_{plan.id}", "")
    if env_price:
        return env_price
    raise BillingError(f"Plan {plan.id!r} has no Stripe price configured")


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

        price_id = _price_id_for(plan)
        customer_id = await self._ensure_customer(db, user)
        stripe = _stripe()

        base = settings.app_url.rstrip("/")
        session = await asyncio.to_thread(
            stripe.checkout.Session.create,
            customer=customer_id,
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            subscription_data=({"trial_period_days": plan.trial_days} if plan.trial_days else {}),
            success_url=f"{base}{settings.billing_success_path}",
            cancel_url=f"{base}{settings.billing_cancel_path}",
            client_reference_id=user.id,
            metadata={"user_id": user.id, "plan_id": plan.id},
            allow_promotion_codes=True,
        )
        return session["url"]

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
        sub.current_period_start = _ts_to_dt(obj.get("current_period_start"))
        sub.current_period_end = _ts_to_dt(obj.get("current_period_end"))
        sub.trial_end = _ts_to_dt(obj.get("trial_end"))

        plan_id = await self._resolve_plan_id(db, obj)
        if plan_id:
            sub.plan_id = plan_id

    async def _resolve_plan_id(self, db: AsyncSession, obj: dict) -> str | None:
        """Map the subscription's Stripe price back to a catalog plan."""
        meta_plan = obj.get("metadata", {}).get("plan_id")
        if meta_plan:
            return meta_plan
        items = obj.get("items", {}).get("data", [])
        price_id = items[0].get("price", {}).get("id") if items else None
        if not price_id:
            return None
        plans = list((await db.execute(select(Plan))).scalars().all())
        for plan in plans:
            db_price = plan.stripe_price_id or getattr(settings, f"stripe_price_{plan.id}", "")
            if db_price == price_id:
                return plan.id
        logger.warning("billing: no plan matches stripe price %s", price_id)
        return None

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
