"""A run the reaper kills has to reach the error log, because nothing else will.

`error_log` is the product's own record of what is going wrong — it is what
`/api/logs` reads and what an operator looks at before they look at a platform's log
retention. On 2026-08-23 it held **three rows**, the newest from 2026-08-17, while
`indexing_runs` held **143** with `status='failed'`. The single most frequent
production failure this system has was absent from the one place built to show it.

The reason is structural rather than an oversight. `RunCoordinator` writes to the
catalog in three places (`run_coordinator.py:317`, `:450`, `:485`) and every one of them
sits on a *terminal-event* path — `finish`, or a pipeline reporting its own end. The
reaper does neither: it issues a bulk `UPDATE ... SET status='failed'`
(`stale_run_reaper.py:116-125`) against rows whose process is gone, so no terminal event
is ever emitted and no writer is ever reached. A row died and the catalog was never told.

The message carries the step. `stale run reaped` alone aggregates every reaped run of a
kind into one line; with the step it separates, and separating is what turned this from
a shrug into a diagnosis — 64 of 70 failures were `graph_build` specifically, and that
ratio is the whole reason the cause was findable. The product should be able to say that
without an auditor doing it by hand.

The run's own `error` column stays exactly `REAP_ERROR`: `run_coordinator.py:393`
compares against it verbatim to recognise a reaped run and reconcile it if the pipeline
turns out to still be alive. The catalog message is a different field and free to be
more useful.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 — register every model with Base
from app.models.base import Base
from app.models.error_log import ErrorLog
from app.models.indexing_run import IndexingRun
from app.services.stale_run_reaper import REAP_ERROR, StaleRunReaper

STALE = timedelta(seconds=600)


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    s = sm()
    try:
        yield s
    finally:
        await s.close()
        await engine.dispose()


def _run(project_id: str, *, step: str, kind: str = "index_repo", status: str = "running"):
    return IndexingRun(
        workflow_id=f"wf-{project_id}-{step}",
        project_id=project_id,
        kind=kind,
        trigger="cron",
        status=status,
        current_step=step,
        step_index=1,
        total_steps=15,
        progress_pct=10,
        started_at=datetime.now(UTC) - STALE,
        heartbeat_at=datetime.now(UTC) - STALE,
    )


async def _errors(session) -> list[ErrorLog]:
    return list((await session.execute(select(ErrorLog))).scalars().all())


async def test_a_reaped_run_reaches_the_error_log(session):
    session.add(_run("p1", step="graph_build"))
    await session.commit()

    out = await StaleRunReaper().reap_once(session, timeout_seconds=300)
    await session.commit()
    assert out["runs"] == 1

    rows = await _errors(session)
    assert len(rows) == 1, (
        "the reaper killed a run and the product's own error catalog was never told — "
        "this is why 143 failed runs produced 3 catalog rows"
    )
    assert rows[0].source == "run"
    assert rows[0].kind == "index_repo"
    assert rows[0].failure_kind == "fatal"
    assert rows[0].project_id == "p1"


async def test_the_message_names_the_step_that_died(session):
    """Without the step, every reaped run of a kind collapses to one line and the
    64-of-70 concentration that made the cause findable is not visible."""
    session.add(_run("p1", step="graph_build"))
    session.add(_run("p2", step="generate_docs"))
    await session.commit()

    await StaleRunReaper().reap_once(session, timeout_seconds=300)
    await session.commit()

    by_project = {r.project_id: r for r in await _errors(session)}
    assert "graph_build" in by_project["p1"].message
    assert "generate_docs" in by_project["p2"].message
    assert REAP_ERROR in by_project["p1"].message


async def test_repeats_aggregate_rather_than_pile_up(session):
    """Daily since 2026-08-07 is 64 occurrences of one problem, not 64 problems."""
    reaper = StaleRunReaper()
    for i in range(3):
        session.add(_run("p1", step="graph_build"))
        # a distinct workflow_id per attempt, same shape
        await session.commit()
        await reaper.reap_once(session, timeout_seconds=300)
        await session.commit()
        for run in (await session.execute(select(IndexingRun))).scalars().all():
            run.workflow_id = f"{run.workflow_id}-{i}"
        await session.commit()

    rows = await _errors(session)
    assert len(rows) == 1, f"one recurring failure should be one row, got {len(rows)}"
    assert rows[0].occurrences == 3


async def test_the_runs_error_column_is_left_exactly_as_the_reaper_wrote_it(session):
    """`run_coordinator.py:393` compares `run.error == REAP_ERROR` verbatim to recognise
    a reaped run and reconcile it when the pipeline turns out to be alive. Enriching that
    column instead of the catalog message would break reconciliation silently."""
    session.add(_run("p1", step="graph_build"))
    await session.commit()

    await StaleRunReaper().reap_once(session, timeout_seconds=300)
    await session.commit()

    run = (await session.execute(select(IndexingRun))).scalar_one()
    assert run.error == REAP_ERROR
    assert run.failure_kind == "fatal"


async def test_a_cancelled_run_is_not_catalogued_as_an_error(session):
    """`cancelling` → `cancelled` is somebody's decision, not a failure."""
    session.add(_run("p1", step="graph_build", status="cancelling"))
    await session.commit()

    out = await StaleRunReaper().reap_once(session, timeout_seconds=300)
    await session.commit()

    assert out["runs"] == 1
    assert await _errors(session) == []


async def test_the_catalogued_row_can_be_traced_back_to_a_run(session):
    session.add(_run("p1", step="graph_build"))
    await session.commit()
    await StaleRunReaper().reap_once(session, timeout_seconds=300)
    await session.commit()

    run = (await session.execute(select(IndexingRun))).scalar_one()
    row = (await _errors(session))[0]
    assert row.sample_ref == run.id
    assert json.loads(row.meta_json).get("current_step") == "graph_build"
