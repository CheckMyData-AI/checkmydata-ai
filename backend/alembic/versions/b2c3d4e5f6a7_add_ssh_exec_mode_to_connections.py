"""add ssh_exec_mode to connections

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-17
"""

import sqlalchemy as sa

from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    with op.batch_alter_table("connections") as batch_op:
        batch_op.add_column(
            sa.Column("ssh_exec_mode", sa.Boolean(), server_default="0", nullable=False),
        )
        batch_op.add_column(
            sa.Column("ssh_command_template", sa.Text(), nullable=True),
        )
        batch_op.add_column(
            sa.Column("ssh_pre_commands", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    with op.batch_alter_table("connections") as batch_op:
        batch_op.drop_column("ssh_pre_commands")
        batch_op.drop_column("ssh_command_template")
        batch_op.drop_column("ssh_exec_mode")
