"""add indexing_checkpoint table for resumable indexing

Revision ID: a3f7c8d912b4
Revises: b2c3d4e5f6a7
Create Date: 2026-03-17
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3f7c8d912b4"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        "indexing_checkpoint",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("workflow_id", sa.String(36), nullable=False),
        sa.Column("head_sha", sa.String(40), nullable=False),
        sa.Column("last_sha", sa.String(40), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("completed_steps", sa.Text(), server_default="[]"),
        sa.Column("changed_files_json", sa.Text(), server_default="[]"),
        sa.Column("deleted_files_json", sa.Text(), server_default="[]"),
        sa.Column("profile_json", sa.Text(), server_default="{}"),
        sa.Column("knowledge_json", sa.Text(), server_default="{}"),
        sa.Column("processed_doc_paths", sa.Text(), server_default="[]"),
        sa.Column("total_docs", sa.Integer(), server_default="0"),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("failed_step", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("indexing_checkpoint")
