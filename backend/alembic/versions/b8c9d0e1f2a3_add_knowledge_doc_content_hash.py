"""add knowledge_docs.content_hash

Lets `generate_docs` tell that a document's INPUTS have not changed and skip the LLM
call. Measured motivation: a full rebuild of the one real project spends ~9 375 s of its
12 039 s generating 758 documents, 535 of which describe migrations that are never edited
after they are merged — and a full rebuild is enqueued by every extractor-schema bump.

Hand-written, one operation. `--autogenerate` against a dev database produces 252
operations here (CONVENTIONS §1).

NULL on existing rows is correct and is not backfilled: it means "generated before the
cache existed", which is unknown rather than unchanged. Deriving a hash from the stored
document would assert that it matches inputs nobody compared. The first run after deploy
regenerates and records; the one after that is the cheap one.

Revision ID: b8c9d0e1f2a3
Revises: f6a7b8c9d0e1
Create Date: 2026-09-09
"""

import sqlalchemy as sa
from alembic import op

revision = "b8c9d0e1f2a3"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("knowledge_docs", sa.Column("content_hash", sa.String(length=80), nullable=True))


def downgrade() -> None:
    # Only for a clean environment. Dropping this on production discards every cache
    # entry, and the next rebuild pays the full 9 375 s again to rediscover them.
    op.drop_column("knowledge_docs", "content_hash")
