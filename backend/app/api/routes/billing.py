"""Billing API (T-BILL-2/4/5/6): plan catalog, subscription state, Checkout,
Customer Portal, and the Stripe webhook.

All routes 404 when ``BILLING_ENABLED`` is off so the surface area is zero
until billing is rolled out.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.config import settings
from app.models.user import User
from app.services.billing_service import BillingError, BillingService
from app.services.entitlement_service import EntitlementService
from app.services.usage_service import UsageService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])

_billing = BillingService()
_entitlements = EntitlementService()
_usage = UsageService()


def _require_billing_enabled() -> None:
    if not settings.billing_enabled:
        raise HTTPException(status_code=404, detail="Billing is not enabled")


class CheckoutRequest(BaseModel):
    plan_id: str


@router.get("/plans")
async def list_plans(db: AsyncSession = Depends(get_db)) -> dict:
    """Public plan catalog for the pricing page."""
    _require_billing_enabled()
    plans = await _billing.list_plans(db)
    return {
        "plans": [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "price_usd_month": p.price_usd_month,
                "daily_token_limit": p.daily_token_limit or None,
                "monthly_token_limit": p.monthly_token_limit or None,
                "max_connections": p.max_connections or None,
                "max_projects": p.max_projects or None,
                "seats": p.seats,
                "trial_days": p.trial_days,
            }
            for p in plans
        ]
    }


@router.get("/subscription")
async def get_subscription(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> dict:
    """Current user's plan, subscription state, and usage vs. limits."""
    _require_billing_enabled()
    ent = await _entitlements.get_entitlements(db, user["user_id"])
    daily_limit, monthly_limit = await _entitlements.effective_token_limits(db, user["user_id"])
    try:
        budget = await _usage.check_budget(
            db, user["user_id"], daily_limit=daily_limit, monthly_limit=monthly_limit
        )
    except Exception:
        budget = {"daily_used": None, "monthly_used": None}
    return {
        "entitlements": ent.as_dict(),
        "usage": {
            "daily_used": budget.get("daily_used"),
            "monthly_used": budget.get("monthly_used"),
            "daily_limit": daily_limit or None,
            "monthly_limit": monthly_limit or None,
        },
    }


@router.post("/checkout")
async def create_checkout(
    body: CheckoutRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> dict:
    """Start a Stripe Checkout session for the requested plan."""
    _require_billing_enabled()
    db_user = (
        await db.execute(select(User).where(User.id == user["user_id"]))
    ).scalar_one_or_none()
    if db_user is None:
        raise HTTPException(status_code=401, detail="User not found")
    try:
        url = await _billing.create_checkout_session(db, db_user, body.plan_id)
    except BillingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"url": url}


@router.post("/portal")
async def create_portal(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> dict:
    """Open the Stripe Customer Portal for invoices / cancellation / card update."""
    _require_billing_enabled()
    db_user = (
        await db.execute(select(User).where(User.id == user["user_id"]))
    ).scalar_one_or_none()
    if db_user is None:
        raise HTTPException(status_code=401, detail="User not found")
    try:
        url = await _billing.create_portal_session(db, db_user)
    except BillingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"url": url}


@router.post("/webhook")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """Stripe webhook receiver — signature-verified, idempotent (T-BILL-5)."""
    _require_billing_enabled()
    signature = request.headers.get("stripe-signature", "")
    payload = await request.body()
    try:
        event = _billing.verify_webhook(payload, signature)
    except BillingError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:  # bad signature / malformed payload
        logger.warning("billing: webhook signature verification failed: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid webhook signature") from exc

    try:
        processed = await _billing.handle_event(db, dict(event))
    except Exception:
        logger.exception("billing: failed to process stripe event %s", event.get("id"))
        # 500 → Stripe retries the delivery later.
        raise HTTPException(status_code=500, detail="Event processing failed") from None
    return {"received": True, "duplicate": not processed}
