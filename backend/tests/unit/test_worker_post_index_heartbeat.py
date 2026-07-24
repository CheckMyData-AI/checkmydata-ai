"""RES-3: the post-index window (overview LLM + probes) runs at status
``running`` — it must stay covered by the heartbeat so a slow overview never
gets the live run reaped (which would let the start-guards dispatch a second,
duplicate index).
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.base import Base
from app.models.db_index import DbIndexSummary


@pytest.fixture
async def session(monkeypatch: pytest.MonkeyPatch, tmp_path) -> AsyncSession:
    # File-backed (not :memory:) so the heartbeat writer's concurrent sessions
    # share data without sharing a single StaticPool connection.
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("app.models.base.async_session_factory", sm)
    s = sm()
    try:
        yield s
    finally:
        await s.close()
        await engine.dispose()


async def test_post_index_steps_keep_heartbeat_alive(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    stale_hb = datetime.now(UTC) - timedelta(seconds=10_000)
    summary = DbIndexSummary(
        id=str(uuid4()), connection_id="conn-1", indexing_status="running", heartbeat_at=stale_hb
    )
    session.add(summary)
    await session.commit()

    mock_conn_svc = MagicMock()
    mock_conn_svc.get = AsyncMock(return_value=MagicMock())
    mock_conn_svc.to_config = AsyncMock(return_value=MagicMock())

    mock_pipeline = MagicMock()
    mock_pipeline.run = AsyncMock(return_value={"status": "completed", "tables": 2})

    heartbeat_during_post_index: list[datetime] = []

    async def _overview_and_probe(project_id: str, connection_id: str | None = None) -> None:
        # Post-index work outliving one heartbeat interval; mid-way, the
        # summary row must already be un-reapable again (reaper spares a
        # "running" row solely on heartbeat freshness — see StaleRunReaper).
        await asyncio.sleep(0.15)
        await session.refresh(summary)  # bypass the identity map; writer used its own sessions
        assert summary.indexing_status == "running"
        heartbeat_during_post_index.append(summary.heartbeat_at.replace(tzinfo=UTC))

    # arq is not installed in the unit-test venv; stub it so importing
    # app.worker (whose WorkerSettings builds RedisSettings at class definition)
    # doesn't blow up. Same pattern as test_schema_cache_registry.
    arq_stub = MagicMock()
    arq_stub.connections.RedisSettings = MagicMock(return_value=MagicMock())
    monkeypatch.setitem(sys.modules, "arq", arq_stub)
    monkeypatch.setitem(sys.modules, "arq.connections", arq_stub.connections)
    redis_tls_stub = MagicMock()
    redis_tls_stub.arq_redis_settings = MagicMock(return_value=MagicMock())
    monkeypatch.setitem(sys.modules, "app.core.redis_tls", redis_tls_stub)

    from app import worker
    from app.config import settings as real_settings

    monkeypatch.setattr(real_settings, "heartbeat_interval_seconds", 0.05)

    with (
        patch("app.services.connection_service.ConnectionService", return_value=mock_conn_svc),
        patch("app.knowledge.db_index_pipeline.DbIndexPipeline", return_value=mock_pipeline),
        patch(
            "app.api.routes.connections._regenerate_overview",
            new=AsyncMock(side_effect=_overview_and_probe),
        ),
        patch("app.api.routes.connections._run_data_probes", new=AsyncMock()),
    ):
        await worker.run_db_index({}, connection_id="conn-1", project_id="proj-1", wf_id="wf-1")

    # The row started with a heartbeat 10_000s in the past: without a
    # post-index heartbeat the reaper would have flipped it mid-flight.
    assert len(heartbeat_during_post_index) == 1
    assert heartbeat_during_post_index[0] > stale_hb
    await session.refresh(summary)
    assert summary.indexing_status == "completed"
