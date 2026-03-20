"""add overview_text and overview_generated_at to project_cache

Revision ID: z3a4b5c6d7e8
Revises: y2z3a4b5c6d7
Create Date: 2026-03-20
"""

import sqlalchemy as sa

from alembic import op

revision = "z3a4b5c6d7e8"
down_revision = "y2z3a4b5c6d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "project_cache",
        sa.Column("overview_text", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "project_cache",
        sa.Column("overview_generated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("project_cache", "overview_generated_at")
    op.drop_column("project_cache", "overview_text")
