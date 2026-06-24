"""add token_version to users (JWT revocation)

Revision ID: f4a5b6c7d8e9
Revises: f2a3b4c5d6e7
Create Date: 2026-06-24

"""

import sqlalchemy as sa
from alembic import op

revision = "f4a5b6c7d8e9"
down_revision = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("users", "token_version")
