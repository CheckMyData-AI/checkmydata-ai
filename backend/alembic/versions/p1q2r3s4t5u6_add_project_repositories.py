"""add project_repositories table

Revision ID: p1q2r3s4t5u6
Revises: o0p1q2r3s4t5
Create Date: 2026-03-18

"""

import sqlalchemy as sa

from alembic import op

revision = "p1q2r3s4t5u6"
down_revision = "o0p1q2r3s4t5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_repositories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False, server_default="git_ssh"),
        sa.Column("repo_url", sa.String(512), nullable=False),
        sa.Column("branch", sa.String(255), nullable=False, server_default="main"),
        sa.Column(
            "ssh_key_id",
            sa.String(36),
            sa.ForeignKey("ssh_keys.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("auth_token_encrypted", sa.Text, nullable=True),
        sa.Column("indexing_status", sa.String(20), nullable=False, server_default="idle"),
        sa.Column("last_indexed_commit", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("project_repositories")
