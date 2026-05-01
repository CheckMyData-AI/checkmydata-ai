"""add append-only checkpoint step + doc tables (T22)

Revision ID: b6c7d8e9f0a1
Revises: a5b6c7d8e9f0
Create Date: 2026-04-30
"""

import sqlalchemy as sa

from alembic import op

revision: str = "b6c7d8e9f0a1"
down_revision: str | None = "a5b6c7d8e9f0"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "indexing_checkpoint_step",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "checkpoint_id",
            sa.String(36),
            sa.ForeignKey("indexing_checkpoint.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("step_name", sa.String(64), nullable=False),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "checkpoint_id", "step_name", name="uq_indexing_checkpoint_step"
        ),
    )
    op.create_index(
        "ix_indexing_checkpoint_step_cp",
        "indexing_checkpoint_step",
        ["checkpoint_id"],
    )

    op.create_table(
        "indexing_checkpoint_doc",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "checkpoint_id",
            sa.String(36),
            sa.ForeignKey("indexing_checkpoint.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_path", sa.String(512), nullable=False),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "checkpoint_id", "source_path", name="uq_indexing_checkpoint_doc"
        ),
    )
    op.create_index(
        "ix_indexing_checkpoint_doc_cp",
        "indexing_checkpoint_doc",
        ["checkpoint_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_indexing_checkpoint_doc_cp", table_name="indexing_checkpoint_doc")
    op.drop_table("indexing_checkpoint_doc")
    op.drop_index(
        "ix_indexing_checkpoint_step_cp", table_name="indexing_checkpoint_step"
    )
    op.drop_table("indexing_checkpoint_step")
