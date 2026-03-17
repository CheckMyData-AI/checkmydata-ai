"""add cascade delete to project foreign keys

Revision ID: c7d2e8f31a45
Revises: a3f7c8d912b4
Create Date: 2026-03-17
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'c7d2e8f31a45'
down_revision: Union[str, None] = 'a3f7c8d912b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FK_UPDATES = [
    ("knowledge_docs", "knowledge_docs_project_id_fkey", "project_id", "projects", "id"),
    ("commit_index", "commit_index_project_id_fkey", "project_id", "projects", "id"),
    ("connections", "connections_project_id_fkey", "project_id", "projects", "id"),
    ("chat_sessions", "chat_sessions_project_id_fkey", "project_id", "projects", "id"),
    ("project_cache", "project_cache_project_id_fkey", "project_id", "projects", "id"),
    ("rag_feedback", "rag_feedback_project_id_fkey", "project_id", "projects", "id"),
    ("chat_messages", "chat_messages_session_id_fkey", "session_id", "chat_sessions", "id"),
]

_NAMING = {"fk": "%(table_name)s_%(column_0_name)s_fkey"}


def upgrade() -> None:
    for table, constraint, local_col, ref_table, ref_col in FK_UPDATES:
        with op.batch_alter_table(table, naming_convention=_NAMING) as batch_op:
            batch_op.drop_constraint(constraint, type_="foreignkey")
            batch_op.create_foreign_key(
                constraint, ref_table,
                [local_col], [ref_col],
                ondelete="CASCADE",
            )


def downgrade() -> None:
    for table, constraint, local_col, ref_table, ref_col in FK_UPDATES:
        with op.batch_alter_table(table, naming_convention=_NAMING) as batch_op:
            batch_op.drop_constraint(constraint, type_="foreignkey")
            batch_op.create_foreign_key(
                constraint, ref_table,
                [local_col], [ref_col],
            )
