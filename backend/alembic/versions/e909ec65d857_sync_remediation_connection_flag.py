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
            server_default=sa.text("1"),
        ),
    )


def downgrade() -> None:
    with op.batch_alter_table("connections") as batch_op:
        batch_op.drop_column("send_sample_data_to_llm")
