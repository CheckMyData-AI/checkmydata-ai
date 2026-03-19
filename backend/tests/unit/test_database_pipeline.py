"""Unit tests for DatabasePipeline."""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.pipelines.base import PipelineContext
from app.pipelines.database_pipeline import DatabasePipeline


@pytest.fixture
def pipeline():
    return DatabasePipeline()


@pytest.fixture
def ctx():
    return PipelineContext(project_id="proj-1", workflow_id="wf-1", force_full=False)


def _mock_module(**attrs):
    """Create a mock module with the given attributes."""
    mod = MagicMock()
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


class AsyncCtx:
    def __init__(self, value):
        self._value = value

    async def __aenter__(self):
        return self._value

    async def __aexit__(self, *args):
        pass


class TestDatabasePipelineIndex:
    @pytest.mark.asyncio
    async def test_index_delegates_to_db_index_pipeline(self, pipeline, ctx):
        mock_run = AsyncMock()
        mock_session = AsyncMock()
        mock_pipeline_cls = MagicMock(return_value=MagicMock(run=mock_run))
        mock_conn = MagicMock()
        mock_conn_svc_cls = MagicMock()
        mock_conn_svc_inst = MagicMock()
        mock_conn_svc_inst.get = AsyncMock(return_value=mock_conn)
        mock_conn_svc_inst.to_config = AsyncMock(return_value=MagicMock())
        mock_conn_svc_cls.return_value = mock_conn_svc_inst

        mods = {
            "app.knowledge.db_index_pipeline": _mock_module(DbIndexPipeline=mock_pipeline_cls),
            "app.services.connection_service": _mock_module(ConnectionService=mock_conn_svc_cls),
        }
        with (
            patch.dict(sys.modules, mods),
            patch("app.models.base.async_session_factory", return_value=AsyncCtx(mock_session)),
        ):
            result = await pipeline.index("conn-1", ctx)

        assert result.success is True
        mock_run.assert_awaited_once()
        call_kwargs = mock_run.await_args.kwargs
        assert call_kwargs["connection_id"] == "conn-1"
        assert call_kwargs["project_id"] == "proj-1"

    @pytest.mark.asyncio
    async def test_index_error_propagates(self, pipeline, ctx):
        mock_run = AsyncMock(side_effect=RuntimeError("boom"))
        mock_session = AsyncMock()
        mock_pipeline_cls = MagicMock(return_value=MagicMock(run=mock_run))
        mock_conn = MagicMock()
        mock_conn_svc_cls = MagicMock()
        mock_conn_svc_inst = MagicMock()
        mock_conn_svc_inst.get = AsyncMock(return_value=mock_conn)
        mock_conn_svc_inst.to_config = AsyncMock(return_value=MagicMock())
        mock_conn_svc_cls.return_value = mock_conn_svc_inst

        mods = {
            "app.knowledge.db_index_pipeline": _mock_module(DbIndexPipeline=mock_pipeline_cls),
            "app.services.connection_service": _mock_module(ConnectionService=mock_conn_svc_cls),
        }
        with (
            patch.dict(sys.modules, mods),
            patch("app.models.base.async_session_factory", return_value=AsyncCtx(mock_session)),
        ):
            result = await pipeline.index("conn-1", ctx)

        assert result.success is False
        assert "boom" in result.error


class TestDatabasePipelineSyncWithCode:
    @pytest.mark.asyncio
    async def test_sync_with_code_delegates(self, pipeline, ctx):
        mock_run = AsyncMock()
        mock_pipeline_cls = MagicMock(return_value=MagicMock(run=mock_run))

        mods = {
            "app.knowledge.code_db_sync_pipeline": _mock_module(
                CodeDbSyncPipeline=mock_pipeline_cls
            ),
        }
        with patch.dict(sys.modules, mods):
            result = await pipeline.sync_with_code("conn-1", ctx)

        assert result.success is True
        mock_run.assert_awaited_once_with(
            connection_id="conn-1",
            project_id="proj-1",
        )


class TestDatabasePipelineGetStatus:
    def _status_mods(self, mock_db_svc, mock_sync_svc):
        return {
            "app.services.db_index_service": _mock_module(
                DbIndexService=MagicMock(return_value=mock_db_svc)
            ),
            "app.services.code_db_sync_service": _mock_module(
                CodeDbSyncService=MagicMock(return_value=mock_sync_svc)
            ),
        }

    @pytest.mark.asyncio
    async def test_get_status_combines_index_and_sync(self, pipeline):
        mock_session = AsyncMock()
        mock_db_svc = MagicMock()
        mock_db_svc.is_indexed = AsyncMock(return_value=True)
        mock_db_svc.is_stale = AsyncMock(return_value=False)
        mock_db_svc.get_index = AsyncMock(return_value=["e1", "e2", "e3"])
        mock_sync_svc = MagicMock()
        mock_sync_svc.is_synced = AsyncMock(return_value=True)

        mods = self._status_mods(mock_db_svc, mock_sync_svc)

        with (
            patch("app.models.base.async_session_factory", return_value=AsyncCtx(mock_session)),
            patch.dict(sys.modules, mods),
            patch("app.config.settings", MagicMock(db_index_ttl_hours=24)),
        ):
            status = await pipeline.get_status("conn-1")

        assert status.is_indexed is True
        assert status.is_synced is True
        assert status.is_stale is False
        assert status.items_count == 3

    @pytest.mark.asyncio
    async def test_get_status_no_index(self, pipeline):
        mock_session = AsyncMock()
        mock_db_svc = MagicMock()
        mock_db_svc.is_indexed = AsyncMock(return_value=False)
        mock_sync_svc = MagicMock()

        mods = self._status_mods(mock_db_svc, mock_sync_svc)

        with (
            patch("app.models.base.async_session_factory", return_value=AsyncCtx(mock_session)),
            patch.dict(sys.modules, mods),
        ):
            status = await pipeline.get_status("conn-1")

        assert status.is_indexed is False
        assert status.is_synced is False
        assert status.items_count == 0

    @pytest.mark.asyncio
    async def test_get_status_no_sync(self, pipeline):
        mock_session = AsyncMock()
        mock_db_svc = MagicMock()
        mock_db_svc.is_indexed = AsyncMock(return_value=True)
        mock_db_svc.is_stale = AsyncMock(return_value=True)
        mock_db_svc.get_index = AsyncMock(return_value=["e1"])
        mock_sync_svc = MagicMock()
        mock_sync_svc.is_synced = AsyncMock(return_value=False)

        mods = self._status_mods(mock_db_svc, mock_sync_svc)

        with (
            patch("app.models.base.async_session_factory", return_value=AsyncCtx(mock_session)),
            patch.dict(sys.modules, mods),
            patch("app.config.settings", MagicMock(db_index_ttl_hours=24)),
        ):
            status = await pipeline.get_status("conn-1")

        assert status.is_indexed is True
        assert status.is_synced is False
        assert status.is_stale is True
        assert status.items_count == 1


class TestDatabasePipelineProperties:
    def test_source_type_property(self, pipeline):
        assert pipeline.source_type == "database"

    def test_constructor_stores_config(self):
        p = DatabasePipeline()
        assert isinstance(p, DatabasePipeline)
        assert p.source_type == "database"
