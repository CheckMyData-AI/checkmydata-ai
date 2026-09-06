"""plans: the data ceiling the tier copy already promised

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-09-06

`base` has been described as "1 GB index" and `scale` as "2 GB index per project" since the
2026-08-31 catalogue transition, while `plans` had no column to hold either figure. A
promise with no meter is not a tier boundary — it is copy.

**This migration adds the column and seeds nothing.** The tier values live in
`app/services/plan_catalogue.py` and reach the database through
`app/ops/plan_catalogue_reconcile.py` at boot, the same self-completing shape the
embedding and encryption reconciles use. Seeding a price list inside a migration freezes
it at this revision: the code would say $900 and the row a customer resolves against would
still say $199, with nothing comparing the two.

0 means unlimited, as it does in every other numeric column on this table.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "plans",
        sa.Column(
            "max_index_bytes",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("plans", "max_index_bytes")
