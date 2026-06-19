"""add knowledge_sync_runs table

Revision ID: c2d3e4f5g6h7
Revises: b1l2l3i4n5g6
Create Date: 2026-06-19
"""

import sqlalchemy as sa

from alembic import op

revision = "c2d3e4f5g6h7"
down_revision = "b1l2l3i4n5g6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_sync_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("trigger", sa.String(50), nullable=False, server_default="scheduled"),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("duration_seconds", sa.Float, nullable=True),
        sa.Column("steps_json", sa.JSON, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
    )
    op.create_index(
        "ix_knowledge_sync_runs_project_id",
        "knowledge_sync_runs",
        ["project_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_sync_runs_project_id", table_name="knowledge_sync_runs")
    op.drop_table("knowledge_sync_runs")
