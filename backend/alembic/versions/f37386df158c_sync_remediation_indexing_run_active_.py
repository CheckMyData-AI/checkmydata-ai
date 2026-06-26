"""sync_remediation_indexing_run_active_index

Idempotent parity migration: ensures `uq_indexing_runs_active_one` exists on
every environment.  Production already has this index from migration
`a1f2b3c4d5e6`; environments that skipped that hotfix (or fresh dev/staging
setups) get it here.

Revision ID: f37386df158c
Revises: 2317bf9d9126
Create Date: 2026-06-26 16:06:16.161424
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f37386df158c"
down_revision: Union[str, None] = "2317bf9d9126"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Partial unique index: at most one active run per (project, kind, connection).
    # coalesce() ensures NULL connection_id rows are also mutually exclusive per project+kind.
    # if_not_exists=True makes this idempotent for envs that already applied a1f2b3c4d5e6.
    op.create_index(
        "uq_indexing_runs_active_one",
        "indexing_runs",
        ["project_id", "kind", sa.text("coalesce(connection_id, '')")],
        unique=True,
        postgresql_where=sa.text("status IN ('queued','running','cancelling')"),
        sqlite_where=sa.text("status IN ('queued','running','cancelling')"),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_indexing_runs_active_one",
        table_name="indexing_runs",
        if_exists=True,
    )
