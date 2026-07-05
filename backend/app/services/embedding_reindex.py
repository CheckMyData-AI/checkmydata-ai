"""Embedding reindex management (CODEIDX-C1).

Provides ``queue_embedding_reindex`` — a one-shot operator utility that drops
every listed project's ChromaDB collection and enqueues a full repo-index run
for each project so they are re-embedded under the current
``settings.chroma_embedding_model`` / ``settings.embedder_max_tokens``.

**This is an operator action, NOT called automatically.**  Call it post-deploy
whenever ``CHROMA_EMBEDDING_MODEL`` or ``EMBEDDER_MAX_TOKENS`` has changed:

    from app.services.embedding_reindex import queue_embedding_reindex
    await queue_embedding_reindex(all_project_ids)

The function is best-effort: if the collection delete fails for one project it
logs a warning and continues so the remaining projects are still re-enqueued.
"""

from __future__ import annotations

import logging

from app.core.task_queue import enqueue
from app.knowledge.vector_store import VectorStore

logger = logging.getLogger(__name__)


async def queue_embedding_reindex(project_ids: list[str]) -> list[str | None]:
    """Drop Chroma collections and enqueue full repo re-index for each project.

    Parameters
    ----------
    project_ids:
        List of project UUIDs to reindex.  An empty list is a no-op.

    Returns
    -------
    A list of ARQ job IDs (or asyncio task names) in the same order as
    *project_ids*.  Entries are ``None`` when enqueue failed.

    Notes
    -----
    - ``force_full=True`` is always passed so the pipeline does a clean
      rebuild rather than a checkpoint resume (stale vectors are useless).
    - Collection deletion is best-effort: failure is logged but does not
      prevent the re-index enqueue — the pipeline itself will overwrite any
      remaining stale docs via upsert.
    - No Alembic migration is needed; Chroma state lives outside Postgres.
    """
    if not project_ids:
        logger.info("queue_embedding_reindex: no projects specified — nothing to do.")
        return []

    logger.info(
        "queue_embedding_reindex: dropping collections and re-enqueuing %d project(s)",
        len(project_ids),
    )

    vs = VectorStore()
    results: list[str | None] = []

    for pid in project_ids:
        # ── 1. Drop the stale Chroma collection ──────────────────────────────
        try:
            vs.delete_collection(pid)
            logger.info("queue_embedding_reindex: dropped collection for project %s", pid[:8])
        except Exception:
            logger.warning(
                "queue_embedding_reindex: failed to drop collection for project %s — "
                "continuing; pipeline upsert will overwrite stale vectors.",
                pid[:8],
                exc_info=True,
            )

        # ── 2. Enqueue a full re-index ────────────────────────────────────────
        job_id = await enqueue(
            "run_repo_index",
            project_id=pid,
            force_full=True,
        )
        logger.info(
            "queue_embedding_reindex: enqueued run_repo_index for project %s (job=%s)",
            pid[:8],
            job_id,
        )
        results.append(job_id)

    logger.info(
        "queue_embedding_reindex: done — %d project(s) queued for re-embedding.",
        len(project_ids),
    )
    return results
