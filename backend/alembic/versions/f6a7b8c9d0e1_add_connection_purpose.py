"""connections: what the owner says this source is for

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-09-08

A schema says a column is called `status` and holds integers. It cannot say that only
`settled` rows count as revenue, that money is in minor units, or that a table is a
legacy mirror nobody writes to any more. Somebody knows that, and there was nowhere to
put it — so the agent inferred, and inference is where the wrong answers came from.

Free text, by decision D3 of 2026-09-07: one field, nothing about it validated beyond
its length, which is the accepted cost of shipping it rather than a structured form.

Nullable with no default and no backfill. An undescribed source is the normal case and
must stay distinguishable from one described as empty — `purposes_to_context` renders
nothing at all for either, and an empty string written everywhere would have made the
column useless as a signal for the interface's "No purpose set" state.

`SCN-134`.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("connections", sa.Column("purpose", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("connections", "purpose")
