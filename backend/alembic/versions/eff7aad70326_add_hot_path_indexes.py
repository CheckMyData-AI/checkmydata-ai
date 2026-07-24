"""add_hot_path_indexes

Revision ID: eff7aad70326
Revises: f8a9b0c1d2e3
Create Date: 2026-07-24

Composite/covering indexes for hot read paths (qa-audit 09-performance):
- chat_messages(session_id, created_at): every chat request sorts history by
  session_id + created_at.
- agent_learnings(connection_id, is_active, confidence): prompt-compile path.
- notifications(user_id, is_read, created_at): notification feed.
- request_traces(session_id) / request_traces(message_id): FK columns with
  ON DELETE SET NULL that otherwise seq-scan on parent delete.
Additive-only — safe on Postgres (prod) and SQLite (dev) alike.
"""

from alembic import op

revision: str = "eff7aad70326"
down_revision: str | None = "f8a9b0c1d2e3"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_index(
        "ix_chat_messages_session_created", "chat_messages", ["session_id", "created_at"]
    )
    op.create_index(
        "ix_agent_learnings_conn_active_conf",
        "agent_learnings",
        ["connection_id", "is_active", "confidence"],
    )
    op.create_index(
        "ix_notifications_user_read_created",
        "notifications",
        ["user_id", "is_read", "created_at"],
    )
    op.create_index("ix_request_traces_session_id", "request_traces", ["session_id"])
    op.create_index("ix_request_traces_message_id", "request_traces", ["message_id"])


def downgrade() -> None:
    op.drop_index("ix_request_traces_message_id", table_name="request_traces")
    op.drop_index("ix_request_traces_session_id", table_name="request_traces")
    op.drop_index("ix_notifications_user_read_created", table_name="notifications")
    op.drop_index("ix_agent_learnings_conn_active_conf", table_name="agent_learnings")
    op.drop_index("ix_chat_messages_session_created", table_name="chat_messages")
