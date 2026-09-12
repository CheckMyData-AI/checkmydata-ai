"""Put back the runs a process restart orphaned.

Measured on production 2026-09-09: three full rebuilds of the one real project died in
one night. Two were deploys I merged; the third was
`Stopping all processes with SIGTERM` seven seconds after the last heartbeat, with no
release behind it — Heroku cycles dynos on its own. A rebuild of that repository takes
hours and the platform restarts the dyno roughly daily, so the two collide without anyone
doing anything wrong.

`StaleRunReaper._requeue` is the recovery that exists, and it is the wrong instrument for
this case twice over: it waits 300 s to conclude the run is dead, and it spends a budget
(`reaper_requeue_max_attempts`, 2 per 6 h) meant for runs that fail on their own merits.
Two restarts exhausted it, so the third reap was refused — *"the run is failing for its
own reasons, not a restart"* — which was wrong, and unknowable from its data.

The replacement worker knows on its first line, because it IS the replacement: an
`index_repo` run still marked `running` and stamped with a different boot id belonged to
the process this one took over from.

A double enqueue is harmless, which is worth stating because it is the first objection:
arq may re-queue a job its worker was executing at shutdown, and this sweep may enqueue
the same work. Whichever arrives second reaches `run_repo_index_task`, finds the run the
first one minted, and returns with *"already has an active index run; not starting a
second one"* — the partial unique index behind that is proven cross-process in
`tests/unit/services/test_run_exclusion_cross_process.py`. Two enqueues, one index.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.release import BOOT_ID, owner
from app.models.indexing_run import IndexingRun

logger = logging.getLogger(__name__)

#: Deliberately NOT `REAP_ERROR`. That string spends the reaper's failure budget and
#: `RunCoordinator` compares it verbatim to reconcile a run that turns out to be alive.
#: An orphan is neither of those things.
ORPHAN_ERROR = "orphaned by a process restart"

#: Only this kind, and the asymmetry matches `StaleRunReaper._REQUEUE_TASKS` for the same
#: reason: `reconcile_embeddings` advances the `embedding_fingerprint` marker on enqueue,
#: so an interrupted `index_repo` leaves a marker asserting a rebuild that never ran, and
#: the nightly cron is `force_full=False` and cannot redo it. The short kinds are covered
#: by that cron.


async def _catalog(
    session: AsyncSession,
    project_id: str,
    run_id: str,
    current_step: str | None,
    *,
    message: str | None = None,
    failure_kind: str = "transient",
) -> None:
    """Record an orphaned run in the product's error catalog (OPS-16).

    Mirrors `StaleRunReaper._catalog`, including the step in the message: the marker
    alone collapses every orphaned run onto one line, and it was the step that made
    the 2026-09-08 cause findable. Never raises — see the caller's comment.
    """
    from app.services.error_log_service import ErrorLogService

    try:
        await ErrorLogService().upsert(
            session,
            project_id=project_id,
            source="run",
            kind=_KIND,
            message=message or f"{ORPHAN_ERROR} (step: {current_step or 'unknown'})",
            failure_kind=failure_kind,
            sample_ref=run_id,
            meta={"current_step": current_step, "boot_id": BOOT_ID},
        )
    except Exception:
        logger.warning("orphan sweep: failed to catalog orphaned run %s", run_id[:8], exc_info=True)


_KIND = "index_repo"


async def requeue_orphaned_runs(session: AsyncSession) -> int:
    """Mark this process type's abandoned runs dead and enqueue their replacements.

    Never raises: a worker must start even if this cannot.
    """
    from app.core.task_queue import enqueue

    me = owner()
    requeued = 0
    try:
        rows = (
            await session.scalars(
                select(IndexingRun).where(
                    IndexingRun.status == "running",
                    IndexingRun.kind == _KIND,
                )
            )
        ).all()
    except Exception:
        logger.warning("orphan sweep: could not read running runs", exc_info=True)
        return 0

    for row in rows:
        try:
            meta = json.loads(row.meta_json or "{}") or {}
        except (ValueError, TypeError):
            meta = {}
        boot = meta.get("boot_id") or ""
        stamped_owner = meta.get("owner") or ""

        # No stamp means the row predates this, and "whose was it?" has no answer.
        # Guessing would mean possibly killing a live run; the reaper's heartbeat test is
        # the right instrument when ownership is unknown.
        if not boot or not stamped_owner:
            continue
        # A run belonging to the OTHER process type is not ours to judge — `index_repo`
        # executes on the worker via the queue and on `web` via the manual route.
        if not me or stamped_owner != me:
            continue
        # And the run this very process is executing must survive, obviously.
        if boot == BOOT_ID:
            continue

        # Marked terminal first, and unconditionally: leaving it `running` would block its
        # own replacement through the partial unique index, which is precisely the state
        # that made three enqueued rebuilds bounce with "already has an active index run".
        row.status = "failed"
        row.error = ORPHAN_ERROR
        # OPS-16: a terminal run needs the columns that make it terminal. Without
        # `finished_at` the duration is incomputable in `/sync-history`, and without
        # `failure_kind` the row is a failure of no kind — the two fields every other
        # terminal path in this codebase sets. `error` stays exactly ORPHAN_ERROR,
        # which `run_coordinator` and the reaper's budget both compare verbatim.
        row.finished_at = datetime.now(UTC)
        row.failure_kind = "transient"
        orphaned_step = row.current_step
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            logger.warning("orphan sweep: could not close run %s", row.id[:8], exc_info=True)
            continue

        # OPS-16: and it reaches the product's own error catalog, as a reaped run does
        # (N3). Until now an orphaned run — including one whose re-enqueue returned
        # `None`, the very failure this sweep exists to surface — never produced an
        # `error_log` row, so `/api/logs` showed nothing at all. Best-effort by
        # construction: a diagnostic that can abort the recovery it describes is worse
        # than one that is occasionally incomplete.
        await _catalog(session, row.project_id, row.id, orphaned_step)

        try:
            job_id = await enqueue(
                "run_repo_index",
                project_id=row.project_id,
                force_full=bool(meta.get("force_full", False)),
            )
        except Exception:
            logger.error(
                "orphan sweep: %s for project %s was orphaned by a restart and could "
                "NOT be put back — nothing is rebuilding it.",
                _KIND,
                row.project_id[:8],
                exc_info=True,
            )
            continue

        if job_id is None:
            logger.error(
                "orphan sweep: %s for project %s was orphaned by a restart and could "
                "NOT be put back — nothing is rebuilding it.",
                _KIND,
                row.project_id[:8],
            )
            await _catalog(
                session,
                row.project_id,
                row.id,
                orphaned_step,
                message=f"{ORPHAN_ERROR} (re-enqueue failed — nothing is rebuilding it)",
                failure_kind="fatal",
            )
            continue

        requeued += 1
        logger.info(
            "orphan sweep: re-enqueued %s for project %s, orphaned at step %s by the "
            "restart this process is (force_full=%s, job=%s)",
            _KIND,
            row.project_id[:8],
            row.current_step or "unknown",
            bool(meta.get("force_full", False)),
            job_id,
        )

    if rows:
        logger.info(
            "orphan sweep: %d running %s run(s) seen, %d put back",
            len(rows),
            _KIND,
            requeued,
        )
    return requeued
