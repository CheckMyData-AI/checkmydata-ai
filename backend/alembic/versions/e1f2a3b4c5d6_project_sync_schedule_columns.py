"""project per-project daily-sync schedule columns

Revision ID: e1f2a3b4c5d6
Revises: a1f2b3c4d5e6
Create Date: 2026-06-22

"""

import sqlalchemy as sa
from alembic import op

revision = "e1f2a3b4c5d6"
down_revision = "a1f2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("sync_schedule_enabled", sa.Boolean(), nullable=True))
    op.add_column("projects", sa.Column("sync_schedule_hour", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "sync_schedule_hour")
    op.drop_column("projects", "sync_schedule_enabled")
