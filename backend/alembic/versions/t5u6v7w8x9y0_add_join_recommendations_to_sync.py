"""add join_recommendations to code_db_sync_summary

Revision ID: t5u6v7w8x9y0
Revises: s4t5u6v7w8x9
Create Date: 2026-03-19 14:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "t5u6v7w8x9y0"
down_revision: Union[str, None] = "s4t5u6v7w8x9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "code_db_sync_summary",
        sa.Column("join_recommendations", sa.Text, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("code_db_sync_summary", "join_recommendations")
