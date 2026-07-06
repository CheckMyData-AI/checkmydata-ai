"""add deploy_state table + seed embedding fingerprint

Revision ID: d5e6f7a8b9c0
Revises: c9b8a7f6e5d4
Create Date: 2026-07-06

Seeds the embedding fingerprint so the embedding-reconcile flow behaves
correctly on first boot:
- DB already has projects  -> seed the OLD fingerprint, so the first
  reconcile detects a change and reindexes the stale backlog once.
- Fresh install (no rows)  -> seed the CURRENT fingerprint, so no reindex.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d5e6f7a8b9c0"
down_revision = "c9b8a7f6e5d4"
branch_labels = None
depends_on = None

_OLD_FINGERPRINT = "all-MiniLM-L6-v2|256"
_CURRENT_FINGERPRINT = "BAAI/bge-base-en-v1.5|512"


def pick_seed_fingerprint(has_projects: bool) -> str:
    """OLD fingerprint when projects already exist (force one reindex), else CURRENT."""
    return _OLD_FINGERPRINT if has_projects else _CURRENT_FINGERPRINT


def upgrade() -> None:
    op.create_table(
        "deploy_state",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column("value", sa.String(length=255), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    conn = op.get_bind()
    has_projects = conn.execute(sa.text("SELECT 1 FROM projects LIMIT 1")).first() is not None
    # Omit updated_at -> server_default now()/CURRENT_TIMESTAMP fills it (dialect-safe).
    conn.execute(
        sa.text("INSERT INTO deploy_state (key, value) VALUES ('embedding_fingerprint', :v)"),
        {"v": pick_seed_fingerprint(has_projects)},
    )


def downgrade() -> None:
    op.drop_table("deploy_state")
