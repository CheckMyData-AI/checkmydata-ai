"""add billing tables: plans, subscriptions, stripe_events (T-BILL-1)

Revision ID: b1l2l3i4n5g6
Revises: a8b9c0d1e2f3
Create Date: 2026-06-09
"""

import sqlalchemy as sa

from alembic import op

revision = "b1l2l3i4n5g6"
down_revision = "a8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    plans = op.create_table(
        "plans",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("stripe_price_id", sa.String(255), nullable=True),
        sa.Column("price_usd_month", sa.Float, nullable=False, server_default="0"),
        sa.Column("daily_token_limit", sa.Integer, nullable=False, server_default="0"),
        sa.Column("monthly_token_limit", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_connections", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_projects", sa.Integer, nullable=False, server_default="0"),
        sa.Column("seats", sa.Integer, nullable=False, server_default="1"),
        sa.Column("trial_days", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "plan_id",
            sa.String(50),
            sa.ForeignKey("plans.id"),
            nullable=False,
            server_default="free",
        ),
        sa.Column("stripe_customer_id", sa.String(255), nullable=True, unique=True),
        sa.Column("stripe_subscription_id", sa.String(255), nullable=True, unique=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="free"),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "cancel_at_period_end", sa.Boolean, nullable=False, server_default=sa.false()
        ),
        sa.Column("trial_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    with op.batch_alter_table("subscriptions") as batch_op:
        batch_op.create_index("ix_subscriptions_user_id", ["user_id"])
        batch_op.create_index("ix_subscriptions_stripe_customer_id", ["stripe_customer_id"])

    op.create_table(
        "stripe_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("stripe_event_id", sa.String(255), nullable=False, unique=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("payload", sa.Text, nullable=True),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    with op.batch_alter_table("stripe_events") as batch_op:
        batch_op.create_index("ix_stripe_events_stripe_event_id", ["stripe_event_id"])

    # Seed the default catalog. Stripe price ids are filled from env/admin later;
    # limits follow docs/production-plan/04-BACKLOG.md (T-BILL-1).
    op.bulk_insert(
        plans,
        [
            {
                "id": "free",
                "name": "Free",
                "description": "Try CheckMyData on a single project.",
                "stripe_price_id": None,
                "price_usd_month": 0.0,
                "daily_token_limit": 100_000,
                "monthly_token_limit": 1_000_000,
                "max_connections": 1,
                "max_projects": 1,
                "seats": 1,
                "trial_days": 0,
                "is_active": True,
                "sort_order": 0,
            },
            {
                "id": "pro",
                "name": "Pro",
                "description": "For individual analysts and small teams.",
                "stripe_price_id": None,
                "price_usd_month": 49.0,
                "daily_token_limit": 1_000_000,
                "monthly_token_limit": 15_000_000,
                "max_connections": 5,
                "max_projects": 5,
                "seats": 3,
                "trial_days": 14,
                "is_active": True,
                "sort_order": 1,
            },
            {
                "id": "team",
                "name": "Team",
                "description": "For data teams that need scale and collaboration.",
                "stripe_price_id": None,
                "price_usd_month": 199.0,
                "daily_token_limit": 5_000_000,
                "monthly_token_limit": 75_000_000,
                "max_connections": 25,
                "max_projects": 25,
                "seats": 10,
                "trial_days": 14,
                "is_active": True,
                "sort_order": 2,
            },
        ],
    )


def downgrade() -> None:
    op.drop_table("stripe_events")
    op.drop_table("subscriptions")
    op.drop_table("plans")
