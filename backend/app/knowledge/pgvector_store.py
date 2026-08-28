"""The vector store, backed by Postgres instead of a dyno's local disk.

Drop-in for :class:`app.knowledge.vector_store.VectorStore`: same six methods, same
shapes in and out, same cosine distance. Only where the vectors live changes.

**Why.** ``CHROMA_PERSIST_DIR`` is ``/app/data/chroma`` in production — the container
filesystem, wiped on every dyno restart, and not shared between the ``web`` and
``worker`` process types. Measured on 2026-08-27: the worker found the store empty
five hours after a deploy, so ``pipeline_runner`` set ``force_full``; a full rebuild
of that repository costs 12 039 s against the nightly job's 7 200 s ceiling; the run
was reaped at 124.9 minutes and the store was empty again the next night. 16 of 94
repo-index runs have ever completed. The self-repair was not wrong — it cost more
than the budget allowed, which no ceiling could fix.

**Synchronous on purpose.** The interface it replaces is called synchronously from
ten sites, several on the agent's hot path (``context_loader.py:213,421``,
``knowledge_catalog_service.py:480,539``). Converting those to async is a larger and
riskier change than carrying psycopg beside asyncpg, so the port keeps the shape and
changes only the storage. One variable at a time.

**Embeddings are unchanged.** ChromaDB computed them internally with its bundled ONNX
``all-MiniLM-L6-v2``; this class calls the same class directly. Identical vectors,
identical dimension, identical metric — so a query returns the neighbours it returned
before, and any change in answers is a bug rather than a new model.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from app.config import settings
from app.models.doc_embedding import EMBEDDING_DIM

logger = logging.getLogger(__name__)


class EmbeddingDimensionError(RuntimeError):
    """Raised when the embedder stops producing the width the column declares.

    Loud on purpose. A silently truncated or padded vector is an index that returns
    plausible neighbours which are simply wrong, and nothing downstream can tell.
    """


def _sync_dsn(url: str) -> str:
    """SQLAlchemy's async URL is not a libpq DSN — psycopg wants the driver gone."""
    return url.replace("+asyncpg", "").replace("postgresql+psycopg", "postgresql")


class _ProjectHandle:
    """What ``get_or_create_collection`` hands back.

    ChromaDB returned a ``Collection``; both callers in this codebase use exactly two
    things from it — ``count()`` and, for logging, its name. Mirroring that surface is
    what lets the backend swap without touching the call sites, and ``count()`` in
    particular is load-bearing: ``pipeline_runner`` reads it to decide whether the
    store is empty and a full re-index is owed, which is the decision that made an
    ephemeral store rebuild itself nightly and never finish.
    """

    __slots__ = ("_store", "project_id", "name")

    def __init__(self, store: PgVectorStore, project_id: str) -> None:
        self._store = store
        self.project_id = project_id
        safe = project_id.replace("-", "_")[:50]
        self.name = f"project_{safe}"

    def count(self) -> int:
        return self._store.count(self.project_id)


