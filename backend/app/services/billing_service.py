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
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.billing import Plan, StripeEvent, Subscription
from app.models.user import User
from app.services.plan_catalogue import PROMISED_CREDIT_USD

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
    # Money leaving. `refund.created` and NOT `charge.refunded`: the charge carries a
    # cumulative `amount_refunded`, so two partial refunds emit two events reading 5.00
    # and then 17.00, and debiting that field twice takes 22.00 for a 17.00 refund.
    # Stripe's own guidance — "during each partial refund, we send a refund.created
    # event", "listen to refund.created instead of charge.refunded to accurately process
    # individual refunds". Handling both would double every reversal.
    "refund.created",
    "charge.dispute.created",
    "charge.dispute.closed",
}


#: Subscription statuses that earn a per-account LLM key. Mirrors
#: ``EntitlementService.ACTIVE_STATUSES`` deliberately rather than importing it: that set
#: answers "does this account get its plan's entitlements", this one answers "does this
#: account get a key that can spend money", and the day those two stop being the same
#: question the import would silently pick the wrong answer.
_LIVE_SUBSCRIPTION_STATUSES = frozenset({"active", "trialing"})

#: How long an opened Checkout session blocks a second one (BILL-05). Stripe's own sessions
#: expire after 24 hours, but a customer who abandons one must not be locked out for a day —
#: the window only has to cover the gap between Checkout and the webhook that fills in
#: `stripe_subscription_id`, which is seconds to minutes.
CHECKOUT_PENDING_WINDOW = timedelta(minutes=15)


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


#: Included LLM credit per tier, in USD, keyed by plan id. ``None`` means *no ceiling on
#: the key* — not zero, which is the opposite instruction at the provider.
#:
#: The dollar figures are **taken from** ``plan_catalogue.PROMISED_CREDIT_USD`` rather than
#: restated: that table is also what each tier's token ceiling is derived from, and two
#: copies of one promise is exactly how a migration and the catalogue came to hold
#: different numbers for the same column (DATA-01).
#:
#: `enterprise` maps to ``None`` (D-SPEND-2b, 2026-09-11). Its description sells "LLM
#: credit at cost with no monthly cap", so there is no allowance for a key ceiling to
#: express; it is provisioned no key, and the invoice is the instrument. Until this table
#: covered four tiers, `team` and `enterprise` fell through a `.get(..., 0.0)` default and
#: provisioned a key with a **$0 lifetime ceiling** (BIZ-02).
_INCLUDED_CREDIT_USD: dict[str, float | None] = {
    **PROMISED_CREDIT_USD,
    "enterprise": None,
}


def _included_credit_for(plan) -> float | None:
    """The tier's monthly credit; ``None`` for a tier sold without a cap.

    An id absent from the table resolves to ``0.0`` — no headroom, the safe direction for a
    tier nobody planned for — and logs, because doing it silently is how two live tiers sat
    at zero.
    """
    plan_id = getattr(plan, "id", "") or ""
    if plan_id in _INCLUDED_CREDIT_USD:
        return _INCLUDED_CREDIT_USD[plan_id]
    logger.warning(
        "billing: plan %r has no included-credit entry; provisioning a $0 key ceiling",
        plan_id,
    )
    return 0.0


def _ts_to_dt(ts: int | None) -> datetime | None:
    return datetime.fromtimestamp(ts, tz=UTC) if ts else None


