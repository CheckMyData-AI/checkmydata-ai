"""Best-effort cleanup of indexing artifacts that live outside Postgres.

The Postgres FK cascades (``code_graph_*``, ``code_clusters``, ``db_index``,
``code_db_sync``, ``project_caches``, …) handle structured-data cleanup when a
project / connection is deleted. The artifacts below are intentionally
**not** in Postgres for cost / latency reasons, so they need explicit deletion
when their parent goes away:

* ``./data/bm25/{project_id}.pkl`` — code corpus BM25 snapshot (M3).
* ``./data/bm25/schema_{connection_id}.pkl`` — schema BM25 snapshot (M4).
* ChromaDB collection ``project_{project_id}`` — the dense knowledge corpus.

Every function here is **idempotent** and **non-throwing**: failures are
logged but never propagate, because cleanup runs in the same transaction
boundary that ships the user-visible delete; a leaked ``.pkl`` is preferable
to a 500.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.config import settings
from app.knowledge.bm25_index import BM25Index
from app.knowledge.schema_retriever import SchemaRetriever

logger = logging.getLogger(__name__)


def cleanup_project_artifacts(project_id: str) -> None:
    """Remove code-corpus BM25 snapshot + Chroma collection for a project."""
    if not project_id:
        return

    # 1. BM25 code corpus snapshot.
    try:
        bm25 = BM25Index(Path(settings.bm25_data_dir))
        bm25.delete(project_id)
    except Exception:
        logger.debug(
            "indexing_artifacts: BM25 cleanup failed for project %s",
            project_id,
            exc_info=True,
        )

    # 2. Chroma collection (best-effort — VectorStore is a singleton and we
    # don't want to pin its lifecycle to this delete path).
    try:
        from app.knowledge.vector_store import VectorStore

        VectorStore().delete_collection(project_id)
    except Exception:
        logger.debug(
            "indexing_artifacts: Chroma cleanup failed for project %s",
            project_id,
            exc_info=True,
        )


def cleanup_connection_artifacts(connection_id: str) -> None:
    """Remove schema BM25 snapshot for a single connection."""
    if not connection_id:
        return
    try:
        retriever = SchemaRetriever(data_dir=settings.bm25_data_dir)
        retriever.delete(connection_id)
    except Exception:
        logger.debug(
            "indexing_artifacts: schema BM25 cleanup failed for connection %s",
            connection_id,
            exc_info=True,
        )


__all__ = ["cleanup_project_artifacts", "cleanup_connection_artifacts"]
