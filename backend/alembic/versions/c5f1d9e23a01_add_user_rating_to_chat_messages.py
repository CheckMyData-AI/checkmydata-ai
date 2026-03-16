"""add user_rating to chat_messages

Revision ID: c5f1d9e23a01
Revises: b3c8f2a71e56
Create Date: 2026-03-14
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c5f1d9e23a01'
down_revision: Union[str, None] = 'b3c8f2a71e56'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('chat_messages') as batch_op:
        batch_op.add_column(
            sa.Column('user_rating', sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    with op.batch_alter_table('chat_messages') as batch_op:
        batch_op.drop_column('user_rating')
