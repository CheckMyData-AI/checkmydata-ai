"""add status to chat_sessions

Revision ID: d8e9f0g1h2i3
Revises: c6d7e8f9g0h1
Create Date: 2026-04-01
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d8e9f0g1h2i3"
down_revision: str | None = "d7e8f9g0h1i2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("chat_sessions") as batch_op:
        batch_op.add_column(
            sa.Column("status", sa.String(20), nullable=False, server_default="idle")
        )


def downgrade() -> None:
    with op.batch_alter_table("chat_sessions") as batch_op:
        batch_op.drop_column("status")
