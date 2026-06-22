"""add indexing_runs, indexing_run_events, error_log; request_traces.failure_kind

Revision ID: a1f2b3c4d5e6
Revises: 7968486e00a3
Create Date: 2026-06-22

"""

import sqlalchemy as sa
from alembic import op

revision = "a1f2b3c4d5e6"
down_revision = "7968486e00a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "indexing_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workflow_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("connection_id", sa.String(length=36), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("current_step", sa.String(length=64), nullable=True),
        sa.Column("step_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_steps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress_pct", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("failure_kind", sa.String(length=20), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("meta_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connection_id"], ["connections.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_indexing_runs_workflow", "indexing_runs", ["workflow_id"], unique=True)
    op.create_index(
        "ix_indexing_runs_history", "indexing_runs", ["project_id", "kind", "created_at"]
    )
    op.create_index("ix_indexing_runs_active", "indexing_runs", ["project_id", "kind", "status"])
    # Defense-in-depth single-active guard (partial unique). The code-level guard in
    # RunCoordinator.start is the primary enforcement.
    op.create_index(
        "uq_indexing_runs_active_one",
        "indexing_runs",
        ["project_id", "kind", sa.text("coalesce(connection_id, '')")],
        unique=True,
        postgresql_where=sa.text("status IN ('queued','running','cancelling')"),
        sqlite_where=sa.text("status IN ('queued','running','cancelling')"),
    )

    op.create_table(
        "indexing_run_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("step", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("elapsed_ms", sa.Float(), nullable=True),
        sa.Column("progress_pct", sa.Integer(), nullable=True),
        sa.Column("level", sa.String(length=10), nullable=False, server_default="info"),
        sa.ForeignKeyConstraint(["run_id"], ["indexing_runs.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_indexing_run_events_run_ts", "indexing_run_events", ["run_id", "ts"])

    op.create_table(
        "error_log",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("signature", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("failure_kind", sa.String(length=20), nullable=True),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("sample_ref", sa.String(length=36), nullable=True),
        sa.Column("occurrences", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("meta_json", sa.Text(), nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "uq_error_log_project_sig", "error_log", ["project_id", "signature"], unique=True
    )
    op.create_index("ix_error_log_project_lastseen", "error_log", ["project_id", "last_seen_at"])
    op.create_index("ix_error_log_status", "error_log", ["status"])

    op.add_column("request_traces", sa.Column("failure_kind", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("request_traces", "failure_kind")
    op.drop_index("ix_error_log_status", table_name="error_log")
    op.drop_index("ix_error_log_project_lastseen", table_name="error_log")
    op.drop_index("uq_error_log_project_sig", table_name="error_log")
    op.drop_table("error_log")
    op.drop_index("ix_indexing_run_events_run_ts", table_name="indexing_run_events")
    op.drop_table("indexing_run_events")
    op.drop_index("uq_indexing_runs_active_one", table_name="indexing_runs")
    op.drop_index("ix_indexing_runs_active", table_name="indexing_runs")
    op.drop_index("ix_indexing_runs_history", table_name="indexing_runs")
    op.drop_index("ix_indexing_runs_workflow", table_name="indexing_runs")
    op.drop_table("indexing_runs")
