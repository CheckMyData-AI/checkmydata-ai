"""add max_orchestrator_steps to projects

Revision ID: b4c5d6e7f8g9
Revises: a3f7c8d912b4
Create Date: 2026-03-28
"""

import sqlalchemy as sa

from alembic import op

revision: str = "b4c5d6e7f8g9"
down_revision = ("a3f7c8d912b4", "f1b2c3d4e5f6")
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch_op:
        batch_op.add_column(
            sa.Column("max_orchestrator_steps", sa.Integer(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch_op:
        batch_op.drop_column("max_orchestrator_steps")
