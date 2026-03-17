"""add indexing_status to db_index_summary

Revision ID: j5k6l7m8n9o0
Revises: i4j5k6l7m8n9
Create Date: 2026-03-17
"""

from alembic import op
import sqlalchemy as sa

revision = "j5k6l7m8n9o0"
down_revision = "i4j5k6l7m8n9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "db_index_summary",
        sa.Column("indexing_status", sa.String(20), server_default="idle", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("db_index_summary", "indexing_status")