class PgVectorStore:
    """Postgres-backed vector store. Thread-safe; one connection pool per process."""

    def __init__(self) -> None:
        from psycopg_pool import ConnectionPool

        self._embedding_fn: Any | None = None
        self._embed_lock = threading.Lock()
        self._pool = ConnectionPool(
            conninfo=_sync_dsn(settings.database_url),
            min_size=1,
            max_size=max(2, settings.db_pool_size // 2),
            open=True,
            # A pooled connection that outlives a Supavisor session is a connection
            # that fails on first use rather than on checkout.
            max_lifetime=float(settings.db_pool_recycle),
            kwargs={"autocommit": True},
        )
        self._register_vector()
        logger.info("PgVectorStore: pool open (dim=%d)", EMBEDDING_DIM)

    def _register_vector(self) -> None:
        from pgvector.psycopg import register_vector

        with self._pool.connection() as conn:
            register_vector(conn)

    # -- embedding ---------------------------------------------------------------

    def _embed(self, texts: list[str]) -> list[list[float]]:
        """Embed with the same model ChromaDB used internally.

        Loaded lazily and once: the ONNX session is ~90 MiB and the web dyno only
        needs it when a query arrives, not at import.
        """
        if self._embedding_fn is None:
            with self._embed_lock:
                if self._embedding_fn is None:
                    from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2

                    self._embedding_fn = ONNXMiniLM_L6_V2()
        vectors = [list(map(float, v)) for v in self._embedding_fn(texts)]
        for v in vectors:
            if len(v) != EMBEDDING_DIM:
                raise EmbeddingDimensionError(
                    f"embedder produced {len(v)} dimensions, column declares "
                    f"{EMBEDDING_DIM} — re-index is required, not a cast"
                )
        return vectors

    # -- the VectorStore interface -----------------------------------------------

    def get_or_create_collection(self, project_id: str) -> _ProjectHandle:
        """There is no collection to create — rows carry ``project_id``. What comes
        back is a handle exposing ``.count()`` and ``.name``, because that is the
        whole of what the two callers use it for
        (``pipeline_runner.py:415``, ``context_loader.py:213``), and keeping the
        shape means neither has to change to gain a working store."""
        return _ProjectHandle(self, project_id)

    def add_documents(
        self,
        project_id: str,
        doc_ids: list[str],
        documents: list[str],
        metadatas: list[dict] | None = None,
    ) -> None:
        if not doc_ids:
            return
        # TWO batch sizes, because embedding and writing pull in opposite directions
        # and used to share one number only because ChromaDB's write was local and free.
        #
        # Embedding is memory-bound: the ONNX model pads every document to 256 tokens,
        # so the transformer's activations are sized by the batch and nothing else —
        # 967 MiB at 200 against 415 MiB at 8, and an unbounded batch is what SIGKILLed
        # the worker (AUD-0819-01). That number must stay small.
        #
        # Writing is round-trip-bound. Measured against the production database with
        # the embedder stubbed out, 800 rows:
        #
        #     batch=  8   16.67 s   (100 round-trips, ~167 ms each)
        #     batch=100    2.31 s   (  8 round-trips)
        #     batch=400    1.92 s   (  2 round-trips)
        #
        # A fixed ~167 ms per statement dominates completely, and tying the write to
        # the embed batch paid it 3 196 times over a full rebuild. HNSW maintenance was
        # the first suspect and is not the cause: measured server-side, 8 000 rows cost
        # 1 376 ms with no index and 12 348 ms with one — 9x, but only ~44 s across the
        # whole corpus, not the tens of minutes observed.
        embed_step = max(1, settings.embedding_upsert_batch_size)
        write_step = max(embed_step, settings.pgvector_write_batch_size)

        buf_ids: list[str] = []
        buf_docs: list[str] = []
        buf_meta: list[str] = []
        buf_vecs: list[str] = []

        def _flush(conn: Any) -> None:
            if not buf_ids:
                return
            conn.execute(
                """
                INSERT INTO doc_embeddings
                    (project_id, id, document, metadata, embedding, updated_at)
                SELECT %s, u.id, u.document, u.metadata::jsonb, u.embedding, now()
                FROM unnest(%s::text[], %s::text[], %s::text[], %s::vector[])
                     AS u(id, document, metadata, embedding)
                ON CONFLICT (project_id, id) DO UPDATE
                   SET document   = EXCLUDED.document,
                       metadata   = EXCLUDED.metadata,
                       embedding  = EXCLUDED.embedding,
                       updated_at = now()
                """,
                (project_id, buf_ids, buf_docs, buf_meta, buf_vecs),
            )
            buf_ids.clear()
            buf_docs.clear()
            buf_meta.clear()
            buf_vecs.clear()

        with self._pool.connection() as conn:
            for start in range(0, len(doc_ids), embed_step):
                end = start + embed_step
                chunk_docs = documents[start:end]
                chunk_ids = doc_ids[start:end]
                chunk_meta = (
                    metadatas[start:end] if metadatas is not None else [{}] * len(chunk_ids)
                )
                vectors = self._embed(chunk_docs)
                buf_ids.extend(chunk_ids)
                buf_docs.extend(chunk_docs)
                buf_meta.extend(json.dumps(m or {}) for m in chunk_meta)
                buf_vecs.extend(str(v) for v in vectors)
                if len(buf_ids) >= write_step:
                    _flush(conn)
            _flush(conn)

        logger.debug(
            "PgVectorStore: upserted %d documents for project %s (embed %d, write %d)",
            len(doc_ids),
            project_id,
            embed_step,
            write_step,
        )

    def query(
        self,
        project_id: str,
        query_text: str,
        n_results: int = 5,
        where: dict | None = None,
    ) -> list[dict]:
        """Nearest neighbours by cosine distance, shaped exactly as ChromaDB shaped
        them: ``{id, document, distance, metadata}``.

        ``where`` is ChromaDB's equality filter over metadata. Only the flat
        ``{"key": value}`` form was ever used in this codebase; an operator form
        (``$eq``, ``$in``) would silently match nothing here, so it raises instead.
        """
        # Validate the filter BEFORE embedding. The embed is an ONNX forward pass;
        # refusing an unsupported filter after paying for it wastes the work and puts
        # the error a frame further from its cause.
        filter_clauses: list[str] = []
        filter_params: list[Any] = []
        for key, value in (where or {}).items():
            if isinstance(value, dict):
                raise ValueError(
                    f"PgVectorStore: operator filter {key}={value!r} is not supported; "
                    "only flat equality was ever used by this codebase"
                )
            filter_clauses.append("metadata ->> %s = %s")
            filter_params.extend([key, str(value)])

        vector = self._embed([query_text])[0]
        # psycopg binds %s positionally in statement order, and the query vector's
        # placeholder is in the SELECT list — so it must be the FIRST parameter, not
        # the first one the WHERE clause happens to need. Getting this backwards
        # passes the project id where a vector belongs and fails at the cast rather
        # than returning wrong rows, which is the one mercy in it.
        params: list[Any] = [str(vector), project_id, *filter_params, n_results]
        clauses = ["project_id = %s", *filter_clauses]

        sql = f"""
            SELECT id, document, metadata, embedding <=> %s::vector AS distance
            FROM doc_embeddings
            WHERE {" AND ".join(clauses)}
            ORDER BY distance
            LIMIT %s
        """
        with self._pool.connection() as conn:
            rows = conn.execute(sql, params).fetchall()

        return [
            {
                "id": r[0],
                "document": r[1],
                "distance": float(r[3]),
                "metadata": r[2] or {},
            }
            for r in rows
        ]

    def delete_by_source_path(self, project_id: str, source_path: str) -> int:
        """Remove every chunk of one file. Returns how many rows went."""
        with self._pool.connection() as conn:
            cur = conn.execute(
                "DELETE FROM doc_embeddings "
                "WHERE project_id = %s AND metadata ->> 'source_path' = %s",
                (project_id, source_path),
            )
            return cur.rowcount or 0

    def delete_collection(self, project_id: str) -> None:
        with self._pool.connection() as conn:
            conn.execute("DELETE FROM doc_embeddings WHERE project_id = %s", (project_id,))

    def count(self, project_id: str) -> int:
        """How many vectors a project holds.

        The ChromaDB backend exposes this through the collection object
        (`collection.count()`), which `pipeline_runner` reads to decide whether the
        store is empty and a full re-index is owed. That decision is the reason this
        class exists, so the number it reads must come from here.
        """
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT count(*) FROM doc_embeddings WHERE project_id = %s", (project_id,)
            ).fetchone()
        return int(row[0]) if row else 0

    def close(self) -> None:
        try:
            self._pool.close()
        except Exception:  # pragma: no cover - close is best-effort
            logger.debug("PgVectorStore: pool close failed", exc_info=True)
