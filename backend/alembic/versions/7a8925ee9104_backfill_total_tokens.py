"""backfill token_usage.total_tokens from the parts that were always stored

Revision ID: 7a8925ee9104
Revises: 1d72054cd637
Create Date: 2026-08-31

Every adapter reported `prompt_tokens` and `completion_tokens` and none reported
`total_tokens`; the router read the missing key with a `0` default, so
`record_usage`'s `if total_tokens is None` fallback never ran and a zero was stored.
Measured over the whole table on 2026-08-28:

    rows                    6 479
    sum(prompt_tokens)     53 089 902
    sum(completion_tokens)  4 315 660
    sum(total_tokens)               0

`check_budget` sums exactly that column, so every daily, monthly and plan-derived limit
compared itself against a permanent zero while `BILLING_ENABLED` was on.

**The history is recoverable** — the parts were never lost, only the sum was never
written. This restores it rather than starting the count from today, so the budget gate
takes effect against real usage on the first request after deploy instead of granting
everyone a silent amnesty for the current month.

Only rows where the total is 0 AND at least one part is non-zero are touched: a
genuinely empty usage row (a failed call, an unsinked stream) stays 0 rather than being
invented. The migration is idempotent — a second run matches nothing.
"""

from alembic import op

revision = "7a8925ee9104"
down_revision = "1d72054cd637"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE token_usage
           SET total_tokens = COALESCE(prompt_tokens, 0) + COALESCE(completion_tokens, 0)
         WHERE COALESCE(total_tokens, 0) = 0
           AND COALESCE(prompt_tokens, 0) + COALESCE(completion_tokens, 0) > 0
        """
    )


def downgrade() -> None:
    # Deliberately NOT reversible. Re-zeroing the column would restore the defect, and
    # the rows it would zero are indistinguishable from any correctly-totalled row.
    pass
