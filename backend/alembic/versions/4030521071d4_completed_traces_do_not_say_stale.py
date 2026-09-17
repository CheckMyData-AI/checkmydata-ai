"""A completed trace does not say it went stale (PRJ-04 follow-up).

``d6e7f8a9b0c1`` removed the ``Stale: pipeline_end never received`` note from a
completed run while MERGING duplicates. Production, re-read after it shipped on v434:
**one** completed row still carried the note — a single row, never duplicated, where
an older ``finalize_trace`` marked the run completed without clearing what the
eviction had written. The writers no longer do that; this clears the one that exists.

Revision ID: 4030521071d4
Revises: d6e7f8a9b0c1
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "4030521071d4"
down_revision = "d6e7f8a9b0c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    traces = sa.table("request_traces", sa.column("status"), sa.column("error_message"))
    op.get_bind().execute(
        sa.update(traces)
        .where(traces.c.status == "completed")
        .where(traces.c.error_message.like("Stale:%"))
        .values(error_message=None)
    )


def downgrade() -> None:
    # The removed note described a death that did not happen; there is nothing to restore.
    pass
