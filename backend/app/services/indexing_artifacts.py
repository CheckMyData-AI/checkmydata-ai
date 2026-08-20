"""Best-effort cleanup of indexing artifacts that live outside Postgres.

The Postgres FK cascades (``code_graph_*``, ``code_clusters``, ``db_index``,
``code_db_sync``, ``project_caches``, …) handle structured-data cleanup when a
project / connection is deleted. The artifacts below are intentionally
**not** in Postgres for cost / latency reasons, so they need explicit deletion
when their parent goes away:

* ``./data/repos/{project_id}/`` — the git clone, i.e. the project's whole source tree.
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
import shutil
from pathlib import Path

from app.config import settings
from app.knowledge.bm25_index import BM25Index
from app.knowledge.schema_retriever import SchemaRetriever

logger = logging.getLogger(__name__)


def _clone_dir(project_id: str) -> Path | None:
    """The clone directory for *project_id*, or None when it cannot safely be one.

    F-KNOW-08 adds an ``rmtree`` here, and that is the part worth being careful about: the
    path is built from an identifier, and an identifier that is empty, ``.``, ``..`` or
    contains a separator turns a per-project cleanup into ``rmtree`` over the directory
    holding **every** project's source — from a routine whose whole contract is to never
    raise.

    So the answer is a resolved path that must be a *direct child* of the configured base
    directory, or nothing. Resolution handles ``..``; the parent check handles both the
    empty id (``base / "" == base``) and a symlink pointing out of the tree, because a
    symlink resolves to where it points and its parent is then somewhere else.
    """
    candidate = (project_id or "").strip()
    if not candidate:
        return None
    base = Path(settings.repo_clone_base_dir)
    named = base / candidate
    # Checked BEFORE resolving, and on the *named* path rather than the resolved one.
    # A first version checked `is_symlink()` on the resolved result, which is always
    # False by construction — resolution is what removes the link. A symlink pointing
    # OUT of the tree was still refused, because its target's parent is not the base
    # directory; a symlink pointing at a sibling project resolved to a legitimate-looking
    # path inside the tree and `rmtree` followed it into that project's real source. The
    # test for that case is what found it.
    if named.is_symlink():
        return None
    try:
        resolved = named.resolve()
        base_resolved = base.resolve()
    except OSError:
        return None
    if resolved.parent != base_resolved or resolved == base_resolved:
        return None
    return resolved


def cleanup_project_artifacts(project_id: str) -> None:
    """Remove the git clone, code-corpus BM25 snapshot and Chroma collection."""
    if not project_id:
        return

    # 0. The git clone — the project's whole source tree. Heroku's filesystem is
    # ephemeral, so this leak is invisible there and permanent on a deployment with a
    # persistent volume: every deleted project keeps its repository forever. Somebody who
    # deletes a project has asked for their code to stop being here, which makes this a
    # retention question before a housekeeping one.
    clone = _clone_dir(project_id)
    if clone is not None and clone.is_dir():
        try:
            shutil.rmtree(clone)
            logger.info("indexing_artifacts: removed clone %s", clone)
        except OSError:
            # Louder than the rest of this module: a leaked repository is a retention
            # problem somebody may have to answer for, and `debug` is where that goes to
            # die.
            logger.warning(
                "indexing_artifacts: could not remove the clone for project %s at %s; "
                "the source tree is still on disk",
                project_id,
                clone,
                exc_info=True,
            )

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
