"""add column_distinct_values_json to db_index

Revision ID: m8n9o0p1q2r3
Revises: k6l7m8n9o0p1
Create Date: 2026-03-17

"""

import sqlalchemy as sa

from alembic import op

revision = "m8n9o0p1q2r3"
down_revision = "k6l7m8n9o0p1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "db_index",
        sa.Column("column_distinct_values_json", sa.Text(), nullable=True, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("db_index", "column_distinct_values_json")
