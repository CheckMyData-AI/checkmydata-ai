"""Unit tests for app.core.schema_cache_registry.

Tests:
- invalidate_connection clears matching keys and leaves others intact
- dead (GC'd) weakrefs are pruned without crashing
- run_db_index completion calls invalidate_connection (call-site wiring)
"""

from __future__ import annotations

import gc

import pytest

from app.core.schema_cache_registry import invalidate_connection, register_schema_cache, reset
from app.core.ttl_cache import TTLCache

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeAgent:
    def __init__(self) -> None:
        self._schema_cache: TTLCache[str, object] = TTLCache(ttl=300.0, max_size=8)


# ---------------------------------------------------------------------------
# Registry semantics
# ---------------------------------------------------------------------------


def test_invalidate_clears_matching_connection() -> None:
    reset()
    a = FakeAgent()
    a._schema_cache.put("postgres:h:5432:db:False:cid=conn-1", object())
    a._schema_cache.put("postgres:h:5432:db:False:cid=conn-2", object())
    register_schema_cache(a)

    cleared = invalidate_connection("conn-1")

    assert cleared >= 1
    assert a._schema_cache.get("postgres:h:5432:db:False:cid=conn-1") is None
    assert a._schema_cache.get("postgres:h:5432:db:False:cid=conn-2") is not None


def test_dead_owner_pruned() -> None:
    reset()
    a = FakeAgent()
    register_schema_cache(a)
    del a
    gc.collect()

    # No live owners → no crash, returns 0
    assert invalidate_connection("x") == 0


def test_invalidate_different_connection_untouched() -> None:
    """Entries for an unrelated connection_id are never removed."""
    reset()
    a = FakeAgent()
    sentinel = object()
    a._schema_cache.put("postgres:h:5432:db:False:cid=conn-99", sentinel)
    register_schema_cache(a)

    cleared = invalidate_connection("conn-1")

    assert cleared == 0
    assert a._schema_cache.get("postgres:h:5432:db:False:cid=conn-99") is sentinel


def test_multiple_agents_all_invalidated() -> None:
    """invalidate_connection clears the same connection in every registered agent."""
    reset()
    a1 = FakeAgent()
    a2 = FakeAgent()
    key = "postgres:h:5432:db:False:cid=conn-42"
    sentinel1 = object()
    sentinel2 = object()
    a1._schema_cache.put(key, sentinel1)
    a2._schema_cache.put(key, sentinel2)
    register_schema_cache(a1)
    register_schema_cache(a2)

    cleared = invalidate_connection("conn-42")

    assert cleared == 2
    assert a1._schema_cache.get(key) is None
    assert a2._schema_cache.get(key) is None


def test_reset_clears_all_registrations() -> None:
    reset()
    a = FakeAgent()
    register_schema_cache(a)
    reset()

    # After reset no entries should be touched
    a._schema_cache.put("postgres:h:5432:db:False:cid=conn-1", object())
    cleared = invalidate_connection("conn-1")
    assert cleared == 0


def test_invalidate_empty_registry() -> None:
    reset()
    # Must not raise even with nothing registered
    assert invalidate_connection("conn-anything") == 0


def test_custom_cache_attr() -> None:
    """register_schema_cache supports a custom cache attribute name."""
    reset()

    class AgentWithOtherAttr:
        def __init__(self) -> None:
            self.my_cache: TTLCache[str, object] = TTLCache(ttl=300.0, max_size=8)

    a = AgentWithOtherAttr()
    key = "mysql:h:3306:db:False:cid=conn-7"
    a.my_cache.put(key, object())
    register_schema_cache(a, cache_attr="my_cache")

    cleared = invalidate_connection("conn-7")

    assert cleared >= 1
    assert a.my_cache.get(key) is None


# ---------------------------------------------------------------------------
# Call-site wiring: worker.run_db_index calls invalidate_connection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_db_index_calls_invalidate_on_success(monkeypatch) -> None:
    """run_db_index must call invalidate_connection(connection_id) on success.

    We import the function directly (not the module) to avoid triggering the
    module-level ``WorkerSettings`` class which calls ``arq.connections`` at
    import time — arq is not installed in the unit-test environment.
    """
    import sys
    from unittest.mock import AsyncMock, MagicMock, patch

    invalidated: list[str] = []

    def fake_invalidate(cid: str) -> int:
        invalidated.append(cid)
        return 0

    # arq is not installed in the test venv; stub it before any import of worker
    arq_stub = MagicMock()
    arq_conn_stub = MagicMock()
    arq_conn_stub.RedisSettings = MagicMock(return_value=MagicMock())
    arq_stub.connections = arq_conn_stub
    monkeypatch.setitem(sys.modules, "arq", arq_stub)
    monkeypatch.setitem(sys.modules, "arq.connections", arq_conn_stub)

    # Also stub redis_tls so WorkerSettings doesn't blow up
    redis_tls_stub = MagicMock()
    redis_tls_stub.arq_redis_settings = MagicMock(return_value=MagicMock())
    monkeypatch.setitem(sys.modules, "app.core.redis_tls", redis_tls_stub)

    # Remove worker from sys.modules so our stubs take effect on fresh import
    monkeypatch.delitem(sys.modules, "app.worker", raising=False)

    with (
        patch("app.core.schema_cache_registry.invalidate_connection", side_effect=fake_invalidate),
        patch("app.models.base.async_session_factory") as mock_factory,
        patch("app.services.connection_service.ConnectionService") as mock_conn_svc_cls,
        patch("app.services.db_index_service.DbIndexService") as mock_idx_svc_cls,
        patch("app.config.settings") as mock_settings,
        patch("app.knowledge.db_index_pipeline.DbIndexPipeline") as mock_pipeline_cls,
        patch("app.api.routes.connections._regenerate_overview", new=AsyncMock()),
        patch("app.api.routes.connections._run_data_probes", new=AsyncMock()),
    ):
        # async_session_factory async context manager
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_factory.return_value = mock_session

        # ConnectionService.get → return a fake connection
        fake_conn = MagicMock()
        mock_conn_svc_cls.return_value.get = AsyncMock(return_value=fake_conn)
        mock_conn_svc_cls.return_value.to_config = AsyncMock(return_value=MagicMock())

        # DbIndexService
        mock_idx_svc_cls.return_value.set_indexing_status = AsyncMock()

        # Pipeline returns success
        mock_settings.db_index_batch_size = 100
        mock_pipeline = AsyncMock()
        mock_pipeline.run = AsyncMock(return_value={"tables": 5})
        mock_pipeline_cls.return_value = mock_pipeline

        import app.worker as worker_module

        await worker_module.run_db_index(
            {},
            connection_id="conn-abc",
            project_id="proj-1",
            wf_id="wf-1",
        )

    assert "conn-abc" in invalidated, (
        "run_db_index must call invalidate_connection(connection_id) on completion"
    )
