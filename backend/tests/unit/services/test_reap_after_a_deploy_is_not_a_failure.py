"""A run killed by a deploy has not failed, and must not spend the retry budget.

Measured on 2026-09-09, on production, and it was self-inflicted — which is what makes it
worth fixing rather than avoiding. Three full rebuilds of the one real project died in a
row that night. Their last heartbeats line up with the release list to the second:

    run 23:44:39   last beat 23:47:53   v352 at 23:47:54
    run 23:54:06   last beat 00:00:25   v353 at 00:00:45

Merged pull requests were landing on `main`, CI was going green, and the deploy workflow
restarted the dyno underneath a running index each time. The reaper did its job: those
runs really were dead.

What went wrong is what happened next. `StaleRunReaper._requeue` exists precisely to put
back the work a reap destroyed — but it is bounded at `reaper_requeue_max_attempts` (2)
per `reaper_requeue_window_hours` (6), counted from rows carrying `REAP_ERROR`. Two
deploys spent the whole budget, so the third reap was refused:

    Reaper: not re-enqueueing index_repo for project 38856e63 — 3 reaps in the last 6h
    is at the bound; the run is failing for its own reasons, not a restart.

It was wrong, and it could not have known: from its own data a run orphaned by a restart
and a run that hangs look identical. The vectors for that project had already been
dropped by `queue_embedding_reindex`, so "no rebuild queued" meant the customer's
retrieval degraded until somebody noticed by hand.

`_requeue_attempts` already draws exactly this distinction one level up — its docstring
says `REAP_ERROR` narrows the count to reaps because "a run that failed on its own merits
is a different fact and must not spend this budget". A deploy is another such fact, and
now there is a signal for it: the release the run started under, stamped on the run.

Degrades to today's behaviour when there is no signal (a self-hosted install has no
`HEROKU_RELEASE_VERSION`): unknown means counted, because a bound that cannot count stops
bounding.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.indexing_run import IndexingRun
from app.services.stale_run_reaper import REAP_ERROR, StaleRunReaper


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _reaped(db: AsyncSession, *, release: str | None, wf: str, minutes_ago: int = 5) -> None:
    meta: dict = {"force_full": True}
    if release is not None:
        meta["release"] = release
    db.add(
        IndexingRun(
            workflow_id=wf,
            project_id="p1",
            connection_id=None,
            kind="index_repo",
            trigger="schedule",
            status="failed",
            error=REAP_ERROR,
            step_index=0,
            total_steps=5,
            progress_pct=0,
            finished_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
            meta_json=json.dumps(meta),
        )
    )
    await db.commit()


class TestTheBudgetCountsFailuresNotDeploys:
    async def test_a_reap_under_the_current_release_is_counted(self, db) -> None:
        """The case the bound exists for: the run died and the process was never
        replaced, so whatever killed it is still there."""
        with patch("app.services.stale_run_reaper._current_release", return_value="v355"):
            await _reaped(db, release="v355", wf="w1")
            await _reaped(db, release="v355", wf="w2")
            assert await StaleRunReaper()._requeue_attempts(db, "p1", "index_repo") == 2

    async def test_a_reap_from_an_older_release_is_not_counted(self, db) -> None:
        """The production case. Both of these runs were orphaned by deploys; neither is
        evidence that the work itself fails."""
        with patch("app.services.stale_run_reaper._current_release", return_value="v355"):
            await _reaped(db, release="v352", wf="w1")
            await _reaped(db, release="v353", wf="w2")
            assert await StaleRunReaper()._requeue_attempts(db, "p1", "index_repo") == 0

    async def test_the_two_are_told_apart_in_one_window(self, db) -> None:
        """A deploy and a real hang inside the same six hours. Only the hang counts."""
        with patch("app.services.stale_run_reaper._current_release", return_value="v355"):
            await _reaped(db, release="v352", wf="w1")
            await _reaped(db, release="v355", wf="w2")
            assert await StaleRunReaper()._requeue_attempts(db, "p1", "index_repo") == 1

    async def test_a_run_with_no_release_stamp_is_counted(self, db) -> None:
        """Rows written before this change, and self-hosted installs. Unknown means
        counted: a bound that cannot count stops bounding, which is the same rule the
        error path in this method already follows."""
        with patch("app.services.stale_run_reaper._current_release", return_value="v355"):
            await _reaped(db, release=None, wf="w1")
            assert await StaleRunReaper()._requeue_attempts(db, "p1", "index_repo") == 1

    async def test_without_a_release_signal_nothing_changes(self, db) -> None:
        """A self-hosted install has no `HEROKU_RELEASE_VERSION`. With no current release
        to compare against, every reap counts — exactly today's behaviour."""
        with patch("app.services.stale_run_reaper._current_release", return_value=""):
            await _reaped(db, release="v352", wf="w1")
            await _reaped(db, release="v353", wf="w2")
            assert await StaleRunReaper()._requeue_attempts(db, "p1", "index_repo") == 2

    async def test_another_project_is_not_counted(self, db) -> None:
        with patch("app.services.stale_run_reaper._current_release", return_value="v355"):
            await _reaped(db, release="v355", wf="w1")
            assert await StaleRunReaper()._requeue_attempts(db, "p2", "index_repo") == 0


class TestARequeueThatDidNotHappenIsNotCounted:
    """The same defect as T11, in the reaper: `enqueue` returns None on failure rather
    than raising, and the count and the log line both said it had worked."""

    async def test_a_failed_enqueue_is_reported_as_one(self, db, caplog) -> None:
        import logging

        with (
            patch("app.core.task_queue.enqueue", new=AsyncMock(return_value=None)),
            patch("app.services.stale_run_reaper._current_release", return_value="v355"),
            caplog.at_level(logging.DEBUG),
        ):
            n = await StaleRunReaper()._requeue(
                db, [("r1", "p1", "index_repo", None, "graph_build")]
            )

        assert n == 0, "a re-enqueue that returned no job id was counted as done"
        assert [r for r in caplog.records if r.levelno >= logging.ERROR], (
            "the work was destroyed and not put back, and nothing said so above INFO"
        )

    async def test_a_successful_enqueue_still_counts(self, db) -> None:
        with (
            patch("app.core.task_queue.enqueue", new=AsyncMock(return_value="job-1")),
            patch("app.services.stale_run_reaper._current_release", return_value="v355"),
        ):
            n = await StaleRunReaper()._requeue(
                db, [("r1", "p1", "index_repo", None, "graph_build")]
            )
        assert n == 1


class TestTheRunRecordsWhatItStartedUnder:
    def test_the_coordinator_stamps_the_release(self) -> None:
        """Source-level: `start` needs a session, a manifest and a tracker. The property
        is that the stamp is written where the run is created — there is exactly one such
        place, which `test_run_exclusion_cross_process.py` pins."""
        import inspect
        import re

        from app.services import run_coordinator as mod

        src = inspect.getsource(mod.RunCoordinator.start)
        body = re.sub(r'"""[\s\S]*?"""', "", src)
        body = "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith("#"))
        assert '"release"' in body, (
            "the run does not record the release it started under, so a reap cannot tell "
            "a deploy from a hang"
        )
