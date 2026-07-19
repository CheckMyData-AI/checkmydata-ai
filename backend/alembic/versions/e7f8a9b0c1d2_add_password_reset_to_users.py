"""add password reset columns to users

Revision ID: e7f8a9b0c1d2
Revises: d5e6f7a8b9c0
Create Date: 2026-07-19

Adds the single-use password-reset token (SHA-256 hash) + its expiry to the
users table (SCN-013). Both columns are nullable, so this is a safe additive
migration on Postgres (prod) and SQLite (dev) alike.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "e7f8a9b0c1d2"
down_revision: str | None = "d5e6f7a8b9c0"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("password_reset_token", sa.String(64), nullable=True))
        batch_op.add_column(
            sa.Column("password_reset_expires_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("password_reset_expires_at")
        batch_op.drop_column("password_reset_token")
