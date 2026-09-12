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

from app.config import settings
from app.core.release import current_release as _current_release
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

    async def _catalog(
        self,
        session: AsyncSession,
        doomed: list[tuple[str, str, str, str | None, str | None]],
    ) -> None:
        """Record each reaped run in the product's own error catalog.

        The message carries the **step**, not just the marker. ``stale run reaped``
        alone collapses every reaped run of a kind onto one line; with the step it
        separates, and separating is what made the cause findable — 64 of 70 failures
        were `graph_build` specifically. An operator should get that concentration from
        the product rather than from someone running SQL by hand.

        The run's own ``error`` column stays exactly :data:`REAP_ERROR`:
        ``run_coordinator.py:393`` compares it verbatim to recognise a reaped run and
        reconcile it when the pipeline turns out to be alive. Only the catalog message
        is enriched.

        Best-effort by construction. The catalog is a diagnostic, and a diagnostic that
        can abort the recovery it is describing is worse than one that is occasionally
        incomplete — a failed write here would leave the `running` rows unreaped and the
        UI spinning, which is the state this whole class exists to end.
        """
        if not doomed:
            return
        # Imported here rather than at module scope: `run_coordinator` imports
        # REAP_ERROR from this module, and the service pulls in the model layer.
        from app.services.error_log_service import ErrorLogService

        catalog = ErrorLogService()
        for run_id, project_id, kind, connection_id, current_step in doomed:
            try:
                await catalog.upsert(
                    session,
                    project_id=project_id,
                    source="run",
                    kind=kind,
                    message=f"{REAP_ERROR} (step: {current_step or 'unknown'})",
                    failure_kind="fatal",
                    sample_ref=run_id,
                    meta={"connection_id": connection_id, "current_step": current_step},
                )
            except Exception:
                logger.warning("Reaper: failed to catalog reaped run %s", run_id[:8], exc_info=True)

    #: Kinds worth re-enqueueing after a reap, and the task each maps to.
    #:
    #: `index_repo` alone, and the asymmetry is deliberate. `reconcile_embeddings`
    #: advances the `embedding_fingerprint` marker on ENQUEUE rather than on completion,
    #: so a deploy that restarts the worker mid-rebuild leaves a marker asserting the
    #: rebuild happened; the nightly cron then runs `force_full=False`, which cannot
    #: rebuild what only a clean run rebuilds. `db_index` and `code_db_sync` are short
    #: and the nightly sync covers them, and `daily_sync` is the cron itself.
    _REQUEUE_TASKS = {"index_repo": "run_repo_index"}

    async def _run_meta(self, session: AsyncSession, run_id: str) -> dict:
        """The reaped run's own `meta_json`, so the replacement inherits its arguments."""
        import json

        try:
            raw = await session.scalar(
                select(IndexingRun.meta_json).where(IndexingRun.id == run_id)
            )
            parsed = json.loads(raw or "{}")
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            logger.warning("Reaper: could not read meta for run %s", run_id[:8], exc_info=True)
            return {}

    async def _requeue_attempts(
        self,
        session: AsyncSession,
        project_id: str,
        kind: str,
        *,
        exclude_run_id: str | None = None,
    ) -> int:
        """How many of this project's runs of this kind the reaper has killed recently.

        Counted from the rows themselves rather than held in a counter on one row: the
        row a counter would live on is the one just destroyed, and each replacement
        starts a fresh row. `REAP_ERROR` narrows it to reaps — a run that failed on its
        own merits is a different fact and must not spend this budget.

        **`exclude_run_id` is the reap in flight (OPS-10).** `reap_once` runs the
        `UPDATE … status='failed', error=REAP_ERROR, finished_at=now()`, flushes, and
        only then calls `_requeue` — so without this the run being reaped right now
        was inside its own attempt count. With `reaper_requeue_max_attempts = 2` the
        first reap saw 1 and requeued, the second saw 2 and refused: a bound the
        operator is told allows two retries, spent after one. That halving ran in the
        same direction as the 2026-09-09 incident, where an exhausted budget was what
        refused a third rebuild.
        """
        import json

        window = datetime.now(UTC) - timedelta(hours=settings.reaper_requeue_window_hours)
        try:
            metas = (
                await session.scalars(
                    select(IndexingRun.meta_json).where(
                        IndexingRun.project_id == project_id,
                        IndexingRun.kind == kind,
                        IndexingRun.error == REAP_ERROR,
                        IndexingRun.finished_at >= window,
                        *([IndexingRun.id != exclude_run_id] if exclude_run_id is not None else []),
                    )
                )
            ).all()
            here = _current_release()
            if not here:
                # Nothing to compare against — a self-hosted install. Every reap counts,
                # which is exactly the behaviour that predates this distinction.
                return len(metas)
            counted = 0
            for raw in metas:
                try:
                    stamped = (json.loads(raw or "{}") or {}).get("release", "")
                except (ValueError, TypeError):
                    # Narrow on purpose: `json.loads` raises `JSONDecodeError` (a
                    # `ValueError`) or `TypeError`, and nothing else here can. A broad
                    # handler would spend the repository's `except Exception` budget on a
                    # case that cannot produce anything else. A malformed meta falls
                    # through to "unknown", which counts.
                    stamped = ""
                # A run started under a DIFFERENT release was orphaned when that release
                # was replaced — the process was taken away from it. That is not evidence
                # the work fails, and spending the budget on it is what refused a third
                # rebuild on 2026-09-09 with "failing for its own reasons, not a restart".
                # An absent stamp is unknown, and unknown counts: a bound that cannot
                # count stops bounding, the same rule the error path below follows.
                if stamped == here or not stamped:
                    counted += 1
            return counted
        except Exception:
            # Unknown attempt count must not read as zero, or the bound stops bounding.
            logger.warning("Reaper: could not count requeue attempts", exc_info=True)
            return settings.reaper_requeue_max_attempts

    async def _requeue(
        self,
        session: AsyncSession,
        doomed: list[tuple[str, str, str, str | None, str | None]],
    ) -> int:
        """Put back the work this reap destroyed. Never raises.

        The reap IS the recovery: a re-enqueue that propagated would leave `running`
        rows unreaped and the UI spinning, which is the state this class exists to end.
        """
        if not doomed or not settings.reaper_requeue_enabled:
            return 0

        from app.core.task_queue import enqueue

        requeued = 0
        for run_id, project_id, kind, _connection_id, current_step in doomed:
            task = self._REQUEUE_TASKS.get(kind)
            if not task:
                continue
            try:
                attempts = await self._requeue_attempts(
                    session, project_id, kind, exclude_run_id=run_id
                )
                if attempts >= settings.reaper_requeue_max_attempts:
                    logger.warning(
                        "Reaper: not re-enqueueing %s for project %s — %d reaps in the "
                        "last %dh is at the bound; the run is failing for its own "
                        "reasons, not a restart.",
                        kind,
                        project_id[:8],
                        attempts,
                        settings.reaper_requeue_window_hours,
                    )
                    continue
                meta = await self._run_meta(session, run_id)
                job_id = await enqueue(
                    task,
                    project_id=project_id,
                    force_full=bool(meta.get("force_full", False)),
                )
                if job_id is None:
                    # `enqueue` returns None rather than raising, so this used to be
                    # counted and logged as a success — the work was destroyed by the
                    # reap and not put back, silently.
                    logger.error(
                        "Reaper: destroyed %s for project %s at step %s and could NOT "
                        "put it back — nothing is rebuilding it.",
                        kind,
                        project_id[:8],
                        current_step or "unknown",
                    )
                    continue
                requeued += 1
                logger.info(
                    "Reaper: re-enqueued %s for project %s after a reap at step %s "
                    "(force_full=%s, job=%s, attempt %d of %d)",
                    kind,
                    project_id[:8],
                    current_step or "unknown",
                    bool(meta.get("force_full", False)),
                    job_id,
                    # `attempts` no longer contains this reap, so the count of THIS
                    # attempt is one more — and the first requeue now prints "1 of 2"
                    # rather than announcing itself as attempt 2 (OPS-10).
                    attempts + 1,
                    settings.reaper_requeue_max_attempts,
                )
            except Exception:
                logger.warning(
                    "Reaper: failed to re-enqueue %s for project %s",
                    kind,
                    project_id[:8],
                    exc_info=True,
                )
        return requeued

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

        # Read what is about to die *before* killing it, and keep plain values rather
        # than ORM objects: the bulk UPDATE below may expire them, and this is the only
        # moment the run's own step is still knowable.
        #
        # Why this exists at all: `RunCoordinator` catalogs failures in three places
        # (`run_coordinator.py:317`, `:450`, `:485`) and every one sits on a
        # terminal-event path. A reaped run emits no terminal event — its process is
        # gone — so no writer was ever reached, and `error_log` held 3 rows against 143
        # failed runs. The catalog is what `/api/logs` shows an operator; a failure it
        # cannot see is a failure nobody is told about.
        doomed = [
            (r.id, r.project_id, r.kind, r.connection_id, r.current_step)
            for r in (
                await session.execute(
                    select(IndexingRun).where(
                        IndexingRun.status == "running", self._stale_run(IndexingRun, cutoff)
                    )
                )
            )
            .scalars()
            .all()
        ]

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
        await self._catalog(session, doomed)
        await self._requeue(session, doomed)

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
