"""F-SCHED-07: a retried batch job must not re-run the batch.

`execute_batch` set `status = "running"` with no reference to the current status,
and `run_batch` is registered bare in `WorkerSettings.functions`, so it inherits
ARQ's class-level `job_timeout` and its default `max_tries`. A job that fails — or
whose worker is SIGKILLed, which this deployment does under memory pressure — is
retried and re-executes every query in the batch from the top, overwriting
`results_json`. For a batch of writes against a read-write connection that is
duplicated work, not just wasted work.

A bare claim on `pending` alone would trade that for a worse bug: **nothing resets a
stuck `running` batch.** The stale-run reaper covers `IndexingRun` and does not know
about `batch_queries` (no reference to it anywhere in `stale_run_reaper.py` or
`reaper_loop.py`), so the first crashed attempt would strand the batch forever.

So the claim is stale-aware in one atomic UPDATE: take it from `pending`, or from a
`running` row whose attempt started longer ago than ARQ could possibly have kept it
alive. One statement, so two workers racing cannot both win.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.batch_query import BatchQuery
from app.services.batch_service import BatchService


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as s:
        yield s
    await engine.dispose()


async def _seed(session: AsyncSession, *, status: str, started_at=None) -> BatchQuery:
    b = BatchQuery(
        id=str(uuid.uuid4()),
        user_id=str(uuid.uuid4()),
        project_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        title="nightly",
        queries_json=json.dumps([{"sql": "SELECT 1"}]),
        status=status,
        started_at=started_at,
    )
    session.add(b)
    await session.commit()
    return b


async def _status(session: AsyncSession, batch_id: str) -> str:
    row = (await session.execute(select(BatchQuery).where(BatchQuery.id == batch_id))).scalar_one()
    await session.refresh(row)
    return row.status


class TestClaim:
    async def test_a_pending_batch_is_claimed_once(self, session: AsyncSession):
        b = await _seed(session, status="pending")
        svc = BatchService()
        assert await svc._claim_batch(session, b.id) is True
        assert await _status(session, b.id) == "running"
        # The second attempt — an ARQ retry — must not get the claim.
        assert await svc._claim_batch(session, b.id) is False

    async def test_a_completed_batch_is_never_reclaimed(self, session: AsyncSession):
        b = await _seed(session, status="completed")
        assert await BatchService()._claim_batch(session, b.id) is False
        assert await _status(session, b.id) == "completed"

    @pytest.mark.parametrize("terminal", ["failed", "partially_failed"])
    async def test_terminal_states_are_never_reclaimed(self, session, terminal):
        b = await _seed(session, status=terminal)
        assert await BatchService()._claim_batch(session, b.id) is False

    async def test_a_fresh_running_batch_is_left_alone(self, session: AsyncSession):
        """Another worker is plausibly still on it — do not double-run."""
        b = await _seed(session, status="running", started_at=datetime.now(UTC))
        assert await BatchService()._claim_batch(session, b.id) is False

    async def test_a_running_batch_older_than_arq_could_keep_alive_is_reclaimable(
        self, session: AsyncSession
    ):
        """Otherwise a crashed attempt strands the batch: nothing reaps batches."""
        long_ago = datetime.now(UTC) - timedelta(seconds=7200)
        b = await _seed(session, status="running", started_at=long_ago)
        assert await BatchService()._claim_batch(session, b.id) is True
        assert await _status(session, b.id) == "running"

    async def test_a_running_batch_with_no_start_time_is_reclaimable(self, session: AsyncSession):
        """Rows written before `started_at` existed must not be permanently stuck."""
        b = await _seed(session, status="running", started_at=None)
        assert await BatchService()._claim_batch(session, b.id) is True

    async def test_an_unknown_batch_is_refused(self, session: AsyncSession):
        assert await BatchService()._claim_batch(session, str(uuid.uuid4())) is False
