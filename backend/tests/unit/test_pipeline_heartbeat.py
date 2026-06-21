"""Tests that heartbeat CM is wired into DbIndexPipeline and CodeDbSyncPipeline.

Strategy: spy on `app.knowledge.db_index_pipeline.heartbeat` and
`app.knowledge.code_db_sync_pipeline.heartbeat` to assert the CM is opened with
`interval_seconds=settings.heartbeat_interval_seconds`.  We let `run()` fail
fast (bad connection config / no DB index available) — the immediate first beat
in the heartbeat CM fires even before the body has a chance to fail, so one call
to the spy is guaranteed.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.config import settings
from app.connectors.base import ConnectionConfig


@pytest.fixture()
def bad_cfg() -> ConnectionConfig:
    """ConnectionConfig that will fail to connect (port 1 is never open)."""
    return ConnectionConfig(
        db_type="postgres",
        db_host="127.0.0.1",
        db_port=1,
        db_name="no_db",
        db_user="no_user",
        db_password="no_pass",
    )


# ---------------------------------------------------------------------------
# DbIndexPipeline
# ---------------------------------------------------------------------------


async def test_db_index_pipeline_uses_heartbeat(monkeypatch: pytest.MonkeyPatch, bad_cfg: Any):
    """DbIndexPipeline.run must open the heartbeat CM with the configured interval."""
    seen: dict[str, Any] = {"opened": False, "interval": None}

    import app.knowledge.db_index_pipeline as pipeline_mod
    from app.core.heartbeat import heartbeat as real_heartbeat

    def spy(writer, *, interval_seconds):  # type: ignore[no-untyped-def]
        seen["opened"] = True
        seen["interval"] = interval_seconds
        return real_heartbeat(writer, interval_seconds=interval_seconds)

    monkeypatch.setattr(pipeline_mod, "heartbeat", spy, raising=True)

    from app.knowledge.db_index_pipeline import DbIndexPipeline

    pipeline = DbIndexPipeline(db_index_batch_size=5)
    try:
        await pipeline.run(
            connection_id="test-conn-hb",
            connection_config=bad_cfg,
            project_id="test-proj-hb",
        )
    except Exception:
        pass

    assert seen["opened"] is True, "heartbeat CM was never opened by DbIndexPipeline.run"
    assert seen["interval"] == settings.heartbeat_interval_seconds, (
        f"Expected interval {settings.heartbeat_interval_seconds}, got {seen['interval']}"
    )


# ---------------------------------------------------------------------------
# CodeDbSyncPipeline
# ---------------------------------------------------------------------------


async def test_code_db_sync_pipeline_uses_heartbeat(monkeypatch: pytest.MonkeyPatch):
    """CodeDbSyncPipeline.run must open the heartbeat CM with the configured interval."""
    seen: dict[str, Any] = {"opened": False, "interval": None}

    import app.knowledge.code_db_sync_pipeline as sync_mod
    from app.core.heartbeat import heartbeat as real_heartbeat

    def spy(writer, *, interval_seconds):  # type: ignore[no-untyped-def]
        seen["opened"] = True
        seen["interval"] = interval_seconds
        return real_heartbeat(writer, interval_seconds=interval_seconds)

    monkeypatch.setattr(sync_mod, "heartbeat", spy, raising=True)

    # CodeDbSyncPipeline fails fast because there is no code knowledge or DB
    # index for the dummy IDs — but the heartbeat CM must have been entered first.
    from app.knowledge.code_db_sync_pipeline import CodeDbSyncPipeline

    pipeline = CodeDbSyncPipeline()
    try:
        await pipeline.run(
            connection_id="test-conn-sync-hb",
            project_id="test-proj-sync-hb",
        )
    except Exception:
        pass

    assert seen["opened"] is True, "heartbeat CM was never opened by CodeDbSyncPipeline.run"
    assert seen["interval"] == settings.heartbeat_interval_seconds, (
        f"Expected interval {settings.heartbeat_interval_seconds}, got {seen['interval']}"
    )
