"""add pipeline_runs table for multi-stage query tracking

Revision ID: a4b5c6d7e8f9
Revises: z3a4b5c6d7e8
Create Date: 2026-03-20
"""

import sqlalchemy as sa

from alembic import op

revision = "a4b5c6d7e8f9"
down_revision = "z3a4b5c6d7e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "message_id",
            sa.String(36),
            sa.ForeignKey("chat_messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("user_question", sa.Text(), nullable=False),
        sa.Column("plan_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="planning"
        ),
        sa.Column("current_stage_idx", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stage_results_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("user_feedback_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("pipeline_runs")
