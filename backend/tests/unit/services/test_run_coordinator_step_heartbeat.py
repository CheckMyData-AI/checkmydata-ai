"""A step that outlives the reaper's timeout must not be killed while it is working.

`RunCoordinator.step` wrote `run.heartbeat_at` on entry (`run_coordinator.py:263`) and
again on success (`:280`) — and nothing in between. `IndexingRun` is what
`StaleRunReaper` reaps, so any single step running longer than
`stale_running_heartbeat_timeout_seconds` (300) was declared dead *while it was still
running*, and the row was flipped to `failed` with `error='stale run reaped'`.

In production that was not a rare race. 64 of 70 repo-index failures carried exactly
that error, all on `current_step='graph_build'`, every day from 2026-08-07 — the step
that walks 25 421 symbols. Runs with many short steps survived (417 s and 2 568 s both
completed), which is the signature of a per-step limit rather than a per-run one.

**The heartbeat that already existed was on the wrong row.** `_run_index_background`
(`repos.py:556-563`) ticks `IndexingCheckpoint`, so the checkpoint stayed alive while
the run beside it was reaped — which is why the failure never looked like a missing
heartbeat and went thirteen days without a diagnosis.

The fix belongs in `step` rather than in any one caller: `IndexingRun` is created and
finished here, and all four entry points into a repo index (the ARQ task, the manual
route, the retry route, the daily sync) reach the pipeline through this contextmanager.
Wrapping a caller would have covered one of the four and put a second heartbeat beside
the existing one.

The writer needs **its own session**: `db` belongs to the step's own work, and a
SQLAlchemy async session used from two tasks concurrently is a race, not a heartbeat.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 — register every model with Base
from app.models.base import Base
from app.models.indexing_run import IndexingRun
from app.services.run_coordinator import RunCoordinator
from app.services.stale_run_reaper import REAP_ERROR, StaleRunReaper

#: Short enough to keep the test near a second, long enough that a beat is not a
#: coincidence of scheduling.
BEAT = 0.05


@pytest.fixture
async def engine(tmp_path):
    """File-backed, not `:memory:`.

    Each `:memory:` connection is its own database, so a second session would see an
    empty schema — and this test's whole subject is what a *different* session observes
    while the step is still open.
    """
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'runs.db'}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
async def sessions(engine, monkeypatch):
    """A sessionmaker on the test database, installed where the coordinator looks."""
    sm = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("app.services.run_coordinator.async_session_factory", sm)
    monkeypatch.setattr("app.services.run_coordinator.settings.heartbeat_interval_seconds", BEAT)
    return sm


async def _observe(sm, run_id: str) -> datetime | None:
    """`heartbeat_at` as a *separate* session sees it — i.e. as the reaper would."""
    async with sm() as other:
        return (
            await other.execute(select(IndexingRun.heartbeat_at).where(IndexingRun.id == run_id))
        ).scalar_one()


async def test_heartbeat_advances_while_a_step_is_still_running(sessions):
    sm = sessions
    async with sm() as db:
        coord = RunCoordinator()
        run = await coord.start(db, kind="index_repo", project_id="p1", trigger="manual")

        async with coord.step(db, run, "graph_build"):
            before = await _observe(sm, run.id)
            assert before is not None, "entry beat should be committed before the body runs"
            await asyncio.sleep(BEAT * 6)
            during = await _observe(sm, run.id)

        assert during is not None
        assert during > before, (
            "heartbeat_at did not move while the step was running: the row goes stale "
            "under any step longer than the reaper's timeout, and the reaper then kills "
            "work that is still in progress"
        )


async def test_a_long_step_is_not_reaped(sessions):
    """The behaviour the production failure actually consisted of."""
    sm = sessions
    async with sm() as db:
        coord = RunCoordinator()
        run = await coord.start(db, kind="index_repo", project_id="p2", trigger="manual")

        async with coord.step(db, run, "graph_build"):
            # Age the row past the cutoff exactly as a long step would, then let the
            # heartbeat do its job before the reaper sweeps.
            async with sm() as aged:
                await aged.execute(
                    IndexingRun.__table__.update()
                    .where(IndexingRun.id == run.id)
                    .values(heartbeat_at=datetime.now(UTC) - timedelta(seconds=600))
                )
                await aged.commit()
            await asyncio.sleep(BEAT * 6)

            async with sm() as reaper_session:
                out = await StaleRunReaper().reap_once(reaper_session, timeout_seconds=300)
                await reaper_session.commit()

        assert out["runs"] == 0, "a heartbeating step was reaped as if it had crashed"
        row = await _observe(sm, run.id)
        assert row is not None
    async with sm() as check:
        fresh = (
            await check.execute(select(IndexingRun).where(IndexingRun.id == run.id))
        ).scalar_one()
        assert fresh.status != "failed"
        assert fresh.error != REAP_ERROR


async def test_the_beat_stops_when_the_step_does(sessions):
    """A heartbeat that outlives its step keeps a crashed run looking alive — the exact
    failure the reaper exists to catch, reintroduced by the fix for it."""
    sm = sessions
    async with sm() as db:
        coord = RunCoordinator()
        run = await coord.start(db, kind="index_repo", project_id="p3", trigger="manual")
        async with coord.step(db, run, "graph_build"):
            await asyncio.sleep(BEAT * 2)

        settled = await _observe(sm, run.id)
        await asyncio.sleep(BEAT * 6)
        assert await _observe(sm, run.id) == settled, (
            "heartbeat kept ticking after the step closed — a crashed run would stay "
            "immortal, which is worse than the bug being fixed"
        )
