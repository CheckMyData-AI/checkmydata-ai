"""FA-008/RES-2: the pipeline runner must tick the ``IndexingRun`` heartbeat
*inside* long emit-less steps (clone_or_pull, ast_parse, code_symbol_embed,
bm25_build), so a live run is never flipped by the stale-run reaper.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.knowledge.pipeline_runner import IndexingPipelineRunner, PipelineResult
from app.models.base import Base
from app.models.indexing_run import IndexingRun
from app.services.stale_run_reaper import StaleRunReaper


@pytest.fixture
async def session(monkeypatch: pytest.MonkeyPatch) -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    # The heartbeat writer opens its own session via the module-level factory.
    monkeypatch.setattr("app.knowledge.pipeline_runner.async_session_factory", sm)
    # Sub-second beat so the test doesn't take 30s.
    monkeypatch.setattr(
        "app.knowledge.pipeline_runner.settings",
        SimpleNamespace(heartbeat_interval_seconds=0.05),
    )
    s = sm()
    s.info["sessionmaker"] = sm
    try:
        yield s
    finally:
        await s.close()
        await engine.dispose()


def _make_runner() -> IndexingPipelineRunner:
    return IndexingPipelineRunner(
        ssh_key_svc=MagicMock(),
        git_tracker=MagicMock(),
        repo_analyzer=MagicMock(),
        doc_store=MagicMock(),
        doc_generator=MagicMock(),
        vector_store=MagicMock(),
        cache_svc=MagicMock(),
        checkpoint_svc=MagicMock(),
    )


async def test_heartbeat_ticks_during_long_step(session: AsyncSession):
    stale_hb = datetime.now(UTC) - timedelta(seconds=10_000)
    run = IndexingRun(
        workflow_id="wf-hb",
        project_id="proj-1",
        connection_id=None,
        kind="index_repo",
        trigger="manual",
        status="running",
        started_at=stale_hb,
        heartbeat_at=stale_hb,
    )
    session.add(run)
    await session.commit()

    sm_probe = session.info["sessionmaker"]
    runner = _make_runner()
    runner._cp_svc.get_completed_steps = AsyncMock(return_value=set())

    async def _slow_steps(**kwargs) -> PipelineResult:
        """Stay inside the step until the heartbeat has *actually* been written.

        This used to `sleep(0.3)` and trust that a 0.05 s beat had fired in the
        meantime. That is a wall-clock wait for someone else's scheduling, and it
        failed roughly 1 run in 10 when other pytest processes shared the machine --
        the failure that skipped a deploy in m0 (C21) and again on 2026-08-08. Tuning
        SQLite (WAL + busy timeout, c5c6460) could not fix it, because the contended
        resource was the scheduler and the disk, not a database lock.

        Waiting on the condition instead removes the race entirely: the step ends when
        the heartbeat has moved, or the test fails on a ceiling generous enough that
        only a genuinely broken heartbeat can hit it.
        """
        deadline = asyncio.get_running_loop().time() + 10.0
        while asyncio.get_running_loop().time() < deadline:
            async with sm_probe() as probe:
                current = await probe.get(IndexingRun, run.id)
                if current is not None:
                    beat = current.heartbeat_at
                    if beat is not None and beat.replace(tzinfo=UTC) > stale_hb:
                        return PipelineResult(status="completed")
            await asyncio.sleep(0.01)
        raise AssertionError(
            "the heartbeat never advanced within 10s -- this is the real defect the "
            "test exists to catch, not a timing artefact"
        )

    runner._run_steps = AsyncMock(side_effect=_slow_steps)

    result = await runner.run(
        "proj-1",
        MagicMock(),
        False,
        AsyncMock(),
        "wf-hb",
        MagicMock(id="cp-1"),
    )

    assert result.status == "completed"
    await session.refresh(run)
    assert run.heartbeat_at is not None
    assert run.heartbeat_at.replace(tzinfo=UTC) > stale_hb

    # And the corollary: the reaper must leave this live run alone.
    session.expunge(run)  # keep the bulk UPDATE evaluator off naive SQLite datetimes
    out = await StaleRunReaper().reap_once(session, timeout_seconds=300)
    assert out["runs"] == 0
    fresh = await session.get(IndexingRun, run.id)
    assert fresh is not None
    assert fresh.status == "running"
