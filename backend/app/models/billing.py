"""Billing data model (T-BILL-1): plans, subscriptions, Stripe event dedupe.

The Stripe webhook (T-BILL-5) is the only writer of subscription state;
``stripe_events.stripe_event_id`` has a unique constraint so replayed or
duplicated events can never double-grant.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Plan(Base):
    """Plan catalog row. ``id`` is a stable slug ("base", "scale", "team", "enterprise").

    Retired slugs ("free", "pro") keep their rows so already-sold subscriptions still
    resolve; `is_active` governs only what can be BOUGHT. See
    `app/services/plan_catalogue.py` for the live ladder.
    """

    __tablename__ = "plans"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Stripe price for the monthly recurring charge; empty for the free plan.
    stripe_price_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    price_usd_month: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Entitlement limits. 0 = unlimited.
    daily_token_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    monthly_token_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_connections: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_projects: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Bytes of index allowed per project; 0 = unlimited. The tier axis the catalogue
    # copy promised ("1 GB index") from 2026-08-31 with no column behind it.
    max_index_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    seats: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    trial_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Subscription(Base):
    """One row per user; reflects the user's current Stripe subscription."""

    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    plan_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("plans.id"), nullable=False, default="free"
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True, index=True
    )
    stripe_subscription_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True
    )
    # Stripe subscription lifecycle status:
    # free | trialing | active | past_due | canceled | incomplete | unpaid
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="free")
    current_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Stripe's `created` for the most recent subscription event applied to this row.
    #: BILL-04: Stripe does not guarantee delivery order and the `deleted` branch is a full
    #: teardown, so an `updated` arriving after it resurrected a cancelled account. `NULL`
    #: means no event has been applied under the watermark rule yet, which is never treated
    #: as stale — an unknown must not become a refusal to write.
    last_event_created: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    #: When a Checkout session for a subscription was last opened for this account.
    #: BILL-05: the duplicate guard read `stripe_subscription_id`, which stays NULL until a
    #: webhook lands minutes later — so it could not see a checkout in flight, which is
    #: precisely the window its own comment says it exists to close ("before the money
    #: moves"). Cleared when the subscription id arrives or when the window lapses.
    checkout_pending_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    trial_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class StripeEvent(Base):
    """Webhook idempotency ledger (T-BILL-5)."""

    __tablename__ = "stripe_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    stripe_event_id: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
