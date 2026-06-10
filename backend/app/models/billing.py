"""Billing data model (T-BILL-1): plans, subscriptions, Stripe event dedupe.

The Stripe webhook (T-BILL-5) is the only writer of subscription state;
``stripe_events.stripe_event_id`` has a unique constraint so replayed or
duplicated events can never double-grant.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
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
    """Plan catalog row. ``id`` is a stable slug ("free", "pro", "team")."""

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
