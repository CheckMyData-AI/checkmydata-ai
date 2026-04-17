"""add deactivated_at to session_notes

Revision ID: a5b6c7d8e9f0
Revises: d8e9f0g1h2i3
Create Date: 2026-04-13
"""

import sqlalchemy as sa

from alembic import op

revision = "a5b6c7d8e9f0"
down_revision = "d8e9f0g1h2i3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "session_notes",
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("session_notes", "deactivated_at")
