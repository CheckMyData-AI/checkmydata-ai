"""project_invites.expires_at — invitations stop being acceptable (F-PROJ-04)

An invite stayed ``pending`` indefinitely, so `auto_accept_for_user` accepted it
whenever that address eventually registered — years later, after the person had left.
Email verification (F-PROJ-01) does not cover this: a re-registered address verifies
perfectly well, because verification proves control of the mailbox today, not that the
invitation was meant for whoever controls it now.

Nullable, and deliberately not backfilled. `invite_expires_at` reads NULL as
``created_at + invite_expiry_days``, so the policy applies to the real creation time of
every row that predates this column — which is precisely the set of stale invites the
finding is about. A backfill would have to invent a value; the fallback does not.

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-08-20
"""

import sqlalchemy as sa

from alembic import op

revision = "c2d3e4f5a6b7"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "project_invites",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("project_invites", "expires_at")
