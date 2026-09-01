"""Vector embeddings, stored in Postgres rather than on a dyno's local disk.

ChromaDB persisted to ``CHROMA_PERSIST_DIR`` — ``/app/data/chroma`` in production,
which is the container filesystem and is wiped on every dyno restart. Two things
followed, and the second is why this table exists rather than a bigger disk:

* ``web`` and ``worker`` are separate Heroku process types with separate
  filesystems, so a store the worker built was never visible to the chat path.
* An empty store makes ``pipeline_runner`` set ``force_full`` ("Vector store empty
  but 758 docs in DB. Forcing a full re-index") — and a full rebuild of the one
  real customer repository measures 12 039 s against the nightly job's 7 200 s
  ceiling. Measured 2026-08-27: 16 of 94 repo-index runs ever completed. The
  self-repair was correct; it simply cost more than the budget allowed, so the
  store stayed empty and the loop repeated every night.

Postgres has neither property: one store, shared by every dyno, surviving restarts.

**Dimension is fixed at 384 on purpose.** It is what ChromaDB's bundled
``all-MiniLM-L6-v2`` produces, which is what production has always stored —
``CHROMA_EMBEDDING_MODEL`` names a 768-d model but ``sentence-transformers`` is not
installed, so it has never taken effect. Changing the embedder changes this column,
and ``embedding_fingerprint()`` already forces a re-index when it moves.
"""

from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, DateTime, ForeignKey, Index, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

# Imported, not declared: it lived here as a second copy, and two homes for one fact is
# how the configured window and the real embedder drifted 512 against 256. Re-exported so
# existing `from app.models.doc_embedding import EMBEDDING_DIM` callers keep working.
from app.core.embedder import EMBEDDING_DIM
from app.models.base import Base


class DocEmbedding(Base):
    """One embedded chunk. Keyed by ``(project_id, id)`` because ChromaDB ids are
    unique within a collection — one collection per project — and never globally."""

    __tablename__ = "doc_embeddings"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # Text, not String(512). The id embeds the symbol UID, which already begins with
    # the file path the id also prefixes — so a deep PHP module path counts twice, and
    # production dropped code-symbol chunks in batches of 200 with
    # StringDataRightTruncation. Measured there: uids reach 316 chars and the longest
    # id that fit was 497, which is how the cap looked survivable until it was not.
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    document: Mapped[str] = mapped_column(Text, nullable=False)
    # Both columns carry a SQLite variant, and neither is decoration. Development
    # and the whole test suite run on SQLite and call `create_all` over every model;
    # `JSONB` refuses to compile there ("can't render element of type JSONB") and
    # `vector` does not exist at all. The variants let the table be *declared*
    # everywhere while only Postgres gets the types that mean anything — which
    # matches the migration, a deliberate no-op on SQLite, and the factory, which
    # refuses `pgvector` on a SQLite URL rather than failing later on a missing table.
    doc_metadata: Mapped[dict] = mapped_column(
        "metadata",
        JSONB().with_variant(JSON(), "sqlite"),
        nullable=False,
        server_default="{}",
    )
    embedding: Mapped[list[float]] = mapped_column(
        Vector(EMBEDDING_DIM).with_variant(Text(), "sqlite"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        # `source_path` is the only metadata key ever queried on its own — it is how
        # a changed file's chunks are removed before re-embedding
        # (`delete_by_source_path`). An expression btree on that one key answers the
        # equality directly; a GIN index over the whole `metadata` document would be
        # larger, slower to maintain, and would still need a recheck.
        Index(
            "ix_doc_embeddings_source_path",
            "project_id",
            text("(metadata ->> 'source_path')"),
        ),
        # The similarity index. HNSW rather than IVFFlat: it needs no training pass,
        # so it works from an empty table and does not degrade as rows arrive.
        # Measured on this schema with 30 000 rows of 384 dimensions — build 20 s,
        # and a top-5 filtered by `project_id` goes from 4 738 ms unindexed to
        # 0.92 ms. `vector_cosine_ops` because the ChromaDB collections it replaces
        # were created with `{"hnsw:space": "cosine"}`, so `<=>` returns the same
        # distance the old store returned.
        Index(
            "ix_doc_embeddings_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
