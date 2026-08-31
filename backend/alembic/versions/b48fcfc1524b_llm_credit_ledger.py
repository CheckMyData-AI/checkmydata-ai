"""llm_credit: two pockets over one OpenRouter counter

Revision ID: b48fcfc1524b
Revises: 4f1a29a0e973
Create Date: 2026-08-31

**Hand-written, and `--autogenerate` must not be used to regenerate it.** Run against this
project's dev SQLite database, autogenerate proposed `op.drop_table('audit_logs')` plus a
re-creation of `doc_embeddings` and column rewrites across a dozen tables — because the
Postgres-only migrations are no-ops on SQLite, so the dev schema legitimately differs from
the models and every difference reads to alembic as drift to "fix". Applying that would
destroy the audit trail.

The table itself: OpenRouter gives one spend counter per key (`limit`, `usage`), and the
billing model needs two pockets with different lifetimes — an included allowance that
expires monthly, and purchased credit that does not. `usage_at_period_start` is the hinge,
because OpenRouter's `usage` never resets.

Money is `Numeric`, not float, for the same reason revenue is `Numeric(18,4)` in the
analytics fact tables.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b48fcfc1524b"
down_revision = "4f1a29a0e973"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_credit",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("key_hash", sa.String(length=128), nullable=True),
        sa.Column("key_encrypted", sa.Text(), nullable=True),
        sa.Column(
            "usage_at_period_start",
            sa.Numeric(precision=12, scale=6),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "included_grant_usd",
            sa.Numeric(precision=12, scale=6),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "purchased_balance_usd",
            sa.Numeric(precision=12, scale=6),
            server_default="0",
            nullable=False,
        ),
        sa.Column("provision_count", sa.Integer(), server_default="0", nullable=False),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    # Dropping this loses the record of purchased credit, which is money owed. The key
    # itself is recoverable — it can be re-provisioned — but a purchased balance cannot be
    # reconstructed from anything else, so a downgrade past this point needs the row
    # exported first.
    op.drop_table("llm_credit")
