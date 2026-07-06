"""add column_mismatch_json to code_db_sync

Revision ID: c9b8a7f6e5d4
Revises: 0e5084fdfb86
Create Date: 2026-07-06 00:00:00.000000

Adds a Text column `column_mismatch_json` to `code_db_sync` that stores the
deterministic set-diff result (code_only / db_only / matched column lists)
computed by SYNC-L5 / T4.  Existing rows get a server_default of `{}` so the
migration is non-destructive and PostgreSQL-safe (server_default backfills all
existing rows at ALTER TABLE time without a separate UPDATE pass).
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c9b8a7f6e5d4"
down_revision = "0e5084fdfb86"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "code_db_sync",
        sa.Column(
            "column_mismatch_json",
            sa.Text(),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("code_db_sync", "column_mismatch_json")
