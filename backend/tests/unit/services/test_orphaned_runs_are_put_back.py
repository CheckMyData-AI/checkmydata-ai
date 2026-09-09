"""A worker that restarts knows the previous worker's runs are dead. It should say so.

Measured on production 2026-09-09, three times in one night, and only the first two were
my doing:

    23:44:39 run   last beat 23:47:53   v352 deployed 23:47:54   (a deploy I merged)
    23:54:06 run   last beat 00:00:25   v353 deployed 00:00:45   (a deploy I merged)
    00:29:37 run   last beat 00:49:52   `Stopping all processes with SIGTERM` 00:49:59

The third had no deploy behind it — Heroku cycles dynos on its own. So "do not ship
releases over a running rebuild" is necessary and not sufficient: a full rebuild of this
project takes hours, the platform restarts the dyno roughly daily, and the two will
collide on their own.

What recovery exists today is `StaleRunReaper._requeue`, and it is the wrong instrument
for this:

* it waits for `stale_running_heartbeat_timeout_seconds` (300 s) to decide the run is
  dead — which the replacement worker already knows on its first line;
* it spends `reaper_requeue_max_attempts` (2 per 6 h), a budget meant for runs that fail
  on their own merits. Two restarts exhausted it and the third reap was refused with
  *"the run is failing for its own reasons, not a restart"*. It was wrong, and from its
  own data it could not have known.

The replacement worker can know, because it IS the replacement: any `index_repo` run
still marked `running` and stamped with a different boot id belonged to the process this
one replaced. Nothing else in the system has that fact for free.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.release import BOOT_ID
from app.models.base import Base
from app.models.indexing_run import IndexingRun
from app.ops.orphan_runs import ORPHAN_ERROR, requeue_orphaned_runs


@pytest_asyncio.fixture(autouse=True)
def _this_is_a_worker(monkeypatch):
    """A test process has no `DYNO`, so `owner()` is empty and the sweep skips everything
    — correctly, since it must never act when it cannot tell whose run it is looking at.
    Every case here is about a worker, so say so."""
    monkeypatch.setenv("DYNO", "worker.1")


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _run(
    db: AsyncSession,
    *,
    wf: str,
    boot: str | None,
    owner: str | None = "worker",
    kind: str = "index_repo",
    status: str = "running",
    project: str = "p1",
    force_full: bool = True,
) -> str:
    meta: dict = {"force_full": force_full}
    if boot is not None:
        meta["boot_id"] = boot
    if owner is not None:
        meta["owner"] = owner
    row = IndexingRun(
        workflow_id=wf,
        project_id=project,
        connection_id=None,
        kind=kind,
        trigger="schedule",
        status=status,
        step_index=0,
        total_steps=5,
        progress_pct=0,
        meta_json=json.dumps(meta),
    )
    db.add(row)
    await db.commit()
    return row.id


class TestTheReplacementPutsBackWhatItReplaced:
    async def test_a_run_from_a_previous_boot_is_requeued(self, db) -> None:
        run_id = await _run(db, wf="w1", boot="an-older-process")
        enq = AsyncMock(return_value="job-1")
        with patch("app.core.task_queue.enqueue", new=enq):
            n = await requeue_orphaned_runs(db)

        assert n == 1
        enq.assert_awaited_once()
        assert enq.await_args.kwargs["project_id"] == "p1"
        assert enq.await_args.kwargs["force_full"] is True, (
            "the replacement must inherit force_full, or a clean rebuild silently becomes "
            "an incremental one and the marker still says it happened"
        )
        row = await db.get(IndexingRun, run_id)
        await db.refresh(row)
        assert row.status == "failed"
        assert row.error == ORPHAN_ERROR

    async def test_this_process_own_run_is_left_alone(self, db) -> None:
        """The run executing right now is stamped with THIS boot id. Requeuing it would
        start a second index of the same project — the thing the partial unique index
        exists to prevent."""
        await _run(db, wf="w1", boot=BOOT_ID)
        with patch("app.core.task_queue.enqueue", new=AsyncMock(return_value="j")) as enq:
            assert await requeue_orphaned_runs(db) == 0
            enq.assert_not_awaited()

    async def test_a_run_owned_by_another_process_type_is_left_alone(self, db) -> None:
        """`_run_index_background` also runs on `web`, for the manual route. A worker
        sweeping those would kill an index that is running perfectly on another dyno."""
        await _run(db, wf="w1", boot="another-boot", owner="web")
        assert await requeue_orphaned_runs(db) == 0

    async def test_an_unstamped_run_is_left_to_the_reaper(self, db) -> None:
        """Rows written before this change carry no boot id. "Whose was it?" has no
        answer, and guessing means possibly killing a live run — the reaper's heartbeat
        test is the right instrument when the ownership is unknown."""
        await _run(db, wf="w1", boot=None, owner=None)
        assert await requeue_orphaned_runs(db) == 0

    async def test_a_finished_run_is_not_resurrected(self, db) -> None:
        await _run(db, wf="w1", boot="older", status="completed")
        assert await requeue_orphaned_runs(db) == 0

    async def test_only_index_repo_is_put_back(self, db) -> None:
        """The same asymmetry `StaleRunReaper._REQUEUE_TASKS` already carries: the
        nightly cron re-runs the short kinds, and only `index_repo` leaves an
        `embedding_fingerprint` marker asserting a rebuild that did not happen."""
        await _run(db, wf="w1", boot="older", kind="db_index")
        await _run(db, wf="w2", boot="older", kind="daily_sync")
        assert await requeue_orphaned_runs(db) == 0


class TestItNeverTakesTheWorkerDownWithIt:
    async def test_a_failed_enqueue_is_reported_and_not_counted(self, db, caplog) -> None:
        import logging

        run_id = await _run(db, wf="w1", boot="older")
        with (
            patch("app.core.task_queue.enqueue", new=AsyncMock(return_value=None)),
            caplog.at_level(logging.DEBUG),
        ):
            assert await requeue_orphaned_runs(db) == 0
        assert [r for r in caplog.records if r.levelno >= logging.ERROR], (
            "the run was marked dead and not put back, and nothing said so above INFO"
        )
        # Still marked terminal: leaving it `running` would block its own replacement.
        row = await db.get(IndexingRun, run_id)
        await db.refresh(row)
        assert row.status == "failed"

    async def test_an_exploding_enqueue_does_not_stop_the_worker(self, db) -> None:
        await _run(db, wf="w1", boot="older")
        with patch("app.core.task_queue.enqueue", new=AsyncMock(side_effect=RuntimeError("x"))):
            assert await requeue_orphaned_runs(db) == 0  # returns, does not raise

    async def test_the_error_is_distinct_from_a_reap(self, db) -> None:
        """`REAP_ERROR` spends the reaper's failure budget and `run_coordinator` compares
        it verbatim to reconcile a run that turns out to be alive. An orphan is neither of
        those things and must not borrow the string."""
        from app.services.stale_run_reaper import REAP_ERROR

        assert ORPHAN_ERROR != REAP_ERROR


class TestTheWorkerCallsIt:
    def test_startup_sweeps_before_it_takes_jobs(self) -> None:
        import inspect
        import re

        from app import worker

        src = inspect.getsource(worker.startup)
        body = re.sub(r'"""[\s\S]*?"""', "", src)
        body = "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith("#"))
        assert "requeue_orphaned_runs" in body, (
            "the replacement worker does not put back what it replaced, so recovery waits "
            "300 s for the reaper and then spends a budget meant for real failures"
        )
