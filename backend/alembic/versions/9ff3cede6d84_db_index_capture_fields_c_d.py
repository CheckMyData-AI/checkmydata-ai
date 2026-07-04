"""db_index capture fields (C-D)

Revision ID: 9ff3cede6d84
Revises: 760604aa1803
Create Date: 2026-07-04 13:56:17.610118
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '9ff3cede6d84'
down_revision: Union[str, None] = '760604aa1803'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("db_index", sa.Column("enum_labels_json", sa.Text(), server_default="{}", nullable=False))
    op.add_column("db_index", sa.Column("check_constraints_json", sa.Text(), server_default="{}", nullable=False))
    op.add_column("db_index", sa.Column("sort_keys_json", sa.Text(), server_default="[]", nullable=False))
    op.add_column("db_index", sa.Column("column_stats_json", sa.Text(), server_default="{}", nullable=False))
    op.add_column("db_index", sa.Column("object_kind", sa.String(length=20), server_default="table", nullable=False))


def downgrade() -> None:
    op.drop_column("db_index", "object_kind")
    op.drop_column("db_index", "column_stats_json")
    op.drop_column("db_index", "sort_keys_json")
    op.drop_column("db_index", "check_constraints_json")
    op.drop_column("db_index", "enum_labels_json")
