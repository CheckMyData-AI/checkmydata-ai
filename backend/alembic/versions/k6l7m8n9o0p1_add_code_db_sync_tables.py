"""add code_db_sync and code_db_sync_summary tables

Revision ID: k6l7m8n9o0p1
Revises: j5k6l7m8n9o0
Create Date: 2026-03-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "k6l7m8n9o0p1"
down_revision: Union[str, None] = "j5k6l7m8n9o0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "code_db_sync",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "connection_id",
            sa.String(36),
            sa.ForeignKey("connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("table_name", sa.String(255), nullable=False),
        sa.Column("entity_name", sa.String(255), nullable=True),
        sa.Column("entity_file_path", sa.Text, nullable=True),
        sa.Column("code_columns_json", sa.Text, server_default="[]"),
        sa.Column("used_in_files_json", sa.Text, server_default="[]"),
        sa.Column("read_count", sa.Integer, server_default="0"),
        sa.Column("write_count", sa.Integer, server_default="0"),
        sa.Column("data_format_notes", sa.Text, server_default=""),
        sa.Column("column_sync_notes_json", sa.Text, server_default="{}"),
        sa.Column("business_logic_notes", sa.Text, server_default=""),
        sa.Column("conversion_warnings", sa.Text, server_default=""),
        sa.Column("query_recommendations", sa.Text, server_default=""),
        sa.Column("sync_status", sa.String(50), server_default="unknown"),
        sa.Column("confidence_score", sa.Integer, server_default="3"),
        sa.Column("synced_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "connection_id", "table_name", name="uq_code_db_sync_conn_table"
        ),
    )

    op.create_table(
        "code_db_sync_summary",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "connection_id",
            sa.String(36),
            sa.ForeignKey("connections.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("total_tables", sa.Integer, server_default="0"),
        sa.Column("synced_tables", sa.Integer, server_default="0"),
        sa.Column("code_only_tables", sa.Integer, server_default="0"),
        sa.Column("db_only_tables", sa.Integer, server_default="0"),
        sa.Column("mismatch_tables", sa.Integer, server_default="0"),
        sa.Column("global_notes", sa.Text, server_default=""),
        sa.Column("data_conventions", sa.Text, server_default=""),
        sa.Column("query_guidelines", sa.Text, server_default=""),
        sa.Column("sync_status", sa.String(20), server_default="idle"),
        sa.Column("synced_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("code_db_sync_summary")
    op.drop_table("code_db_sync")
