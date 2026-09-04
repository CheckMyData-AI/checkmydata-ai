"""add plan_json to request_traces

The plan a request executed lived only in ``pipeline_runs.plan_json``, and
``_cleanup_pipeline_runs()`` deletes those rows at start-up once they pass
``pipeline_run_ttl_days`` (7). Measured 2026-09-03: the table held **zero** rows,
and the deploy of v321 had swept the last four between two probes half an hour
apart.

The plan is part of what happened, not part of what can be resumed, so it belongs
beside the trace — which ``cleanup_old_traces`` keeps for 90 days. The buffer's
TTL is deliberately left at 7: one number serving both roles would make a
pipeline three months stale resumable.

Nullable, because Path B takes 14% of requests and a NOT NULL column would make
the other 86% store ``{}`` — which reads as "an empty plan ran".

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("request_traces", sa.Column("plan_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("request_traces", "plan_json")
