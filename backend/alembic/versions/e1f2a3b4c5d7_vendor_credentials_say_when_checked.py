"""A vendor credential records when it was last checked, and what was said (PRJ-10).

A key is pasted once and used by a background job every night, so a revocation shows up
as a report that stopped arriving — days later, in a log nobody reads. `POST
/api/vendor-credentials/{id}/verify` asks the vendor now; these two columns are where
the answer is kept.

Two columns rather than one: `last_verify_error` is NULL exactly when the attempt at
`last_verified_at` succeeded, so "checked and refused" cannot be read as "never
checked". A transient failure writes neither — an unreachable vendor is no evidence
about a key.

Revision ID: e1f2a3b4c5d7
Revises: 4030521071d4
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e1f2a3b4c5d7"
down_revision = "4030521071d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "vendor_credentials",
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "vendor_credentials",
        sa.Column("last_verify_error", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("vendor_credentials", "last_verify_error")
    op.drop_column("vendor_credentials", "last_verified_at")
