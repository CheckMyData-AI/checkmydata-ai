"""add_project_cache_and_rag_commit_sha

Revision ID: b3c8f2a71e56
Revises: a7b3e1f20d84
Create Date: 2026-03-16 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3c8f2a71e56'
down_revision: Union[str, None] = 'a7b3e1f20d84'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'project_cache',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('project_id', sa.String(36), nullable=False, unique=True),
        sa.Column('knowledge_json', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('profile_json', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
    )

    with op.batch_alter_table('rag_feedback') as batch_op:
        batch_op.add_column(
            sa.Column('commit_sha', sa.String(40), nullable=True),
        )


def downgrade() -> None:
    with op.batch_alter_table('rag_feedback') as batch_op:
        batch_op.drop_column('commit_sha')

    op.drop_table('project_cache')
