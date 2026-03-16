"""add google oauth fields to users

Revision ID: f4e7a1c23b90
Revises: d8a2f4b19c73
Create Date: 2026-03-16
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "f4e7a1c23b90"
down_revision: Union[str, None] = "d8a2f4b19c73"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("password_hash", existing_type=sa.String(255), nullable=True)
        batch_op.add_column(sa.Column("auth_provider", sa.String(20), nullable=False, server_default="email"))
        batch_op.add_column(sa.Column("google_id", sa.String(255), nullable=True))
        batch_op.create_unique_constraint("uq_users_google_id", ["google_id"])


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("uq_users_google_id", type_="unique")
        batch_op.drop_column("google_id")
        batch_op.drop_column("auth_provider")
        batch_op.alter_column("password_hash", existing_type=sa.String(255), nullable=False)
