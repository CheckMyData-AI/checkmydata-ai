"""Dollar ceilings on plans, and money stops being a float.

Board row 1b + DATA-06.

Every tier sells dollars of LLM credit, and that promise reached the gate only after a
division by a blended $/M rate carrying a 2.2x margin — a margin that is the cost of
the wrong unit rather than caution, because `agent_llm_model` is a field the customer
sets and so the customer picks the price per token. `plans` gains the ceiling in the
unit the tier is actually sold in.

And the three money columns become `Numeric`. This is the precondition rather than a
tidy-up: `estimated_cost_usd` is now SUMMED AS A GATE, and summing thousands of
IEEE-754 doubles is order-dependent — the same month's spend can differ in the last
digits between two calls that see the rows in a different plan order, on the figure
that decides whether to refuse a request.

**No values are seeded here.** `app/ops/plan_catalogue_reconcile.py` owns the ladder
and runs in the FastAPI lifespan; migration `c3d4e5f6a7b8` wrote token ceilings into
`plans` and the reconcile reset them seconds later on every boot — two writers, and
the one that ran last held zeros (DATA-01). This adds the columns and nothing else.

Revision ID: c5d6e7f8a2b3
Revises: b4c5d6e7f8a1
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c5d6e7f8a2b3"
down_revision = "b4c5d6e7f8a1"
branch_labels = None
depends_on = None

#: (table, column, precision, scale) for every money column that was `Float`.
_MONEY_COLUMNS = [
    ("plans", "price_usd_month", 12, 4),
    ("token_usage", "estimated_cost_usd", 12, 6),
    ("request_traces", "estimated_cost_usd", 12, 6),
]


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def upgrade() -> None:
    with op.batch_alter_table("plans") as batch:
        batch.add_column(
            sa.Column(
                "daily_cost_limit_usd",
                sa.Numeric(12, 4),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(
            sa.Column(
                "monthly_cost_limit_usd",
                sa.Numeric(12, 4),
                nullable=False,
                server_default="0",
            )
        )

    if _is_sqlite():
        # SQLite has no fixed-point type: `NUMERIC` is an affinity and a REAL value
        # stays REAL. Altering the column would rewrite the table for no change in
        # behaviour, so the type change is a no-op here and applies where it matters.
        return

    for table, column, precision, scale in _MONEY_COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.Numeric(precision, scale),
            existing_type=sa.Float(),
            postgresql_using=f"{column}::numeric({precision},{scale})",
        )


def downgrade() -> None:
    if not _is_sqlite():
        for table, column, _precision, _scale in _MONEY_COLUMNS:
            op.alter_column(
                table,
                column,
                type_=sa.Float(),
                existing_type=sa.Numeric(),
                postgresql_using=f"{column}::double precision",
            )

    with op.batch_alter_table("plans") as batch:
        batch.drop_column("monthly_cost_limit_usd")
        batch.drop_column("daily_cost_limit_usd")
