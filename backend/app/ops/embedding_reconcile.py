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
            await queue_embedding_reindex(ids)
            stored.value = current
            await session.commit()
            logger.info(
                "Embedding config changed (%s -> %s); reindexed %d project(s).",
                previous,
                current,
                len(ids),
            )
            return ReconcileResult("reindexed", reindexed=len(ids), fingerprint=current)
    except Exception:
        logger.warning("reconcile_embeddings failed; marker untouched", exc_info=True)
        return ReconcileResult("error", fingerprint=current)
