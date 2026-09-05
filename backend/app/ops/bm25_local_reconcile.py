"""Rebuild missing BM25 snapshots on the local disk at start-up (F-KNOW-12).

The finding said snapshots live on an ephemeral disk, so hybrid retrieval goes
dense-only "after every restart". The measurement is sharper than that. `Procfile`
declares `web` and `worker` as separate Heroku process types, so they have separate
filesystems; `bm25_data_dir` is a local path (`config.py:653`) with no shared volume.
The repo index writes the snapshot in the **worker** (`worker.py:221` →
`pipeline_runner.py:1257`), and every reader on the chat path — `context_loader.py:79`,
`knowledge_agent.py:61`, `knowledge_catalog_service.py:89` — runs in the **web** dyno.
The file was written on one machine and read on another, so the BM25 leg had no
snapshot to read *at all* in that deployment.

The snapshot is derived data: `_run_bm25_build` builds it from `KnowledgeDoc` rows in
Postgres, with no clone, no network and no LLM. So the fix needs no shared storage —
each process rebuilds what it is about to read.

**Deliberately NOT advisory-locked**, unlike the other reconciles in this package. The
other two coordinate a single shared outcome in the database; this one produces a file
on *each* process's own disk, so every process must do it independently. A lock here
would let one dyno satisfy the check and leave the other reading nothing.

**Only MISSING snapshots are rebuilt, never stale ones.** At start-up there is no
clone, so the true head SHA is unknowable; rebuilding on a mismatch would stamp the
snapshot with the last *indexed* commit and present it as current — a claim this
process cannot support. Staleness stays with the pipeline, which has a clone
(`_repair_bm25_if_stale`).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.knowledge.bm25_corpus import corpus_entries_for_docs
from app.knowledge.bm25_index import BM25Index
from app.models.base import async_session_factory
from app.models.knowledge_doc import KnowledgeDoc
from app.models.project import Project
from app.models.repository import ProjectRepository

logger = logging.getLogger(__name__)


@dataclass
class Bm25ReconcileResult:
    status: str = "ok"
    rebuilt: int = 0
    schema_rebuilt: int = 0
    skipped_present: int = 0
    skipped_no_docs: int = 0
    failed: int = 0


async def _build_one(session: AsyncSession, project_id: str, bm25: BM25Index) -> int:
    """Build one project's snapshot from its stored docs. Returns chunk count."""
    docs = list(
        (
            await session.scalars(select(KnowledgeDoc).where(KnowledgeDoc.project_id == project_id))
        ).all()
    )
    entries = corpus_entries_for_docs(docs)
    if not entries:
        return 0

    # The SHA is a staleness stamp, not a precondition. When no indexed commit is
    # recorded we still build — refusing would leave the retriever dense-only for
    # exactly the projects that have content — and mark it `unknown` so the
    # pipeline's own staleness check will always disagree and rebuild properly.
    sha = await session.scalar(
        select(ProjectRepository.last_indexed_commit)
        .where(ProjectRepository.project_id == project_id)
        .where(ProjectRepository.last_indexed_commit.is_not(None))
        .limit(1)
    )
    await asyncio.to_thread(bm25.build, project_id, sha or "unknown", entries)
    return len(entries)


async def _reconcile_schema_snapshots(
    factory: async_sessionmaker, result: Bm25ReconcileResult
) -> None:
    """Rebuild missing per-connection SCHEMA snapshots on this process's disk.

    Separate flag (`schema_retrieval_enabled`) and separate builder: these are
    produced by the DB-index pipeline, not the repo index, so a project's snapshot
    being present says nothing about a connection's. Same rules as the project pass:
    missing only, never stale, never empty.
    """
    if not settings.schema_retrieval_enabled:
        return
    from app.knowledge.schema_retriever import SchemaRetriever
    from app.models.connection import Connection
    from app.models.db_index import DbIndex

    retriever = SchemaRetriever(data_dir=settings.bm25_data_dir)
    async with factory() as session:
        connection_ids = list(
            (
                await session.scalars(
                    select(Connection.id)
                    .join(DbIndex, DbIndex.connection_id == Connection.id)
                    .group_by(Connection.id)
                    .having(func.count(DbIndex.id) > 0)
                )
            ).all()
        )

    for cid in connection_ids:
        if await asyncio.to_thread(retriever.has_index, cid):
            result.skipped_present += 1
            continue
        try:
            async with factory() as session:
                entries = list(
                    (
                        await session.scalars(select(DbIndex).where(DbIndex.connection_id == cid))
                    ).all()
                )
            if not entries:
                continue
            # Same freshness key the pipeline uses: the newest `indexed_at`, stringified.
            latest = max((e.indexed_at for e in entries if e.indexed_at), default=None)
            sha = latest.isoformat() if latest else "empty"
            await asyncio.to_thread(retriever.build, cid, sha, entries)
            result.schema_rebuilt += 1
        except Exception:
            result.failed += 1
            logger.error(
                "bm25_local_reconcile: could not rebuild the schema snapshot for "
                "connection %s — SQL table selection stays on the relevance safety net",
                cid[:8],
                exc_info=True,
            )


async def reconcile_local_bm25(
    session_factory: async_sessionmaker | None = None,
) -> Bm25ReconcileResult:
    """Rebuild any project's missing BM25 snapshot on THIS process's disk.

    Best-effort per project: one failure is counted and named, never abandons the
    rest, and never raises. Safe to call on every boot — a present snapshot is
    skipped without reading a single document.
    """
    if not settings.hybrid_retrieval_enabled:
        return Bm25ReconcileResult(status="disabled")

    result = Bm25ReconcileResult()
    factory = session_factory or async_session_factory
    try:
        bm25 = BM25Index(settings.bm25_data_dir)
        async with factory() as session:
            # Only projects that actually have indexed content are candidates: a
            # project with no docs must keep reporting `no_snapshot` rather than get
            # an empty snapshot, which would turn a real gap into a silent `no_match`.
            project_ids = list(
                (
                    await session.scalars(
                        select(Project.id)
                        .join(KnowledgeDoc, KnowledgeDoc.project_id == Project.id)
                        .group_by(Project.id)
                        .having(func.count(KnowledgeDoc.id) > 0)
                    )
                ).all()
            )
            all_ids = list((await session.scalars(select(Project.id))).all())
        result.skipped_no_docs = len(all_ids) - len(project_ids)

        for pid in project_ids:
            if await asyncio.to_thread(bm25.indexed_sha, pid) is not None:
                result.skipped_present += 1
                continue
            try:
                async with factory() as session:
                    chunks = await _build_one(session, pid, bm25)
                if chunks:
                    result.rebuilt += 1
                else:
                    result.skipped_no_docs += 1
            except Exception:
                result.failed += 1
                logger.error(
                    "bm25_local_reconcile: could not rebuild the snapshot for project "
                    "%s — its BM25 leg stays dense-only until the next repo index",
                    pid[:8],
                    exc_info=True,
                )

        await _reconcile_schema_snapshots(factory, result)

        if result.rebuilt or result.schema_rebuilt or result.failed:
            logger.info(
                "bm25_local_reconcile: rebuilt=%d schema_rebuilt=%d present=%d "
                "no_docs=%d failed=%d",
                result.rebuilt,
                result.schema_rebuilt,
                result.skipped_present,
                result.skipped_no_docs,
                result.failed,
            )
        return result
    except Exception:
        logger.warning("bm25_local_reconcile failed", exc_info=True)
        result.status = "error"
        return result
