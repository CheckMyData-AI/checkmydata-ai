"""add self-improvement tables (session_notes, data_validation_feedback,
data_benchmarks, data_investigations) and code_db_sync columns

Revision ID: x1y2z3a4b5c6
Revises: w8x9y0z1a2b3
Create Date: 2026-03-20
"""

import sqlalchemy as sa

from alembic import op

revision = "x1y2z3a4b5c6"
down_revision = "w8x9y0z1a2b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- session_notes ---
    op.create_table(
        "session_notes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "connection_id",
            sa.String(36),
            sa.ForeignKey("connections.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("note_hash", sa.String(32), nullable=False),
        sa.Column("source_session_id", sa.String(36), nullable=True),
        sa.Column("confidence", sa.Float(), server_default="0.7"),
        sa.Column("is_verified", sa.Boolean(), server_default="0"),
        sa.Column("is_active", sa.Boolean(), server_default="1"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "connection_id",
            "category",
            "subject",
            "note_hash",
            name="uq_session_note_dedup",
        ),
    )

    # --- data_validation_feedback ---
    op.create_table(
        "data_validation_feedback",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "connection_id",
            sa.String(36),
            sa.ForeignKey("connections.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("message_id", sa.String(36), nullable=False, index=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("metric_description", sa.Text(), server_default=""),
        sa.Column("agent_value", sa.Text(), server_default=""),
        sa.Column("user_expected_value", sa.Text(), nullable=True),
        sa.Column("deviation_pct", sa.Float(), nullable=True),
        sa.Column("verdict", sa.String(30), nullable=False, server_default="unknown"),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("resolved", sa.Boolean(), server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # --- data_benchmarks ---
    op.create_table(
        "data_benchmarks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "connection_id",
            sa.String(36),
            sa.ForeignKey("connections.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("metric_key", sa.String(500), nullable=False, index=True),
        sa.Column("metric_description", sa.Text(), server_default=""),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("value_numeric", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(50), nullable=True),
        sa.Column("confidence", sa.Float(), server_default="0.7"),
        sa.Column("source", sa.String(50), server_default="agent_derived"),
        sa.Column("times_confirmed", sa.Integer(), server_default="1"),
        sa.Column("last_confirmed_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # --- data_investigations ---
    op.create_table(
        "data_investigations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "validation_feedback_id",
            sa.String(36),
            sa.ForeignKey("data_validation_feedback.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "connection_id",
            sa.String(36),
            sa.ForeignKey("connections.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("trigger_message_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(30), server_default="collecting_info"),
        sa.Column("phase", sa.String(50), server_default="collect_info"),
        sa.Column("user_complaint_type", sa.String(50), server_default="other"),
        sa.Column("user_complaint_detail", sa.Text(), nullable=True),
        sa.Column("user_expected_value", sa.Text(), nullable=True),
        sa.Column("problematic_column", sa.String(255), nullable=True),
        sa.Column("investigation_log_json", sa.Text(), server_default="[]"),
        sa.Column("original_query", sa.Text(), server_default=""),
        sa.Column("original_result_summary", sa.Text(), server_default="{}"),
        sa.Column("corrected_query", sa.Text(), nullable=True),
        sa.Column("corrected_result_json", sa.Text(), nullable=True),
        sa.Column("root_cause", sa.Text(), nullable=True),
        sa.Column("root_cause_category", sa.String(50), nullable=True),
        sa.Column("learnings_created_json", sa.Text(), nullable=True),
        sa.Column("notes_created_json", sa.Text(), nullable=True),
        sa.Column("benchmarks_updated_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )

    # --- code_db_sync new columns ---
    with op.batch_alter_table("code_db_sync") as batch_op:
        batch_op.add_column(sa.Column("required_filters_json", sa.Text(), server_default="{}"))
        batch_op.add_column(sa.Column("column_value_mappings_json", sa.Text(), server_default="{}"))


def downgrade() -> None:
    with op.batch_alter_table("code_db_sync") as batch_op:
        batch_op.drop_column("column_value_mappings_json")
        batch_op.drop_column("required_filters_json")

    op.drop_table("data_investigations")
    op.drop_table("data_benchmarks")
    op.drop_table("data_validation_feedback")
    op.drop_table("session_notes")
