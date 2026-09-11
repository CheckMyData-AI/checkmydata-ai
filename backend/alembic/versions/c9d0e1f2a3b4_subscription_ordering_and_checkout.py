"""Two columns a webhook needs to be safe: an ordering watermark and a checkout marker.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-09-11

**`last_event_created`** (BILL-04). Stripe does not guarantee delivery order, and
`_sync_subscription` wrote whatever the payload said. Its `deleted` branch is a full
teardown — status `canceled`, spending key revoked — so an `updated` delivered after it
resurrected a cancelled account and minted it a fresh key. The column stores Stripe's own
`created` for the last event applied; anything older is dropped. `NULL` means no event has
been applied under the rule yet and is never treated as stale: an unknown must not become a
refusal to write.

**`checkout_pending_at`** (BILL-05). The duplicate-subscription guard read
`stripe_subscription_id`, which stays NULL until a webhook lands minutes after Checkout is
created — so it could not see a checkout in flight, which is exactly the window its own
comment says it exists to close ("before the money moves"). Two clicks inside that window
both passed and the account ended up with two Stripe subscriptions.

Both are nullable with no backfill, deliberately: there is nothing true to write for rows
that predate the rules, and inventing a watermark would silently drop the next legitimate
event.
"""

import sqlalchemy as sa
from alembic import op

revision = "c9d0e1f2a3b4"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("subscriptions", sa.Column("last_event_created", sa.BigInteger(), nullable=True))
    op.add_column(
        "subscriptions",
        sa.Column("checkout_pending_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("subscriptions", "checkout_pending_at")
    op.drop_column("subscriptions", "last_event_created")
