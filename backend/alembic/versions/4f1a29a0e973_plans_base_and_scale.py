"""plans: base and scale, replacing free/pro/team

Revision ID: 4f1a29a0e973
Revises: 451d6ca545f5
Create Date: 2026-08-31

The old catalogue priced token allowances that cost more than the tier: Pro at $49
included 15M tokens worth ~$61, Team at $199 included 75M worth ~$306. Measured
2026-08-31; invisible until then because `estimate_cost` returned None for every model in
production, so `estimated_cost_usd` was 0.00 on all 6 771 rows.

The new catalogue prices what actually costs money. Measured on the one real project:
295 MB of index for a 9 981-file repository, 91.7 worker-hours in August, and 33.9 of
those hours spent re-indexing the schemas of **three** connections — which is why data
sources are a tier axis and not a free extra.

Token credit is a pass-through at cost, quoted in dollars rather than tokens because there
is no markup to hide in a token rate.

**Existing rows are not deleted.** A subscription may still point at `pro`; dropping the
row it references would strand it. They are deactivated so nothing new can be bought and
`EntitlementService` keeps resolving what is already sold.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "4f1a29a0e973"
down_revision = "451d6ca545f5"
branch_labels = None
depends_on = None


_PLANS = sa.table(
    "plans",
    sa.column("id", sa.String),
    sa.column("name", sa.String),
    sa.column("description", sa.Text),
    sa.column("price_usd_month", sa.Integer),
    sa.column("daily_token_limit", sa.Integer),
    sa.column("monthly_token_limit", sa.Integer),
    sa.column("max_connections", sa.Integer),
    sa.column("max_projects", sa.Integer),
    sa.column("seats", sa.Integer),
    sa.column("trial_days", sa.Integer),
    sa.column("is_active", sa.Boolean),
    sa.column("sort_order", sa.Integer),
)

#: Token ceilings are 0 = unlimited, deliberately. The spend limit lives on the account's
#: OpenRouter key, where it is a dollar balance rather than a token count — one home per
#: fact, and the key is the only place that can enforce it mid-request.
_NEW = [
    {
        "id": "base",
        "name": "Base",
        "description": (
            "AI data analyst for your own databases and codebase. "
            "1 project, 5 data sources, 1 GB index, $30/month of LLM credit at cost."
        ),
        "price_usd_month": 199,
        "daily_token_limit": 0,
        "monthly_token_limit": 0,
        "max_connections": 5,
        "max_projects": 1,
        "seats": 5,
        "trial_days": 14,
        "is_active": True,
        "sort_order": 10,
    },
    {
        "id": "scale",
        "name": "Scale",
        "description": (
            "3 projects, 15 data sources, 2 GB index per project, $90/month of LLM credit at cost."
        ),
        "price_usd_month": 599,
        "daily_token_limit": 0,
        "monthly_token_limit": 0,
        "max_connections": 15,
        "max_projects": 3,
        "seats": 20,
        "trial_days": 14,
        "is_active": True,
        "sort_order": 20,
    },
]


def upgrade() -> None:
    conn = op.get_bind()
    existing = {r[0] for r in conn.execute(sa.text("SELECT id FROM plans"))}

    for plan in _NEW:
        if plan["id"] in existing:
            op.execute(
                _PLANS.update()
                .where(_PLANS.c.id == op.inline_literal(plan["id"]))
                .values(**{k: v for k, v in plan.items() if k != "id"})
            )
        else:
            op.bulk_insert(_PLANS, [plan])

    # Deactivated, not deleted: a live subscription may still reference one, and removing
    # the row would strand it with no plan to resolve.
    op.execute(
        sa.text("UPDATE plans SET is_active = :off WHERE id IN ('free', 'pro', 'team')").bindparams(
            off=False
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text("UPDATE plans SET is_active = :on WHERE id IN ('free', 'pro', 'team')").bindparams(
            on=True
        )
    )
    op.execute(
        sa.text("UPDATE plans SET is_active = :off WHERE id IN ('base', 'scale')").bindparams(
            off=False
        )
    )
