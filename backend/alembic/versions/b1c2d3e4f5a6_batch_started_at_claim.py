"""batch_queries.started_at — the run claim for F-SCHED-07

`execute_batch` set ``status = "running"`` without consulting the current status, and
`run_batch` inherits ARQ's default retry count, so a retried job re-executed every
query in the batch and overwrote ``results_json``. The claim that stops that has to be
stale-aware, because nothing resets a stuck ``running`` batch — the stale-run reaper
covers ``indexing_runs`` and has no knowledge of ``batch_queries`` — and "stale" needs a
start time. ``created_at`` cannot serve: a batch may sit ``pending`` for a long time, so
its creation time says nothing about whether an attempt is alive.

Nullable on purpose. Rows written before this column existed read as NULL, and
``_claim_batch`` treats NULL as claimable rather than stuck forever.

Revision ID: b1c2d3e4f5a6
Revises: a7b8c9d0e1f2
Create Date: 2026-08-20
"""

import sqlalchemy as sa

from alembic import op

revision = "b1c2d3e4f5a6"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "batch_queries",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("batch_queries", "started_at")
