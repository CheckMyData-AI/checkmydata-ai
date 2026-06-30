"""Flag-snapshot provenance for IndexingRun (spec §3.5, plan T4).

When an :class:`IndexingRun` is created, the relevant feature-flag state is
snapshotted into ``meta_json["flags"]`` so a failed background/sync job is
diagnosable ("which flag produced this run?"). The snapshot must merge into the
existing ``meta_json`` (e.g. ``force_full``, ``retried_from``) without clobbering
those keys.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.config import settings
from app.models.base import Base
from app.services.run_coordinator import RunCoordinator

# The exact flag set the run snapshots (spec §3.5).
EXPECTED_FLAG_KEYS = {
    "git_webhook_enabled",
    "git_poll_enabled",
    "auto_sync_after_index",
    "freshness_reconciler_enabled",
    "schema_change_alerts_enabled",
    "db_index_incremental_enabled",
}


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


async def test_start_snapshots_flags_into_meta_json(session: AsyncSession):
    coord = RunCoordinator()
    run = await coord.start(
        session, kind="db_index", project_id="p1", connection_id="c1", trigger="manual"
    )
    meta = json.loads(run.meta_json)
    assert "flags" in meta, "meta_json must carry a 'flags' object"
    flags = meta["flags"]
    assert set(flags.keys()) == EXPECTED_FLAG_KEYS
    # Values mirror the live settings, and every value is a real bool.
    assert all(isinstance(v, bool) for v in flags.values())
    assert flags == {
        "git_webhook_enabled": settings.git_webhook_enabled,
        "git_poll_enabled": settings.git_poll_enabled,
        "auto_sync_after_index": settings.auto_sync_after_index,
        "freshness_reconciler_enabled": settings.freshness_reconciler_enabled,
        "schema_change_alerts_enabled": settings.schema_change_alerts_enabled,
        "db_index_incremental_enabled": settings.db_index_incremental_enabled,
    }


async def test_start_snapshot_does_not_clobber_existing_meta_keys(session: AsyncSession):
    coord = RunCoordinator()
    run = await coord.start(
        session, kind="db_index", project_id="p2", connection_id="c1", force_full=True
    )
    meta = json.loads(run.meta_json)
    # Pre-existing key survives the merge.
    assert meta["force_full"] is True
    # Snapshot is still present alongside it.
    assert set(meta["flags"].keys()) == EXPECTED_FLAG_KEYS


async def test_flag_snapshot_reflects_overridden_setting(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    # Flip a flag and confirm the snapshot captures the live value, not a constant.
    monkeypatch.setattr(settings, "auto_sync_after_index", True)
    monkeypatch.setattr(settings, "db_index_incremental_enabled", False)
    coord = RunCoordinator()
    run = await coord.start(session, kind="db_index", project_id="p3", connection_id="c1")
    flags = json.loads(run.meta_json)["flags"]
    assert flags["auto_sync_after_index"] is True
    assert flags["db_index_incremental_enabled"] is False


async def test_retry_preserves_flag_snapshot_and_provenance(session: AsyncSession):
    coord = RunCoordinator()
    run = await coord.start(session, kind="db_index", project_id="p4", connection_id="c1")
    await coord.finish(session, run, "failed", error="x", failure_kind="fatal")
    new = await coord.retry(session, run.id, force_full=True)
    meta = json.loads(new.meta_json)
    # Provenance keys from retry are kept.
    assert meta["retried_from"] == run.id
    assert meta["force_full"] is True
    # And the flag snapshot is not clobbered by retry's meta rewrite.
    assert set(meta["flags"].keys()) == EXPECTED_FLAG_KEYS
