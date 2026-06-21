"""add heartbeat_at to summary and checkpoint tables

Revision ID: 7968486e00a3
Revises: d3e4f5g6h7i8
Create Date: 2026-06-21 02:19:32.832323
"""

import sqlalchemy as sa

from alembic import op

revision = "7968486e00a3"
down_revision = "d3e4f5g6h7i8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("code_db_sync_summary", schema=None) as batch_op:
        batch_op.add_column(sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))

    with op.batch_alter_table("db_index_summary", schema=None) as batch_op:
        batch_op.add_column(sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))

    with op.batch_alter_table("indexing_checkpoint", schema=None) as batch_op:
        batch_op.add_column(sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("indexing_checkpoint", schema=None) as batch_op:
        batch_op.drop_column("heartbeat_at")

    with op.batch_alter_table("db_index_summary", schema=None) as batch_op:
        batch_op.drop_column("heartbeat_at")

    with op.batch_alter_table("code_db_sync_summary", schema=None) as batch_op:
        batch_op.drop_column("heartbeat_at")
