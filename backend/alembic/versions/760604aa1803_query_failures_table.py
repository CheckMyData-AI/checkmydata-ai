"""query_failures table

Revision ID: 760604aa1803
Revises: e909ec65d857
Create Date: 2026-06-30 17:04:08.077154

Hand-trimmed: autogenerate emitted spurious diffs from local dev-DB drift
(unrelated alter_column / index churn, and a destructive audit_logs drop). This
migration contains ONLY the intended change — create the append-only
``query_failures`` table. Server defaults are Postgres-safe (string/text
literals + CURRENT_TIMESTAMP; no boolean columns — avoids the v185 boolean
default outage class).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "760604aa1803"
down_revision: str | None = "e909ec65d857"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "query_failures",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("connection_id", sa.String(length=36), nullable=True),
        sa.Column("workflow_id", sa.String(length=36), nullable=True),
        sa.Column("trace_id", sa.String(length=36), nullable=True),
        sa.Column("session_id", sa.String(length=36), nullable=True),
        sa.Column("message_id", sa.String(length=36), nullable=True),
        sa.Column("db_type", sa.String(length=30), server_default="", nullable=False),
        sa.Column("question", sa.Text(), server_default="", nullable=False),
        sa.Column("failed_sql", sa.Text(), server_default="", nullable=False),
        sa.Column("error_type", sa.String(length=40), server_default="unknown", nullable=False),
        sa.Column("failure_kind", sa.String(length=20), nullable=True),
        sa.Column("raw_error", sa.Text(), server_default="", nullable=False),
        sa.Column("attempts_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("final_status", sa.String(length=20), server_default="failed", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_query_failures_project_created", "query_failures", ["project_id", "created_at"]
    )
    op.create_index(
        "ix_query_failures_connection_created", "query_failures", ["connection_id", "created_at"]
    )
    op.create_index("ix_query_failures_error_type", "query_failures", ["error_type"])
    op.create_index("ix_query_failures_workflow_id", "query_failures", ["workflow_id"])


def downgrade() -> None:
    op.drop_index("ix_query_failures_workflow_id", table_name="query_failures")
    op.drop_index("ix_query_failures_error_type", table_name="query_failures")
    op.drop_index("ix_query_failures_connection_created", table_name="query_failures")
    op.drop_index("ix_query_failures_project_created", table_name="query_failures")
    op.drop_table("query_failures")
