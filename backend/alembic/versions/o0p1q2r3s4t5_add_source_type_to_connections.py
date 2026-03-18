"""add source_type to connections

Revision ID: o0p1q2r3s4t5
Revises: n9o0p1q2r3s4
Create Date: 2026-03-18

"""

from alembic import op
import sqlalchemy as sa

revision = "o0p1q2r3s4t5"
down_revision = "n9o0p1q2r3s4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "connections",
        sa.Column("source_type", sa.String(50), nullable=False, server_default="database"),
    )


def downgrade() -> None:
    op.drop_column("connections", "source_type")
