"""add failed_doc_paths_json to project_cache

Tracks repo-relative paths whose LLM doc generation failed under the
failure-ratio threshold so they can be re-queued on the next index run
instead of leaving permanent knowledge-base holes.

Revision ID: 68aa15e554e2
Revises: f0a1b2c3d4e5
Create Date: 2026-06-03
"""

import sqlalchemy as sa

from alembic import op

revision = "68aa15e554e2"
down_revision = "f0a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "project_cache",
        sa.Column("failed_doc_paths_json", sa.Text(), server_default="[]", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("project_cache", "failed_doc_paths_json")
