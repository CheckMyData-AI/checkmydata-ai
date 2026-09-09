from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings
from app.knowledge.ast_parser import GRAPH_EXTRACTION_SCHEMA, SYMBOL_UID_SCHEMA
from app.knowledge.chunk_metadata import SYMBOL_CHUNK_ID_SCHEMA
from app.models.base import async_session_factory
from app.models.deploy_state import DeployState
from app.models.project import Project
from app.services.embedding_reindex import queue_embedding_reindex

logger = logging.getLogger(__name__)

_FINGERPRINT_KEY = "embedding_fingerprint"
# Stable, arbitrary 64-bit key for pg_try_advisory_xact_lock — never change it.
_ADVISORY_LOCK_KEY = 8274123001


@dataclass
class ReconcileResult:
    status: str
    reindexed: int = 0
    fingerprint: str = ""


def embedding_fingerprint() -> str:
    """Deterministic string identifying the current embedding + index config.

    The symbol-UID schema is part of it (AUD-0819-02): changing `_make_uid`'s
    shape leaves every unchanged file's symbols on the old form, because
    `save_incremental` merges by FILE rather than by UID, so cross-file edges to
    them dangle until a clean rebuild. Riding this fingerprint means the rebuild
    is enqueued by `reconcile_embeddings` at startup — idempotent, advisory-locked
    across dynos, `force_full=True` — instead of being owed to an operator.

    The symbol-CHUNK-ID schema joined it on 2026-09-05, and it is a third axis
    rather than a rename of the first two: a symbol can keep its identity
    (`SYMBOL_UID_SCHEMA`) and its edges (`GRAPH_EXTRACTION_SCHEMA`) while the id
    addressing its stored chunks changes shape. Without the rebuild, every stored
    chunk keeps an id nothing will ever look up again — and, before board row
    2.10 landed in the same change, nothing could have deleted them either.
    """
    return (
        f"{settings.chroma_embedding_model}|{settings.embedder_max_tokens}"
        f"|uid{SYMBOL_UID_SCHEMA}|gx{GRAPH_EXTRACTION_SCHEMA}"
        f"|cid{SYMBOL_CHUNK_ID_SCHEMA}"
    )


async def reconcile_embeddings(
    session_factory: async_sessionmaker | None = None,
) -> ReconcileResult:
    """Detect an embedding-config change and enqueue a one-shot full reindex.

    Best-effort: never raises. The marker is advanced ONLY after a successful
    enqueue, so a failure retries on the next boot. On Postgres a
    transaction-scoped advisory lock serializes concurrent dynos; other
    dialects (SQLite dev) skip the lock (single process).
    """
    current = embedding_fingerprint()
    factory = session_factory or async_session_factory
    try:
        async with factory() as session:
            dialect = session.get_bind().dialect.name
            if dialect == "postgresql":
                locked = await session.scalar(
                    text("SELECT pg_try_advisory_xact_lock(:k)"),
                    {"k": _ADVISORY_LOCK_KEY},
                )
                if not locked:
                    return ReconcileResult("skipped_locked", fingerprint=current)

            stored = await session.get(DeployState, _FINGERPRINT_KEY)

            if stored is None:
                session.add(DeployState(key=_FINGERPRINT_KEY, value=current))
                await session.commit()
                return ReconcileResult("seeded", fingerprint=current)

            if stored.value == current:
                return ReconcileResult("unchanged", fingerprint=current)

            previous = stored.value
            ids = list((await session.scalars(select(Project.id))).all())
            jobs = await queue_embedding_reindex(ids)
            queued = sum(1 for j in jobs if j is not None)
            if ids and queued == 0:
                # The marker is advanced on ENQUEUE, deliberately — the rebuild is
                # asynchronous and waiting for it would block boot. But it has to be
                # advanced on an enqueue that HAPPENED. Advancing here would leave:
                # collections dropped, nothing queued, and a marker asserting the rebuild
                # already ran — which the nightly cron cannot undo, because it is
                # `force_full=False` and only a clean run rebuilds. Leaving the marker
                # alone means the next boot tries again, which is the recoverable state.
                logger.error(
                    "Embedding config changed (%s -> %s) but NOTHING could be queued for "
                    "%d project(s); leaving the fingerprint marker at the old value so "
                    "the next start-up retries. Vectors for those projects have been "
                    "dropped and are not being rebuilt.",
                    previous,
                    current,
                    len(ids),
                )
                return ReconcileResult("error", fingerprint=current)
            stored.value = current
            await session.commit()
            log = logger.info if queued == len(ids) else logger.warning
            log(
                "Embedding config changed (%s -> %s); queued %d of %d project(s).",
                previous,
                current,
                queued,
                len(ids),
            )
            return ReconcileResult("reindexed", reindexed=queued, fingerprint=current)
    except Exception:
        logger.warning("reconcile_embeddings failed; marker untouched", exc_info=True)
        return ReconcileResult("error", fingerprint=current)