class BillingService:
    # ------------------------------------------------------------------
    # Catalog
    # ------------------------------------------------------------------

    async def list_plans(self, db: AsyncSession) -> list[Plan]:
        """Plans a visitor can actually buy.

        `is_active` is not sufficient. A plan with no Stripe price is one where the pricing
        page shows a number and the button answers 400 — and this catalogue is public and
        indexable, so the failure is advertised rather than merely reachable.

        Found before shipping the tier migration: it activates `base` and `scale`, whose
        `stripe_price_id` is null until live-mode prices exist, so the deploy alone would
        have published $199 and $599 next to a checkout that cannot complete.

        A free plan is exempt: there is nothing to charge, so there is no price to have.
        """
        stmt = select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.sort_order)
        active = list((await db.execute(stmt)).scalars().all())
        purchasable = []
        for plan in active:
            if plan.price_usd_month <= 0:
                purchasable.append(plan)
                continue
            try:
                _price_id_for(plan)
            except BillingError:
                logger.warning(
                    "billing: plan %r is active but has no Stripe price — hidden from the "
                    "public catalogue rather than offered with a broken checkout",
                    plan.id,
                )
                continue
            purchasable.append(plan)
        return purchasable

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

        # BILL-05: and a checkout already IN FLIGHT is the case the id above cannot see.
        # `stripe_subscription_id` is NULL until `_sync_subscription` runs on a webhook that
        # lands minutes after Checkout is created, so two clicks inside that window both
        # passed the guard and the account ended up with two Stripe subscriptions — which
        # is the refund conversation the guard exists to prevent.
        row = await self._get_or_create_subscription_row(db, user.id)
        pending_since = row.checkout_pending_at
        if pending_since is not None:
            if pending_since.tzinfo is None:
                pending_since = pending_since.replace(tzinfo=UTC)
            if datetime.now(UTC) - pending_since < CHECKOUT_PENDING_WINDOW:
                raise BillingError(
                    "A checkout for this account is already open. Finish or cancel it, or "
                    "wait a few minutes and try again."
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
        # Marked only once Stripe has actually created the session: a failure above leaves
        # no window closed against a customer who never got a checkout page.
        row.checkout_pending_at = datetime.now(UTC)
        await db.commit()
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

    async def verify_checkout(self, db: AsyncSession, user: User, session_id: str) -> dict:
        """Close the window between Stripe's redirect and its webhook.

        Stripe redirects the moment the card clears; the webhook lands when it lands. In
        between, the customer is on the success page and our database knows nothing. This
        performs *exactly the writes the webhook would* and lets the idempotency ledger
        arbitrate — whoever loses reports success.

        **A safety net, never the primary path.** A customer who closes the tab must still
        get what they paid for, which is the webhook's job; this only removes the wait for
        the customer who did not.

        The ownership check is the security-critical part: without it, any authenticated
        user who learns a `cs_…` id claims someone else's purchase.
        """
        if not session_id.startswith("cs_"):
            raise BillingError("not a checkout session id")

        stripe = _stripe()
        # The exception class is imported rather than read off the configured client: it
        # does not depend on the api_key, and reaching through the client for it coupled
        # the handler to whatever `_stripe()` returns — which made it uncatchable the
        # moment a test substituted a double, with `TypeError: catching classes that do
        # not inherit from BaseException`.
        from stripe import StripeError

        try:
            session = await asyncio.to_thread(
                stripe.checkout.Session.retrieve, session_id, expand=["subscription"]
            )
        except StripeError as exc:
            # Narrowed to Stripe's own hierarchy rather than catching everything. The
            # suppression ratchet asked whether recording a broad handler was worth it and
            # the answer was no: a missing session, a bad key and a mode mismatch all
            # arrive as StripeError, while a bug in our own code below should not be
            # swallowed into "session not found".
            #
            # Worth noting for whoever writes the next comment here: the ratchet matches
            # text, so naming the broad form in prose counts as using it. It did, twice.
            raise BillingError("checkout session not found") from exc

        owner = (session.get("client_reference_id") or "") or (session.get("metadata") or {}).get(
            "user_id", ""
        )
        if owner != user.id:
            # Deliberately the same message as a missing session: distinguishing them
            # tells a prober whether a given `cs_…` exists.
            raise BillingError("checkout session not found")

        if session.get("status") != "complete":
            return {"settled": False, "reason": "incomplete"}
        if session.get("payment_status") == "unpaid":
            return {"settled": False, "reason": "unpaid"}

        # The same writes the webhook makes, in the same order.
        row = await self._get_or_create_subscription_row(db, user.id)
        if session.get("customer"):
            row.stripe_customer_id = session["customer"]

        subscription = session.get("subscription")
        if isinstance(subscription, dict):
            try:
                await self._sync_subscription(db, subscription, deleted=False)
            except Exception:
                # `_sync_subscription` now provisions the account's OpenRouter key, which
                # is a call to a third party. On the WEBHOOK that failure must propagate
                # so Stripe redelivers; here it must not, because this page is a safety
                # net over the webhook and the webhook is still owed the same work.
                # Reporting `pending` tells the customer to wait rather than 500-ing the
                # page while the subscription they just bought is still being set up.
                await db.rollback()
                logger.error(
                    "billing: success-page subscription sync failed for session=%s; "
                    "leaving it to the webhook",
                    session_id,
                    exc_info=True,
                )
                return {"settled": False, "reason": "pending"}

        # The payment branch, which this used to omit — it reported `settled: true` for a
        # top-up it never credited. `_credit_top_up` claims the session, so whichever of
        # this and the webhook arrives second finds the claim taken and grants nothing.
        if session.get("mode") == "payment":
            try:
                await self._credit_top_up(db, user.id, session)
            except Exception:
                # The webhook is the primary path and is still owed this grant. Rolling
                # back drops the claim so it can win; reporting `settled: false` tells the
                # customer to wait rather than telling them it is done.
                await db.rollback()
                logger.error(
                    "billing: success-page credit failed for session=%s; leaving it to the webhook",
                    session_id,
                    exc_info=True,
                )
                return {"settled": False, "reason": "pending"}
        await db.commit()

        return {
            "settled": True,
            "mode": session.get("mode"),
            "plan_id": row.plan_id,
            "status": row.status,
        }

    async def create_topup_session(self, db: AsyncSession, user: User) -> str:
        """Start a one-time Checkout for LLM credit. Returns its URL.

        `mode="payment"`, not `subscription`: credit is bought outright and does not renew.
        That word is also what the webhook reads to tell a top-up from a plan purchase.

        The amount is **not** sent. The price carries `custom_unit_amount`, so Stripe's page
        asks the customer for the figure — which is how "we take no margin on API tokens"
        stays literally true instead of being true of a pack size we picked.

        Requires an existing key: crediting a balance that has no key to spend from would
        take the money and grant nothing, and provisioning happens with the subscription.
        """
        price_id = settings.stripe_price_credit_topup
        if not price_id:
            raise BillingError("Credit top-up is not configured (STRIPE_PRICE_CREDIT_TOPUP)")

        from app.models.llm_credit import LlmCredit

        credit = (
            await db.execute(select(LlmCredit).where(LlmCredit.user_id == user.id))
        ).scalar_one_or_none()
        if credit is None or not credit.key_hash:
            raise BillingError(
                "No LLM key to credit yet — start a subscription before buying credit."
            )

        customer_id = await self._ensure_customer(db, user)
        stripe = _stripe()
        base = settings.app_url.rstrip("/")
        metadata = {"user_id": user.id, "kind": "credit_topup"}
        session = await asyncio.to_thread(
            stripe.checkout.Session.create,
            customer=customer_id,
            mode="payment",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=f"{base}{settings.billing_success_path}"
            f"{'&' if '?' in settings.billing_success_path else '?'}"
            "session_id={CHECKOUT_SESSION_ID}",
            cancel_url=f"{base}{settings.billing_cancel_path}",
            client_reference_id=user.id,
            metadata=metadata,
            # `payment_intent_data.metadata` for the same reason `subscription_data` carries
            # it on the recurring path: the session is gone by the time a refund or a
            # dispute arrives, and the PaymentIntent is what those events carry.
            payment_intent_data={"metadata": metadata},
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
                await self._apply_event(db, event_type, obj, int(event.get("created") or 0))
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

    async def _apply_event(
        self, db: AsyncSession, event_type: str, obj: dict, event_created: int = 0
    ) -> None:
        """Apply one verified event. ``event_created`` is Stripe's own timestamp for it.

        BILL-04: it is carried down to `_sync_subscription` because Stripe does not promise
        delivery order and that method's `deleted` branch is a full teardown.
        """
        if event_type == "checkout.session.completed":
            # Subscription state arrives via customer.subscription.* events;
            # here we only make sure the customer id is linked to the user.
            user_id = obj.get("client_reference_id") or obj.get("metadata", {}).get("user_id")
            customer_id = obj.get("customer")
            if user_id and customer_id:
                sub = await self._get_or_create_subscription_row(db, user_id)
                sub.stripe_customer_id = customer_id

            # A credit top-up is a one-time payment, not a subscription: `mode` separates
            # them, and reading the amount from `amount_total` rather than from our own
            # request means a customer who edited the amount on Stripe's page is credited
            # what they actually paid.
            if obj.get("mode") == "payment" and user_id:
                await self._credit_top_up(db, user_id, obj)
            return

        if event_type.startswith("customer.subscription."):
            await self._sync_subscription(
                db, obj, deleted=event_type.endswith(".deleted"), event_created=event_created
            )
            return

        if event_type == "invoice.payment_failed":
            await self._set_status_by_customer(db, obj.get("customer"), "past_due")
            return

        if event_type == "refund.created":
            # The Refund object's `amount` is this refund alone, which is the delta the
            # ledger needs. It carries no customer, so the charge is fetched for the two
            # fields that decide everything: who, and whether this was a top-up at all.
            await self._reverse_purchased_credit(
                db,
                charge_id=obj.get("charge"),
                amount_cents=int(obj.get("amount") or 0),
                reason="refund",
                ref=obj.get("id"),
            )
            return

        if event_type == "charge.dispute.created":
            # The bank has already pulled the funds. The subscription's own fate arrives
            # separately as customer.subscription.deleted, so this only reverses credit.
            await self._reverse_purchased_credit(
                db,
                charge_id=obj.get("charge"),
                amount_cents=int(obj.get("amount") or 0),
                reason="chargeback",
                ref=obj.get("id"),
            )
            return

        if event_type == "charge.dispute.closed":
            # Only a WON dispute returns the money. "lost" is a refund that already
            # happened and was reversed on `created`; restoring there would hand back
            # credit for money the operator no longer has.
            if obj.get("status") != "won":
                logger.info(
                    "billing: dispute %s closed as %s — credit stays reversed",
                    obj.get("id"),
                    obj.get("status"),
                )
                return
            await self._restore_purchased_credit(
                db,
                charge_id=obj.get("charge"),
                amount_cents=int(obj.get("amount") or 0),
                ref=obj.get("id"),
            )
            return

        if event_type == "invoice.paid":
            await self._set_status_by_customer(db, obj.get("customer"), "active")
            # Only the renewal rolls the credit period. `invoice.paid` also fires for the
            # first invoice (checkout already granted) and for every mid-cycle proration —
            # a quantity or plan change emits `subscription_update` immediately, so a
            # customer who upgraded and downgraded four times would otherwise be granted
            # four months of allowance for four proration invoices.
            if obj.get("billing_reason") == "subscription_cycle":
                await self._renew_credit(db, obj)
            return

    async def _charge_owner(self, db: AsyncSession, charge_id: str | None) -> str | None:
        """The user whose purchased credit a charge bought, or ``None`` with a reason logged.

        Two gates, and the second is the one that is easy to get backwards. A refunded
        **subscription invoice** is not a refunded **top-up**: only a one-time payment has
        ``invoice = None``, and only that one ever added to ``purchased_balance_usd``.
        Debiting the purchased pocket for a refunded month of subscription would take
        credit the customer never bought with that money.
        """
        if not charge_id:
            logger.warning("billing: reversal event carries no charge id")
            return None
        # BILL-07: `to_thread`, per this module's own stated invariant — the Stripe SDK is
        # synchronous and this ran on the event loop.
        #
        # BILL-03: and it no longer swallows. The comment here used to say "never raise:
        # the money has already moved, and a failed webhook makes Stripe retry something
        # that cannot be un-done" — but retrying the WEBHOOK does not retry the refund. It
        # retries taking the credit back, which is the thing that did not happen. What the
        # old comment was right about is double-application, and `_claim_once` answers that.
        charge = await asyncio.to_thread(_stripe().Charge.retrieve, charge_id)
        if charge.get("invoice"):
            logger.info(
                "billing: charge %s is a subscription invoice, not a top-up — "
                "purchased credit untouched",
                charge_id,
            )
            return None
        sub = await self._find_by_customer(db, charge.get("customer"))
        if sub is None:
            logger.warning(
                "billing: no subscription row for customer on charge %s — reversal skipped",
                charge_id,
            )
            return None
        return sub.user_id

    async def _reverse_purchased_credit(
        self,
        db: AsyncSession,
        *,
        charge_id: str | None,
        amount_cents: int,
        reason: str,
        ref: str | None,
    ) -> None:
        """Take back credit whose money has gone — a refund or a chargeback."""
        if amount_cents <= 0:
            logger.warning("billing: %s %s carries no amount", reason, ref)
            return
        user_id = await self._charge_owner(db, charge_id)
        if user_id is None:
            return
        # BILL-03. Claimed on the REVERSAL, not on the delivery: a redelivery under a new
        # event id would otherwise debit a second time, which is what the old swallow was
        # protecting against by never retrying at all.
        if not await self._claim_once(db, f"reversal:{reason}:{ref}", "credit_reversal"):
            logger.info("billing: %s %s already reversed", reason, ref)
            return
        try:
            from app.services.openrouter_credit_service import OpenRouterCreditService

            await OpenRouterCreditService().debit(
                db, user_id, amount_usd=amount_cents / 100, reason=reason
            )
        except Exception:
            # Loud, and then RE-RAISED: `handle_event` rolls back — taking this claim with
            # it — and answers Stripe non-2xx so the reversal is tried again. Swallowing
            # committed the ledger row, and Stripe never redelivers a 2xx.
            logger.error(
                "billing: MONEY RETURNED BUT CREDIT NOT REVERSED — user=%s amount=%.2f %s=%s; "
                "rolling back so Stripe redelivers",
                user_id[:8],
                amount_cents / 100,
                reason,
                ref,
                exc_info=True,
            )
            raise

    async def _restore_purchased_credit(
        self, db: AsyncSession, *, charge_id: str | None, amount_cents: int, ref: str | None
    ) -> None:
        """Put credit back after a dispute the operator won."""
        if amount_cents <= 0:
            return
        user_id = await self._charge_owner(db, charge_id)
        if user_id is None:
            return
        if not await self._claim_once(db, f"restore:{ref}", "credit_restore"):
            logger.info("billing: dispute %s already re-credited", ref)
            return
        try:
            from app.services.openrouter_credit_service import OpenRouterCreditService

            await OpenRouterCreditService().restore(
                db, user_id, amount_usd=amount_cents / 100, reason=f"dispute {ref} won"
            )
        except Exception:
            logger.error(
                "billing: WON DISPUTE NOT RE-CREDITED — user=%s amount=%.2f dispute=%s; "
                "rolling back so Stripe redelivers",
                user_id[:8],
                amount_cents / 100,
                ref,
                exc_info=True,
            )
            raise

    async def _claim_once(self, db: AsyncSession, key: str, kind: str) -> bool:
        """Win the right to perform *key* exactly once, across redeliveries.

        The event-id ledger cannot see two deliveries of the same MONEY under different
        event ids — a redelivery with a fresh id, the success page racing the webhook, or a
        refund event Stripe re-sends after our endpoint answered non-2xx. This claim is
        keyed on the thing that must happen once (the session, the refund, the invoice)
        rather than on the delivery that asked for it.

        Taken inside a SAVEPOINT so a lost race does not poison the surrounding
        transaction — `handle_event` has already claimed its own row and still has to
        commit it. A claim taken and then rolled back by `handle_event` disappears with it,
        which is exactly what makes raising on failure safe: the retry re-claims.
        """
        try:
            async with db.begin_nested():
                db.add(StripeEvent(stripe_event_id=key, event_type=kind, payload=None))
        except IntegrityError:
            return False
        return True

    async def _claim_top_up(self, db: AsyncSession, session_id: str) -> bool:
        """Win the right to credit this checkout session exactly once.

        Keyed on the **session**, not on the Stripe event id, because two different
        deliveries can carry the same payment: a redelivery under a new event id, and the
        success page (`verify_checkout`) racing the webhook. The event-id ledger cannot
        see either of those as a duplicate.

        Taken inside a SAVEPOINT so a lost race does not poison the surrounding
        transaction — `handle_event` has already claimed its own row and still has to
        commit it.
        """
        return await self._claim_once(db, f"topup:{session_id}", "credit_topup")

    async def _credit_top_up(self, db: AsyncSession, user_id: str, session: dict) -> None:
        """Add purchased credit for a completed one-time Checkout.

        **Raises on failure, deliberately.** It used to swallow, and the comment explaining
        why was nearly right: "refusing the webhook would make Stripe retry a charge that
        cannot be un-taken." Retrying the *webhook* does not retry the *charge* — it
        redelivers the event, which is exactly what a failed grant needs and the only
        retry Stripe offers. Swallowing let `handle_event` commit its claim, so the money
        was taken, nothing was granted, and every redelivery was refused as a duplicate.
        The old docstring named "the reconciliation sweep" as the recovery; `reconcile()`
        iterates `Subscription` rows and a one-time payment is in none of them.

        Idempotency is claimed here on the session id rather than left to the caller,
        because two callers exist — the webhook and the success page — and only the
        session is common to both.
        """
        amount_cents = int(session.get("amount_total") or 0)
        session_id = str(session.get("id") or "")
        if amount_cents <= 0:
            logger.warning("billing: top-up session with no amount for user=%s", user_id[:8])
            return
        if not session_id:
            logger.warning("billing: top-up with no session id for user=%s", user_id[:8])
            return
        if not await self._claim_top_up(db, session_id):
            logger.info("billing: top-up %s already credited", session_id)
            return
        try:
            from app.services.openrouter_credit_service import OpenRouterCreditService

            await OpenRouterCreditService().top_up(db, user_id, amount_usd=amount_cents / 100)
        except Exception:
            # Loud, and with the amount, because this is money the customer paid that has
            # not been granted. Then re-raised: the caller rolls back — dropping this
            # claim with it — and answers Stripe with a non-2xx so the event is
            # redelivered and the grant tried again.
            logger.error(
                "billing: PAID BUT NOT CREDITED — user=%s amount=%.2f session=%s; "
                "rolling back so Stripe redelivers",
                user_id[:8],
                amount_cents / 100,
                session_id,
                exc_info=True,
            )
            raise

    async def _renew_credit(self, db: AsyncSession, invoice: dict) -> None:
        """Roll the included allowance for the new period; purchased credit carries over.

        The tier decides the grant, and the tier is resolved from the price on the
        subscription rather than from metadata — the same reason `_resolve_plan_id` prefers
        it: metadata records what was bought once, the price records what is billed now.
        """
        customer_id = invoice.get("customer")
        sub = await self._find_by_customer(db, customer_id)
        if sub is None:
            return
        plan = (
            (await db.execute(select(Plan).where(Plan.id == sub.plan_id))).scalar_one_or_none()
            if sub.plan_id
            else None
        )
        included = _included_credit_for(plan)
        if included is None:
            # A tier sold without a cap holds no key (D-SPEND-2b), so there is no period to
            # roll: no included pocket expires and no ceiling needs re-pushing.
            return
        # BILL-08. Claimed on the INVOICE so a redelivery cannot roll the period twice,
        # then allowed to raise. A swallowed failure was not a skipped grant: `renew()`
        # bills `spent − included_grant_usd` to the purchased pocket, so a period that
        # never rolled leaves `usage_at_period_start` behind and the NEXT renewal charges
        # purchased credit for spend the missed allowance already covered.
        invoice_id = invoice.get("id") or ""
        if invoice_id and not await self._claim_once(db, f"renew:{invoice_id}", "credit_renew"):
            logger.info("billing: renewal for invoice %s already applied", invoice_id)
            return
        try:
            from app.services.openrouter_credit_service import OpenRouterCreditService

            await OpenRouterCreditService().renew(db, sub.user_id, included_usd=included)
        except Exception:
            logger.error(
                "billing: COULD NOT ROLL THE CREDIT PERIOD — user=%s invoice=%s; rolling "
                "back so Stripe redelivers",
                sub.user_id[:8],
                invoice_id,
                exc_info=True,
            )
            raise

    async def _sync_subscription(
        self, db: AsyncSession, obj: dict, *, deleted: bool, event_created: int = 0
    ) -> None:
        """Write the subscription state this event describes — unless it is stale.

        BILL-04. Stripe does not guarantee delivery order, and this method used to write
        whatever the payload said, unconditionally. The `deleted` branch is a full teardown
        (status `canceled`, key revoked); an `updated` delivered after it resurrected a
        cancelled account and minted it a fresh spending key.

        The watermark is Stripe's own `created` for the event, stored on the row. An event
        older than the one already applied is dropped with a log line. `event_created=0`
        means "no timestamp available" — the internal callers that pass nothing — and is
        never treated as stale, because refusing to write on a missing timestamp would turn
        an unknown into an outage.
        """
        customer_id = obj.get("customer")
        sub = await self._find_by_customer(db, customer_id)
        if sub is not None and event_created:
            seen = getattr(sub, "last_event_created", None) or 0
            if event_created < seen:
                logger.info(
                    "billing: dropping out-of-order subscription event (created=%s < seen=%s) "
                    "for customer %s",
                    event_created,
                    seen,
                    str(customer_id)[:12],
                )
                return
            sub.last_event_created = event_created
            # The checkout this account was waiting on has resolved.
            sub.checkout_pending_at = None
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
            # The key outlives the subscription unless something takes it back, and a
            # revoked key is the only thing that stops a cancelled account spending.
            # `revoke` keeps the row and the purchased balance — that credit is still
            # owed, and a re-subscription provisions a key whose limit includes it again.
            await self._revoke_key(db, sub.user_id)
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

        # Arm the per-account ceiling. `llm_credit` and `provision` have existed since
        # `b48fcfc1524b` and NOTHING called provision — so the dollar ceiling the billing
        # model is built around was never created for a single account, every request ran
        # against one shared operator key, and `create_topup_session` refused every
        # top-up with "no LLM key to credit yet".
        #
        # Only for a subscription that is actually live. `past_due` has not paid and
        # `incomplete` may never; a trial IS armed, because an account that has paid
        # nothing for fourteen days is exactly the one that must not run uncapped.
        #
        # Safe on every update, not only on the transition: `provision` returns the
        # existing key before it touches `included_grant_usd`, so a re-run cannot reset a
        # grant mid-period. What it also cannot do is RAISE the grant on an upgrade —
        # that follows at the next `subscription_cycle` invoice, which is `_renew_credit`.
        if sub.status in _LIVE_SUBSCRIPTION_STATUSES:
            plan = (
                (await db.execute(select(Plan).where(Plan.id == sub.plan_id))).scalar_one_or_none()
                if sub.plan_id
                else None
            )
            await self._provision_key(db, sub.user_id, included_usd=_included_credit_for(plan))

    async def _provision_key(
        self, db: AsyncSession, user_id: str, *, included_usd: float | None
    ) -> None:
        """Create the account's OpenRouter key. Deliberately allowed to raise.

        `handle_event` rolls its idempotency claim back on an exception, so Stripe
        redelivers and this is retried. Swallowing would leave a paying customer with no
        key, no ceiling and no second attempt — the same shape as the top-up that was
        marked processed after failing to credit.

        ``included_usd=None`` is a tier sold without a cap (D-SPEND-2b): no key is minted,
        and an existing one — from a lower tier the account has just upgraded off — is
        revoked, because leaving it in place would hold an **enterprise** account to the
        ceiling it outgrew. That revocation is allowed to raise for the same reason as the
        rest of this method.
        """
        if included_usd is None:
            await self._revoke_key(db, user_id)
            logger.info(
                "billing: no key ceiling for user=%s — the tier is sold without a cap",
                user_id[:8],
            )
            return
        from app.services.openrouter_credit_service import OpenRouterCreditService

        await OpenRouterCreditService().provision(db, user_id, included_usd=included_usd)

    async def _revoke_key(self, db: AsyncSession, user_id: str) -> None:
        """Delete the account's key on cancellation. Allowed to raise, same reasoning:
        a revocation that quietly failed leaves a cancelled account still spending."""
        from app.services.openrouter_credit_service import OpenRouterCreditService

        await OpenRouterCreditService().revoke(db, user_id)

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
            if meta_plan and not any(plan.id == meta_plan for plan in plans):
                # BILL-06: the fallback wrote this straight into a foreign-key column. A
                # plan id Stripe knows and the catalogue does not is exactly the state this
                # branch exists for, and writing it makes every redelivery of the event 500
                # on the constraint — forever, because a 5xx is what Stripe retries.
                logger.error(
                    "billing: metadata plan_id=%s is not in the catalogue either; leaving "
                    "the subscription's plan untouched rather than writing a foreign key "
                    "that does not resolve",
                    meta_plan,
                )
                return None
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
