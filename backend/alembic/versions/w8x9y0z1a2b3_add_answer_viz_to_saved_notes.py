"""add_answer_text_and_visualization_json_to_saved_notes

Revision ID: w8x9y0z1a2b3
Revises: v7w8x9y0z1a2
Create Date: 2026-03-19 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "w8x9y0z1a2b3"
down_revision: Union[str, None] = "v7w8x9y0z1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("saved_notes", schema=None) as batch_op:
        batch_op.add_column(sa.Column("answer_text", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("visualization_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("saved_notes", schema=None) as batch_op:
        batch_op.drop_column("visualization_json")
        batch_op.drop_column("answer_text")
