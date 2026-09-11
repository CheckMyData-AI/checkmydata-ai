"""A checkpoint that remembers whether it came from a full rebuild.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-09-11

KNOW-08. `_run_index_background` reused whatever `IndexingCheckpoint` it found whenever
`force_full` was false, with nothing recording how that checkpoint was produced. A
checkpoint left by an interrupted full rebuild carries `last_sha = None` and the entire blob
list as `changed_files`, so the resume reads "everything changed" and redoes the full
rebuild — measured at 5 600–12 300 s on the one production repository — under the nightly
sync's 7 200 s ceiling, while reporting itself as incremental.

Nullable with no backfill, and the NULL is load-bearing: a checkpoint written before this
column existed is *unknown*, and the resume treats unknown as full. Defaulting it to `false`
would assert the one thing that cannot be known and reintroduce the defect for every row
that predates the fix.
"""

import sqlalchemy as sa
from alembic import op

revision = "d0e1f2a3b4c5"
down_revision = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("indexing_checkpoint", sa.Column("force_full", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("indexing_checkpoint", "force_full")
