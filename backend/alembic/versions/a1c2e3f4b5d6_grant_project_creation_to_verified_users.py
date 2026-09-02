"""Grant project creation to users whose address is already verified.

Revision ID: a1c2e3f4b5d6
Revises: b48fcfc1524b
Create Date: 2026-09-02

``users.can_create_projects`` defaults to False and, until this release, nothing
anywhere set it True — the only endpoint calling itself a grant
(``POST /api/projects/access-requests``) sends an email and returns ok. So every account
ever created is False, including the ones whose email is verified and who have been
using the product.

The grant now happens at verification, but that fires once and has already passed for
everyone here. This backfill closes exactly that gap: verified address → the right,
which is the same rule the new code applies.

It cannot resurrect a deliberate revocation, because there has never been one to
resurrect: no code path could set the column True, so a False on a verified user means
"never granted", not "taken away". That reasoning is what makes the blanket UPDATE safe,
and it stops being true the moment an admin revokes someone — which is why this is a
one-off backfill and not a recurring reconcile.

Unverified users are left alone: verifying is what grants them the right, and doing it
for them here would hand it to an address nobody has proven.
"""

from alembic import op

revision = "a1c2e3f4b5d6"
down_revision = "b48fcfc1524b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE users SET can_create_projects = true "
        "WHERE email_verified = true AND can_create_projects = false"
    )


def downgrade() -> None:
    # Deliberately empty. The rows this touched are indistinguishable afterwards from
    # rows granted by verification, so a revert would have to guess which users to
    # strip the right from — and guessing wrong locks a paying customer out of their
    # own workspace. Reverting the CODE restores the old behaviour for new signups;
    # existing grants stay, which is the safe direction.
    pass
