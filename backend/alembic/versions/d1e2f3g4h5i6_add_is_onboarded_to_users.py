"""add is_onboarded to users

Revision ID: d1e2f3g4h5i6
Revises: c5d6e7f8g9h0
Create Date: 2026-03-21
"""

import sqlalchemy as sa
from alembic import op

revision = "d1e2f3g4h5i6"
down_revision = "c5d6e7f8g9h0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("is_onboarded", sa.Boolean(), server_default="0", nullable=False),
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("is_onboarded")
