"""add can_create_projects to users

Revision ID: c6d7e8f9g0h1
Revises: b4c5d6e7f8g9
Create Date: 2026-03-29
"""

import sqlalchemy as sa

from alembic import op

revision = "c6d7e8f9g0h1"
down_revision = "b4c5d6e7f8g9"
branch_labels = None
depends_on = None

_ADMIN_EMAILS = ("sergeysheleg4@gmail.com", "sergey@appvillis.com")


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("can_create_projects", sa.Boolean(), server_default="0", nullable=False),
        )

    users = sa.table(
        "users",
        sa.column("email", sa.String),
        sa.column("can_create_projects", sa.Boolean),
    )
    op.execute(
        users.update()
        .where(users.c.email.in_(_ADMIN_EMAILS))
        .values(can_create_projects=True)
    )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("can_create_projects")
