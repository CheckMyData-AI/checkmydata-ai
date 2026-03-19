"""add_saved_notes_table

Revision ID: s4t5u6v7w8x9
Revises: 5f9fe870b98c
Create Date: 2026-03-19 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 's4t5u6v7w8x9'
down_revision: Union[str, None] = '5f9fe870b98c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'saved_notes',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('project_id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('connection_id', sa.String(length=36), nullable=True),
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('sql_query', sa.Text(), nullable=False),
        sa.Column('last_result_json', sa.Text(), nullable=True),
        sa.Column('last_executed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['connection_id'], ['connections.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('saved_notes', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_saved_notes_project_id'), ['project_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_saved_notes_user_id'), ['user_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('saved_notes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_saved_notes_user_id'))
        batch_op.drop_index(batch_op.f('ix_saved_notes_project_id'))

    op.drop_table('saved_notes')
