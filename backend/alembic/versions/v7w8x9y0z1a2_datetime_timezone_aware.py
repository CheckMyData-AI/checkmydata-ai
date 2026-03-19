"""make all datetime columns timezone-aware

Revision ID: v7w8x9y0z1a2
Revises: r3s4t5u6v7w8, j5k6l7m8n9o0
Create Date: 2026-03-19

"""

from alembic import op
import sqlalchemy as sa

revision = "v7w8x9y0z1a2"
down_revision = ("r3s4t5u6v7w8", "j5k6l7m8n9o0")
branch_labels = None
depends_on = None

_COLUMNS = [
    ("users", ["created_at"]),
    ("projects", ["created_at", "updated_at"]),
    ("connections", ["created_at", "updated_at"]),
    ("ssh_keys", ["created_at", "updated_at"]),
    ("chat_sessions", ["created_at"]),
    ("chat_messages", ["created_at"]),
    ("knowledge_docs", ["created_at", "updated_at"]),
    ("agent_learnings", ["created_at", "updated_at"]),
    ("agent_learning_summaries", ["last_compiled_at"]),
    ("db_index", ["indexed_at", "created_at", "updated_at"]),
    ("db_index_summary", ["indexed_at", "created_at", "updated_at"]),
    ("code_db_sync", ["synced_at", "created_at", "updated_at"]),
    ("code_db_sync_summary", ["synced_at", "created_at", "updated_at"]),
    ("saved_notes", ["last_executed_at", "created_at", "updated_at"]),
    ("indexing_checkpoint", ["created_at", "updated_at"]),
    ("project_members", ["created_at"]),
    ("project_invites", ["created_at", "accepted_at"]),
    ("custom_rules", ["created_at", "updated_at"]),
    ("project_cache", ["created_at", "updated_at"]),
    ("project_repositories", ["created_at", "updated_at"]),
    ("rag_feedback", ["created_at"]),
    ("commit_index", ["created_at"]),
]


def upgrade() -> None:
    conn = op.get_bind()
    is_pg = conn.dialect.name == "postgresql"

    for table, columns in _COLUMNS:
        if not _table_exists(conn, table):
            continue
        for col in columns:
            if is_pg:
                op.execute(
                    f'ALTER TABLE "{table}" '
                    f'ALTER COLUMN "{col}" TYPE TIMESTAMP WITH TIME ZONE '
                    f'USING "{col}" AT TIME ZONE \'UTC\''
                )
            else:
                with op.batch_alter_table(table) as batch_op:
                    batch_op.alter_column(
                        col,
                        type_=sa.DateTime(timezone=True),
                        existing_type=sa.DateTime(),
                    )


def downgrade() -> None:
    conn = op.get_bind()
    is_pg = conn.dialect.name == "postgresql"

    for table, columns in _COLUMNS:
        if not _table_exists(conn, table):
            continue
        for col in columns:
            if is_pg:
                op.execute(
                    f'ALTER TABLE "{table}" '
                    f'ALTER COLUMN "{col}" TYPE TIMESTAMP WITHOUT TIME ZONE'
                )
            else:
                with op.batch_alter_table(table) as batch_op:
                    batch_op.alter_column(
                        col,
                        type_=sa.DateTime(),
                        existing_type=sa.DateTime(timezone=True),
                    )


def _table_exists(conn, table_name: str) -> bool:
    insp = sa.inspect(conn)
    return table_name in insp.get_table_names()
