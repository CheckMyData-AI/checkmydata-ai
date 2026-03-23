"""add section_hashes_json to project_cache

Revision ID: c5d6e7f8g9h0
Revises: a4b5c6d7e8f9
Create Date: 2026-03-20
"""

import sqlalchemy as sa

from alembic import op

revision = "c5d6e7f8g9h0"
down_revision = "a4b5c6d7e8f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "project_cache",
        sa.Column("section_hashes_json", sa.Text(), server_default="{}", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("project_cache", "section_hashes_json")
