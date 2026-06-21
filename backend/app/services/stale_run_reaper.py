"""StaleRunReaper — recover stuck 'running' statuses after a hard worker crash.

Idempotent: only rows whose heartbeat (or, when heartbeat is NULL, updated_at)
is older than the timeout are touched, so it is safe to run concurrently in the
web and worker processes.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.code_db_sync import CodeDbSyncSummary
from app.models.db_index import DbIndexSummary
from app.models.indexing_checkpoint import IndexingCheckpoint

logger = logging.getLogger(__name__)


class StaleRunReaper:
    @staticmethod
    def _stale(model, cutoff: datetime):
        # Stale if heartbeat is old, OR heartbeat missing AND the row itself
        # hasn't been updated recently (grace for just-started runs).
        return (model.heartbeat_at.is_not(None) & (model.heartbeat_at < cutoff)) | (
            model.heartbeat_at.is_(None) & (model.updated_at < cutoff)
        )

    async def reap_once(self, session: AsyncSession, *, timeout_seconds: int) -> dict[str, int]:
        cutoff = datetime.now(UTC) - timedelta(seconds=timeout_seconds)

        db_res: CursorResult = await session.execute(  # type: ignore[assignment]
            update(DbIndexSummary)
            .where(DbIndexSummary.indexing_status == "running", self._stale(DbIndexSummary, cutoff))
            .values(indexing_status="failed")
        )
        sync_res: CursorResult = await session.execute(  # type: ignore[assignment]
            update(CodeDbSyncSummary)
            .where(
                CodeDbSyncSummary.sync_status == "running",
                self._stale(CodeDbSyncSummary, cutoff),
            )
            .values(sync_status="failed")
        )
        repo_res: CursorResult = await session.execute(  # type: ignore[assignment]
            update(IndexingCheckpoint)
            .where(IndexingCheckpoint.status == "running", self._stale(IndexingCheckpoint, cutoff))
            .values(status="interrupted")
        )
        await session.flush()

        # max(0, …) guards the -1 "rowcount unknown" sentinel some drivers return.
        out = {
            "db_index": max(0, int(db_res.rowcount or 0)),
            "sync": max(0, int(sync_res.rowcount or 0)),
            "repo": max(0, int(repo_res.rowcount or 0)),
        }
        if any(out.values()):
            logger.info(
                "Reaper: reset stale runs — db_index=%d sync=%d repo=%d (timeout=%ds)",
                out["db_index"],
                out["sync"],
                out["repo"],
                timeout_seconds,
            )
        return out
