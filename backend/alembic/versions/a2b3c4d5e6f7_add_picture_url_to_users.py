"""add picture_url to users

Revision ID: a2b3c4d5e6f7
Revises: x1y2z3a4b5c6
Create Date: 2026-03-20
"""

import sqlalchemy as sa

from alembic import op

revision: str = "a2b3c4d5e6f7"
down_revision: str | None = "x1y2z3a4b5c6"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("picture_url", sa.String(512), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("picture_url")
