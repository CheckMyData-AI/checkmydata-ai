"""sync_remediation_schema_qualified_uniqueness

Revision ID: 2317bf9d9126
Revises: a7c8d9e0f1a2
Create Date: 2026-06-26 15:52:54.795013
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '2317bf9d9126'
down_revision: Union[str, None] = 'a7c8d9e0f1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("db_index") as b:
        b.drop_constraint("uq_db_index_conn_table", type_="unique")
        b.create_unique_constraint(
            "uq_db_index_conn_schema_table",
            ["connection_id", "table_schema", "table_name"],
        )


def downgrade() -> None:
    with op.batch_alter_table("db_index") as b:
        b.drop_constraint("uq_db_index_conn_schema_table", type_="unique")
        b.create_unique_constraint(
            "uq_db_index_conn_table",
            ["connection_id", "table_name"],
        )
