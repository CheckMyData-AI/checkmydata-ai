"""add connection_id to chat_sessions

Revision ID: g2h3i4j5k6l7
Revises: f1a2b3c4d5e6
Create Date: 2026-03-17
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "g2h3i4j5k6l7"
down_revision: str | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("chat_sessions") as batch_op:
        batch_op.add_column(
            sa.Column("connection_id", sa.String(36), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_chat_sessions_connection_id",
            "connections",
            ["connection_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("chat_sessions") as batch_op:
        batch_op.drop_constraint("fk_chat_sessions_connection_id", type_="foreignkey")
        batch_op.drop_column("connection_id")
