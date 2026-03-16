"""add tool_calls_json to chat_messages

Revision ID: a1b2c3d4e5f6
Revises: f4e7a1c23b90
Create Date: 2026-03-16
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f4e7a1c23b90"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    with op.batch_alter_table("chat_messages") as batch_op:
        batch_op.add_column(
            sa.Column("tool_calls_json", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    with op.batch_alter_table("chat_messages") as batch_op:
        batch_op.drop_column("tool_calls_json")
