"""add db_index and db_index_summary tables

Revision ID: i4j5k6l7m8n9
Revises: h3i4j5k6l7m8
Create Date: 2026-03-17
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "i4j5k6l7m8n9"
down_revision: str | None = "h3i4j5k6l7m8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "db_index",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "connection_id",
            sa.String(36),
            sa.ForeignKey("connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("table_name", sa.String(255), nullable=False),
        sa.Column("table_schema", sa.String(255), server_default="public"),
        sa.Column("column_count", sa.Integer, server_default="0"),
        sa.Column("row_count", sa.Integer, nullable=True),
        sa.Column("sample_data_json", sa.Text, server_default="[]"),
        sa.Column("ordering_column", sa.String(255), nullable=True),
        sa.Column("latest_record_at", sa.String(100), nullable=True),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true")),
        sa.Column("relevance_score", sa.Integer, server_default="3"),
        sa.Column("business_description", sa.Text, server_default=""),
        sa.Column("data_patterns", sa.Text, server_default=""),
        sa.Column("column_notes_json", sa.Text, server_default="{}"),
        sa.Column("query_hints", sa.Text, server_default=""),
        sa.Column("code_match_status", sa.String(50), server_default="unknown"),
        sa.Column("code_match_details", sa.Text, server_default=""),
        sa.Column("indexed_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
        sa.UniqueConstraint("connection_id", "table_name", name="uq_db_index_conn_table"),
    )

    op.create_table(
        "db_index_summary",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "connection_id",
            sa.String(36),
            sa.ForeignKey("connections.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("total_tables", sa.Integer, server_default="0"),
        sa.Column("active_tables", sa.Integer, server_default="0"),
        sa.Column("empty_tables", sa.Integer, server_default="0"),
        sa.Column("orphan_tables", sa.Integer, server_default="0"),
        sa.Column("phantom_tables", sa.Integer, server_default="0"),
        sa.Column("summary_text", sa.Text, server_default=""),
        sa.Column("recommendations", sa.Text, server_default=""),
        sa.Column("indexed_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("db_index_summary")
    op.drop_table("db_index")
