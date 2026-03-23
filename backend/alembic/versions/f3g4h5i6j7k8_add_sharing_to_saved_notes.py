"""add sharing columns to saved_notes

Revision ID: f3g4h5i6j7k8
Revises: e2f3g4h5i6j7
Create Date: 2026-03-21
"""

import sqlalchemy as sa

from alembic import op

revision = "f3g4h5i6j7k8"
down_revision = "e2f3g4h5i6j7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("saved_notes", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("is_shared", sa.Boolean(), server_default="0", nullable=False),
        )
        batch_op.add_column(
            sa.Column("shared_by", sa.String(255), nullable=True),
        )


def downgrade() -> None:
    with op.batch_alter_table("saved_notes", schema=None) as batch_op:
        batch_op.drop_column("shared_by")
        batch_op.drop_column("is_shared")
