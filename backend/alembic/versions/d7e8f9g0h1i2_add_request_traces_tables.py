"""add request_traces and trace_spans tables

Revision ID: d7e8f9g0h1i2
Revises: c6d7e8f9g0h1
Create Date: 2026-03-30
"""

import sqlalchemy as sa

from alembic import op

revision = "d7e8f9g0h1i2"
down_revision = "c6d7e8f9g0h1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "request_traces",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("chat_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "message_id",
            sa.String(36),
            sa.ForeignKey("chat_messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("assistant_message_id", sa.String(36), nullable=True),
        sa.Column("workflow_id", sa.String(36), nullable=False, index=True),
        sa.Column("question", sa.Text(), nullable=False, server_default=""),
        sa.Column("response_type", sa.String(30), nullable=False, server_default="text"),
        sa.Column("status", sa.String(20), nullable=False, server_default="started"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("total_duration_ms", sa.Float(), nullable=True),
        sa.Column("total_llm_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_db_queries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=True),
        sa.Column("llm_provider", sa.String(50), nullable=False, server_default="unknown"),
        sa.Column("llm_model", sa.String(100), nullable=False, server_default="unknown"),
        sa.Column("steps_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("steps_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_request_traces_project_created",
        "request_traces",
        ["project_id", "created_at"],
    )
    op.create_index(
        "ix_request_traces_user_created",
        "request_traces",
        ["user_id", "created_at"],
    )

    op.create_table(
        "trace_spans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "trace_id",
            sa.String(36),
            sa.ForeignKey("request_traces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_span_id",
            sa.String(36),
            sa.ForeignKey("trace_spans.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("span_type", sa.String(30), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="started"),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("input_preview", sa.Text(), nullable=True),
        sa.Column("output_preview", sa.Text(), nullable=True),
        sa.Column("token_usage_json", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_trace_spans_trace_order", "trace_spans", ["trace_id", "order_index"]
    )
    op.create_index("ix_trace_spans_type", "trace_spans", ["span_type"])
    op.create_index("ix_trace_spans_status", "trace_spans", ["status"])


def downgrade() -> None:
    op.drop_table("trace_spans")
    op.drop_table("request_traces")
