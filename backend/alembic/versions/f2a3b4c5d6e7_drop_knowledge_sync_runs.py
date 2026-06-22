"""drop knowledge_sync_runs (superseded by indexing_runs kind=daily_sync)

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-06-22

"""

import sqlalchemy as sa
from alembic import op

revision = "f2a3b4c5d6e7"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("knowledge_sync_runs")


def downgrade() -> None:
    op.create_table(
        "knowledge_sync_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("trigger", sa.String(length=50), nullable=False, server_default="scheduled"),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("steps_json", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_knowledge_sync_runs_project_id", "knowledge_sync_runs", ["project_id"]
    )
