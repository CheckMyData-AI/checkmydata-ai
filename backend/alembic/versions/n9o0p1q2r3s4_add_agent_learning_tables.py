"""add agent_learning tables

Revision ID: n9o0p1q2r3s4
Revises: m8n9o0p1q2r3
Create Date: 2026-03-18

"""

import sqlalchemy as sa

from alembic import op

revision = "n9o0p1q2r3s4"
down_revision = "m8n9o0p1q2r3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_learnings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "connection_id",
            sa.String(36),
            sa.ForeignKey("connections.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("lesson", sa.Text(), nullable=False),
        sa.Column("lesson_hash", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float(), server_default="0.6"),
        sa.Column("source_query", sa.Text(), nullable=True),
        sa.Column("source_error", sa.Text(), nullable=True),
        sa.Column("times_confirmed", sa.Integer(), server_default="0"),
        sa.Column("times_applied", sa.Integer(), server_default="0"),
        sa.Column("is_active", sa.Boolean(), server_default="1"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "connection_id", "category", "subject", "lesson_hash",
            name="uq_agent_learning_dedup",
        ),
    )

    op.create_table(
        "agent_learning_summaries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "connection_id",
            sa.String(36),
            sa.ForeignKey("connections.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("total_lessons", sa.Integer(), server_default="0"),
        sa.Column("lessons_by_category_json", sa.Text(), server_default="{}"),
        sa.Column("compiled_prompt", sa.Text(), server_default=""),
        sa.Column("last_compiled_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("agent_learning_summaries")
    op.drop_table("agent_learnings")
