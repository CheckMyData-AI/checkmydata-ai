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

from alembic import op

revision: str = "f37386df158c"
down_revision: Union[str, None] = "2317bf9d9126"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NO-OP: the index `uq_indexing_runs_active_one` is authoritatively created
    # by migration `a1f2b3c4d5e6_add_indexing_runs_and_error_log.py`.
    # The `__table_args__` entry in `app/models/indexing_run.py` provides
    # `create_all` parity for tests and fresh dev setups.
    # Performing create_index here would cause a double-drop on `downgrade base`.
    pass


def downgrade() -> None:
    # NO-OP: index owned by a1f2b3c4d5e6; dropping it here would cause
    # a double-drop when a1f2b3c4d5e6 also runs its downgrade.
    pass
