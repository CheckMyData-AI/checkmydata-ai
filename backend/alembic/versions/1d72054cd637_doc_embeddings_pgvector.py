"""doc_embeddings: move the vector store off local disk and into Postgres

Revision ID: 1d72054cd637
Revises: 6287a47828ca
Create Date: 2026-08-28

Why this table exists is in ``app/models/doc_embedding.py``. The short version:
ChromaDB persisted to the dyno's container filesystem, which is wiped on every
restart and is not shared between the ``web`` and ``worker`` process types. An empty
store makes the pipeline force a full re-index, a full re-index of the one real
customer repository costs 12 039 s, and the nightly job's ceiling is 7 200 s — so
16 of 94 repo-index runs ever completed and the store was empty again by morning.

**Postgres only, deliberately.** Development and the test suite run on SQLite
(``backend/data/agent.db``), where there is no ``vector`` extension and no HNSW.
``make setup`` runs ``alembic upgrade head`` against that SQLite file, so a migration
that assumed Postgres would break every developer's first command. On SQLite this
migration is a no-op and the ChromaDB backend stays in use; ``VECTOR_STORE_BACKEND``
selects between them.

Measured before choosing HNSW over IVFFlat, on this exact schema with 30 000 rows of
384 dimensions: build 20 s, and a top-5 filtered by ``project_id`` goes from 4 738 ms
with no vector index to 0.92 ms with one. HNSW also needs no training pass, so it is
correct from an empty table — IVFFlat built on an empty table returns nothing until
it is rebuilt, which is exactly the failure mode this whole table exists to remove.

pgvector is available on both deployments: 0.8.1 on Heroku Postgres, 0.8.2 on
Supabase. Checked 2026-08-28 — this migration is therefore safe to run before any
database move, which is why the vector fix does not have to wait for one.
"""

from alembic import op

revision = "1d72054cd637"
down_revision = "6287a47828ca"
branch_labels = None
depends_on = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS doc_embeddings (
            project_id  TEXT        NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            id          VARCHAR(512) NOT NULL,
            document    TEXT        NOT NULL,
            metadata    JSONB       NOT NULL DEFAULT '{}'::jsonb,
            embedding   vector(384) NOT NULL,
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (project_id, id)
        )
        """
    )

    # Equality on the one metadata key that is ever queried alone — the path that
    # removes a changed file's chunks before re-embedding them.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_doc_embeddings_source_path
        ON doc_embeddings (project_id, (metadata ->> 'source_path'))
        """
    )

    # `vector_cosine_ops` because the ChromaDB collections this replaces were created
    # with `{"hnsw:space": "cosine"}` — so `<=>` returns the same distance the old
    # store returned, and retrieval ranking does not silently change under the fix.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_doc_embeddings_hnsw
        ON doc_embeddings USING hnsw (embedding vector_cosine_ops)
        """
    )


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("DROP INDEX IF EXISTS ix_doc_embeddings_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_doc_embeddings_source_path")
    op.execute("DROP TABLE IF EXISTS doc_embeddings")
    # The extension is deliberately NOT dropped: another table may come to depend on
    # it, and dropping an extension takes its types with it.
