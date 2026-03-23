"""add user_id to ssh_keys

Revision ID: d4f015eb8a1c
Revises: c7d2e8f31a45
Create Date: 2026-03-17
"""

import sqlalchemy as sa

from alembic import op

revision: str = "d4f015eb8a1c"
down_revision: str | None = "c7d2e8f31a45"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    with op.batch_alter_table("ssh_keys") as batch_op:
        batch_op.add_column(
            sa.Column("user_id", sa.String(36), nullable=True),
        )
        batch_op.create_index("ix_ssh_keys_user_id", ["user_id"])
        batch_op.create_foreign_key(
            "fk_ssh_keys_user_id", "users", ["user_id"], ["id"], ondelete="CASCADE",
        )


def downgrade() -> None:
    with op.batch_alter_table("ssh_keys") as batch_op:
        batch_op.drop_constraint("fk_ssh_keys_user_id", type_="foreignkey")
        batch_op.drop_index("ix_ssh_keys_user_id")
        batch_op.drop_column("user_id")
