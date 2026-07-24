"""Unit tests for worker run_code_db_sync logging."""

import sys
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_run_code_db_sync_logs_matched_from_synced_key(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that run_code_db_sync logs 'matched' from the 'synced' key (not 'synced_tables')."""
    # arq is not installed in the unit-test venv; stub it so importing
    # app.worker (whose WorkerSettings builds RedisSettings at class definition)
    # works regardless of which tests ran before this one.
    arq_stub = MagicMock()
    arq_stub.connections.RedisSettings = MagicMock(return_value=MagicMock())
    monkeypatch.setitem(sys.modules, "arq", arq_stub)
    monkeypatch.setitem(sys.modules, "arq.connections", arq_stub.connections)
    redis_tls_stub = MagicMock()
    redis_tls_stub.arq_redis_settings = MagicMock(return_value=MagicMock())
    monkeypatch.setitem(sys.modules, "app.core.redis_tls", redis_tls_stub)

    # Arrange: patch dependencies before importing worker
    mock_pipeline = AsyncMock()
    mock_pipeline.run.return_value = {
        "status": "completed",
        "total_tables": 3,
        "synced": 2,
        "code_only": 0,
        "db_only": 1,
        "mismatch": 0,
        "workflow_id": "wf-123",
    }

    # Create pipeline class factory
    mock_pipeline_class = lambda: mock_pipeline  # noqa: E731
    monkeypatch.setattr(
        "app.knowledge.code_db_sync_pipeline.CodeDbSyncPipeline",
        mock_pipeline_class,
    )

    # Patch the service calls (status setting)
    mock_sync_svc = AsyncMock()
    mock_sync_svc.set_sync_status = AsyncMock()

    def mock_service_factory():
        return mock_sync_svc

    monkeypatch.setattr(
        "app.services.code_db_sync_service.CodeDbSyncService",
        mock_service_factory,
    )

    # Mock async_session_factory as context manager
    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()

    mock_factory_ctx = AsyncMock()
    mock_factory_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory_ctx.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr(
        "app.models.base.async_session_factory",
        lambda: mock_factory_ctx,
    )

    # Act: call the worker function
    import logging

    from app.worker import run_code_db_sync

    caplog.set_level(logging.INFO)
    ctx = {}
    await run_code_db_sync(ctx, connection_id="conn-123", project_id="proj-456", wf_id="wf-123")

    # Assert: the log line contains matched=2 (not matched=None)
    assert any("matched=2" in record.message for record in caplog.records), (
        f"Expected 'matched=2' in logs, but got: {[r.message for r in caplog.records]}"
    )
    # Also verify it logs the table count
    assert any("tables=3" in record.message for record in caplog.records), (
        f"Expected 'tables=3' in logs, but got: {[r.message for r in caplog.records]}"
    )
