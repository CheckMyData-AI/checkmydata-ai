"""StaleRunReaper — recover stuck 'running' statuses after a hard worker crash.

Idempotent: only rows whose heartbeat (or, when heartbeat is NULL, updated_at)
is older than the timeout are touched, so it is safe to run concurrently in the
web and worker processes.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.code_db_sync import CodeDbSyncSummary
from app.models.db_index import DbIndexSummary
from app.models.indexing_checkpoint import IndexingCheckpoint
from app.models.indexing_run import IndexingRun

logger = logging.getLogger(__name__)

#: Marker written into ``IndexingRun.error`` when the reaper flips a live run.
#: RunCoordinator recognises a *reaped* failure by this marker and reconciles
#: the run when the still-alive pipeline later emits its terminal event.
REAP_ERROR = "stale run reaped"


class StaleRunReaper:
    @staticmethod
    def _stale(model, cutoff: datetime):
        # Stale if heartbeat is old, OR heartbeat missing AND the row itself
        # hasn't been updated recently (grace for just-started runs).
        #
        # No "age unknown" branch here, deliberately: `updated_at` is NOT NULL on
        # all three models this serves (`db_index.py:56,88`, `code_db_sync.py:50,81`,
        # `indexing_checkpoint.py:63`), so the reference always exists and the branch
        # would be defensive code no test could reach. `_stale_run` needs one because
        # its fallback column is nullable.
        return (model.heartbeat_at.is_not(None) & (model.heartbeat_at < cutoff)) | (
            model.heartbeat_at.is_(None) & (model.updated_at < cutoff)
        )

    @staticmethod
    def _stale_run(model, cutoff: datetime):
        """Stale when the row is old — or when its age cannot be established at all.

        ``IndexingRun`` has no ``updated_at`` grace column, so the fallback is
        ``started_at`` — and that column is nullable
        (``models/indexing_run.py:54``). F-SCHED-03 was raised as an
        *immediate-reap* race; that does not reproduce, because the NULL-heartbeat
        branch demands ``started_at < cutoff`` and ``heartbeat()`` writes a beat
        before its first interval. The hole is the mirror image: with **neither**
        reference, no branch matched, so a ``running`` row lived forever — the
        spinning-UI failure this reaper exists to end.

        Today the only creator (``run_coordinator.py:189``) sets both columns, so
        the state is unreachable through the code. That is a convention, not a
        constraint: a backfill, a manual fix, or a second insert path reintroduces
        an invisible immortal row. Treating "age unknown" as stale is the safe
        direction, because the reaper already tolerates flipping a live run —
        ``REAP_ERROR`` lets ``RunCoordinator`` reconcile one that is still alive,
        whereas nothing ever reconciles a row nobody can see is stuck.
        """
        return (
            (model.heartbeat_at.is_not(None) & (model.heartbeat_at < cutoff))
            | (
                model.heartbeat_at.is_(None)
                & model.started_at.is_not(None)
                & (model.started_at < cutoff)
            )
            | (model.heartbeat_at.is_(None) & model.started_at.is_(None))
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
        # F-SCHED-03: a `running` row with neither heartbeat nor start time is now
        # reaped, but doing that silently would swap one invisible state for another
        # — a run flipped to `failed` with no account of why. Counted before the
        # update so the log can name the invariant that broke. One COUNT per sweep
        # on an indexed status column; the state is unreachable through today's code
        # (`run_coordinator.py:189` sets both), which is exactly why nothing else
        # would ever tell us it stopped being unreachable.
        unaccountable = (
            await session.execute(
                select(func.count())
                .select_from(IndexingRun)
                .where(
                    IndexingRun.status.in_(("running", "cancelling")),
                    IndexingRun.heartbeat_at.is_(None),
                    IndexingRun.started_at.is_(None),
                )
            )
        ).scalar_one()

        runs_failed: CursorResult = await session.execute(  # type: ignore[assignment]
            update(IndexingRun)
            .where(IndexingRun.status == "running", self._stale_run(IndexingRun, cutoff))
            .values(
                status="failed",
                error=REAP_ERROR,
                failure_kind="fatal",
                finished_at=datetime.now(UTC),
            )
        )
        runs_cancelled: CursorResult = await session.execute(  # type: ignore[assignment]
            update(IndexingRun)
            .where(IndexingRun.status == "cancelling", self._stale_run(IndexingRun, cutoff))
            .values(status="cancelled", finished_at=datetime.now(UTC))
        )
        await session.flush()

        # max(0, …) guards the -1 "rowcount unknown" sentinel some drivers return.
        runs_count = max(0, int(runs_failed.rowcount or 0)) + max(
            0, int(runs_cancelled.rowcount or 0)
        )
        out = {
            "db_index": max(0, int(db_res.rowcount or 0)),
            "sync": max(0, int(sync_res.rowcount or 0)),
            "repo": max(0, int(repo_res.rowcount or 0)),
            "runs": runs_count,
        }
        unknown = any(
            (r.rowcount is not None and r.rowcount < 0)
            for r in (db_res, sync_res, repo_res, runs_failed, runs_cancelled)
        )
        if unaccountable:
            logger.warning(
                "Reaper: %d run(s) had status running/cancelling with neither "
                "heartbeat_at nor started_at — reaped as unaccountable. Every creator "
                "is supposed to set both (run_coordinator.py), so this means a write "
                "path or a backfill left a row nobody could tell was stuck.",
                unaccountable,
            )
        if any(out.values()):
            logger.info(
                "Reaper: reset stale runs — db_index=%d sync=%d repo=%d runs=%d (timeout=%ds)",
                out["db_index"],
                out["sync"],
                out["repo"],
                out["runs"],
                timeout_seconds,
            )
        elif unknown:
            logger.info(
                "Reaper: swept stale runs (rowcount unknown on this driver, timeout=%ds)",
                timeout_seconds,
            )
        return out
