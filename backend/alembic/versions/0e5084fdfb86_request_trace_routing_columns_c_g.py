"""request_trace routing columns (C-G)

Revision ID: 0e5084fdfb86
Revises: 9ff3cede6d84
Create Date: 2026-07-04 14:16:49.672819
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0e5084fdfb86"
down_revision: Union[str, None] = "9ff3cede6d84"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("request_traces", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("route", sa.String(length=30), server_default="unknown", nullable=False)
        )
        batch_op.add_column(
            sa.Column("complexity", sa.String(length=20), server_default="unknown", nullable=False)
        )
        batch_op.add_column(
            sa.Column("estimated_queries", sa.Integer(), server_default="0", nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("request_traces", schema=None) as batch_op:
        batch_op.drop_column("estimated_queries")
        batch_op.drop_column("complexity")
        batch_op.drop_column("route")
