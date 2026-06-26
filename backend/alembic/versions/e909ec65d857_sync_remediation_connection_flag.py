"""sync_remediation_connection_flag

Revision ID: e909ec65d857
Revises: f37386df158c
Create Date: 2026-06-26 16:34:53.464295
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e909ec65d857"
down_revision: Union[str, None] = "f37386df158c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "connections",
        sa.Column(
            "send_sample_data_to_llm",
            sa.Boolean(),
            nullable=False,
            # Cross-dialect boolean default: sa.true() compiles to `true` on
            # PostgreSQL and `1` on SQLite. A literal sa.text("1") is rejected by
            # Postgres ("column is of type boolean but default expression is of
            # type integer") and crashed the v185 web boot.
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    with op.batch_alter_table("connections") as batch_op:
        batch_op.drop_column("send_sample_data_to_llm")
