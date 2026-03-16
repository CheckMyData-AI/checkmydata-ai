"""add_branch_and_rag_feedback

Revision ID: a7b3e1f20d84
Revises: 9484986f0562
Create Date: 2026-03-16 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7b3e1f20d84'
down_revision: Union[str, None] = '9484986f0562'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('commit_index') as batch_op:
        batch_op.add_column(
            sa.Column('branch', sa.String(255), nullable=False, server_default='main'),
        )

    op.create_table(
        'rag_feedback',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('project_id', sa.String(36), nullable=False),
        sa.Column('chunk_id', sa.String(200), nullable=False),
        sa.Column('source_path', sa.String(512), nullable=False),
        sa.Column('doc_type', sa.String(50), nullable=False, server_default=''),
        sa.Column('distance', sa.Float(), nullable=True),
        sa.Column('query_succeeded', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('question_snippet', sa.Text(), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
    )


def downgrade() -> None:
    op.drop_table('rag_feedback')

    with op.batch_alter_table('commit_index') as batch_op:
        batch_op.drop_column('branch')
