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
"""

from __future__ import annotations

import json
import logging

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
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            logger.warning("orphan sweep: could not close run %s", row.id[:8], exc_info=True)
            continue

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
