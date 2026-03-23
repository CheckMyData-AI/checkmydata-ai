"""add default_rule_initialized to projects and is_default to custom_rules

Revision ID: h3i4j5k6l7m8
Revises: g2h3i4j5k6l7
Create Date: 2026-03-17
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "h3i4j5k6l7m8"
down_revision: str | None = "g2h3i4j5k6l7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

naming_convention = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
}


def upgrade() -> None:
    with op.batch_alter_table(
        "projects", naming_convention=naming_convention
    ) as batch_op:
        batch_op.add_column(
            sa.Column(
                "default_rule_initialized",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            )
        )

    with op.batch_alter_table(
        "custom_rules", naming_convention=naming_convention
    ) as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_default",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table(
        "custom_rules", naming_convention=naming_convention
    ) as batch_op:
        batch_op.drop_column("is_default")

    with op.batch_alter_table(
        "projects", naming_convention=naming_convention
    ) as batch_op:
        batch_op.drop_column("default_rule_initialized")
