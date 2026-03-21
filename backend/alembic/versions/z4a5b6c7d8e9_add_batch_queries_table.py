"""add batch_queries table

Revision ID: z4a5b6c7d8e9
Revises: y2z3a4b5c6d7
Create Date: 2026-03-21
"""

import sqlalchemy as sa

from alembic import op

revision = "z4a5b6c7d8e9"
down_revision = "y2z3a4b5c6d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "batch_queries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "connection_id",
            sa.String(36),
            sa.ForeignKey("connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("queries_json", sa.Text, nullable=False),
        sa.Column("note_ids_json", sa.Text, nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("results_json", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    with op.batch_alter_table("batch_queries") as batch_op:
        batch_op.create_index("ix_batch_queries_user_id", ["user_id"])
        batch_op.create_index("ix_batch_queries_project_id", ["project_id"])


def downgrade() -> None:
    op.drop_table("batch_queries")
