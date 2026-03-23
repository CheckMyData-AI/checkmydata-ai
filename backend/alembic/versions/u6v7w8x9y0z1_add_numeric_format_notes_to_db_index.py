"""add numeric_format_notes to db_index

Revision ID: u6v7w8x9y0z1
Revises: t5u6v7w8x9y0
Create Date: 2026-03-19 18:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "u6v7w8x9y0z1"
down_revision: str | None = "t5u6v7w8x9y0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "db_index",
        sa.Column("numeric_format_notes", sa.Text, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("db_index", "numeric_format_notes")
