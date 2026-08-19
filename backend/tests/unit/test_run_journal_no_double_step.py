"""AUD-0819-21: one step completion, one journal row.

Eight of the pipeline's fourteen steps announce their own terminal event *and*
run inside `tracker.step`, whose context manager emits a second one — measured:

    ast_parse, code_symbol_embed, cross_file_analysis, detect_changes,
    graph_build, graph_clustering, graph_db_bridge, project_profile

Production, 2026-08-19, one step and two completions milliseconds apart:

    11:54:55.697 workflow[25123ca3] graph_build: completed (Persisted 25161 …)
    11:54:55.701 workflow[25123ca3] graph_build: completed (Building code gr…)

`_apply_event` writes an `IndexingRunEvent` and bumps `run.version` on every
`completed`, so the run detail an operator reads in the Runs tab (SCN-107) showed
each of those eight steps twice. Fixing the eight emitters is a change to the
pipeline's event contract and belongs on its own; the durable artifact is made
idempotent here, at one site, because that is the half a reader sees.

A genuine re-run must still journal twice, and it always emits `started` first —
so the guard compares against the immediately-preceding row only.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.base import Base
from app.models.indexing_run import IndexingRunEvent
from app.services.run_coordinator import RunCoordinator


@pytest.fixture
async def session() -> AsyncSession:
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


async def _rows(session: AsyncSession, run_id: str) -> list[IndexingRunEvent]:
    stmt = select(IndexingRunEvent).where(IndexingRunEvent.run_id == run_id)
    return list((await session.execute(stmt)).scalars().all())


async def test_a_repeated_step_completion_writes_one_row(session: AsyncSession):
    coord = RunCoordinator()
    run = await coord.start(session, kind="index_repo", project_id="p1")
    await coord._journal(session, run, "graph_build", "started", "Building code graph")
    await coord._journal(session, run, "graph_build", "completed", "Persisted 25161 symbols")
    await coord._journal(session, run, "graph_build", "completed", "Building code graph")

    completions = [
        r
        for r in await _rows(session, run.id)
        if r.step == "graph_build" and r.status == "completed"
    ]
    assert len(completions) == 1, f"the step was journalled {len(completions)} times"
    # The row that survives is the informative one, not the echo of the start label.
    assert completions[0].detail == "Persisted 25161 symbols"


async def test_a_genuine_rerun_still_journals_twice(session: AsyncSession):
    """A retried step emits `started` again, which breaks the adjacency."""
    coord = RunCoordinator()
    run = await coord.start(session, kind="index_repo", project_id="p2")
    await coord._journal(session, run, "bm25_build", "started", "first")
    await coord._journal(session, run, "bm25_build", "completed", "first done")
    await coord._journal(session, run, "bm25_build", "started", "retry")
    await coord._journal(session, run, "bm25_build", "completed", "retry done")

    completions = [r for r in await _rows(session, run.id) if r.status == "completed"]
    assert len(completions) == 2


async def test_different_steps_are_never_collapsed(session: AsyncSession):
    coord = RunCoordinator()
    run = await coord.start(session, kind="index_repo", project_id="p3")
    await coord._journal(session, run, "ast_parse", "completed", "a")
    await coord._journal(session, run, "graph_build", "completed", "b")
    steps = {r.step for r in await _rows(session, run.id) if r.status == "completed"}
    assert steps == {"ast_parse", "graph_build"}


async def test_a_failure_after_a_completion_is_kept(session: AsyncSession):
    """Same step, different status — two distinct facts, both must survive."""
    coord = RunCoordinator()
    run = await coord.start(session, kind="index_repo", project_id="p4")
    await coord._journal(session, run, "graph_build", "completed", "ok")
    await coord._journal(session, run, "graph_build", "failed", "then it broke", level="error")
    rows = [r for r in await _rows(session, run.id) if r.step == "graph_build"]
    assert {r.status for r in rows} == {"completed", "failed"}
