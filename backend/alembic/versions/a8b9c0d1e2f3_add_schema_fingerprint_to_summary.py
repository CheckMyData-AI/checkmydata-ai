"""add schema_fingerprint to db_index_summary

Revision ID: a8b9c0d1e2f3
Revises: 68aa15e554e2
Create Date: 2026-06-03 20:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a8b9c0d1e2f3"
down_revision: str | None = "68aa15e554e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "db_index_summary",
        sa.Column("schema_fingerprint", sa.Text, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("db_index_summary", "schema_fingerprint")
