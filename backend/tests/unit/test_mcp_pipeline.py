"""Unit tests for MCPPipeline."""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.pipelines.base import PipelineContext
from app.pipelines.mcp_pipeline import MCPPipeline


@pytest.fixture
def pipeline():
    return MCPPipeline()


@pytest.fixture
def ctx():
    return PipelineContext(project_id="proj-1", workflow_id="wf-1")


def _make_conn(source_type="mcp", name="my-mcp", project_id="proj-1"):
    conn = MagicMock()
    conn.source_type = source_type
    conn.name = name
    conn.project_id = project_id
    return conn


def _mock_module(**attrs):
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


class TestMCPPipelineIndex:
    @pytest.mark.asyncio
    async def test_index_connects_and_stores_schemas(self, pipeline, ctx):
        schemas = [
            {"name": "tool_a", "description": "Tool A", "input_schema": {"type": "object"}},
            {"name": "tool_b", "description": "Tool B", "input_schema": {}},
        ]
        conn = _make_conn()
        mock_session = AsyncMock()
        mock_conn_svc = MagicMock()
        mock_conn_svc.get = AsyncMock(return_value=conn)
        mock_conn_svc.to_config = AsyncMock(return_value={"url": "http://mcp"})

        mock_adapter = MagicMock()
        mock_adapter.connect = AsyncMock()
        mock_adapter.disconnect = AsyncMock()
        mock_adapter.get_tool_schemas = MagicMock(return_value=schemas)

        mock_collection = MagicMock()
        mock_vs = MagicMock()
        mock_vs.get_or_create_collection = MagicMock(return_value=mock_collection)

        mods = {
            "app.connectors.mcp_client": _mock_module(
                MCPClientAdapter=MagicMock(return_value=mock_adapter),
            ),
            "app.services.connection_service": _mock_module(
                ConnectionService=MagicMock(return_value=mock_conn_svc),
            ),
            "app.knowledge.vector_store": _mock_module(
                VectorStore=MagicMock(return_value=mock_vs),
            ),
        }

        with (
            patch.dict(sys.modules, mods),
            patch("app.models.base.async_session_factory", return_value=AsyncCtx(mock_session)),
        ):
            result = await pipeline.index("conn-1", ctx)

        assert result.success is True
        assert result.items_processed == 2
        assert "tool_a" in result.metadata["tools"]
        assert "tool_b" in result.metadata["tools"]
        mock_adapter.connect.assert_awaited_once()
        mock_adapter.disconnect.assert_awaited_once()
        mock_collection.upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_index_no_tools(self, pipeline, ctx):
        conn = _make_conn()
        mock_session = AsyncMock()
        mock_conn_svc = MagicMock()
        mock_conn_svc.get = AsyncMock(return_value=conn)
        mock_conn_svc.to_config = AsyncMock(return_value={})

        mock_adapter = MagicMock()
        mock_adapter.connect = AsyncMock()
        mock_adapter.disconnect = AsyncMock()
        mock_adapter.get_tool_schemas = MagicMock(return_value=[])

        mods = {
            "app.connectors.mcp_client": _mock_module(
                MCPClientAdapter=MagicMock(return_value=mock_adapter),
            ),
            "app.services.connection_service": _mock_module(
                ConnectionService=MagicMock(return_value=mock_conn_svc),
            ),
        }

        with (
            patch.dict(sys.modules, mods),
            patch("app.models.base.async_session_factory", return_value=AsyncCtx(mock_session)),
        ):
            result = await pipeline.index("conn-1", ctx)

        assert result.success is True
        assert result.items_processed == 0

    @pytest.mark.asyncio
    async def test_index_connection_failure(self, pipeline, ctx):
        conn = _make_conn()
        mock_session = AsyncMock()
        mock_conn_svc = MagicMock()
        mock_conn_svc.get = AsyncMock(return_value=conn)
        mock_conn_svc.to_config = AsyncMock(return_value={})

        mock_adapter = MagicMock()
        mock_adapter.connect = AsyncMock(side_effect=ConnectionError("refused"))
        mock_adapter.disconnect = AsyncMock()

        mods = {
            "app.connectors.mcp_client": _mock_module(
                MCPClientAdapter=MagicMock(return_value=mock_adapter),
            ),
            "app.services.connection_service": _mock_module(
                ConnectionService=MagicMock(return_value=mock_conn_svc),
            ),
        }

        with (
            patch.dict(sys.modules, mods),
            patch("app.models.base.async_session_factory", return_value=AsyncCtx(mock_session)),
        ):
            result = await pipeline.index("conn-1", ctx)

        assert result.success is False
        assert "refused" in result.error


class TestMCPPipelineSyncWithCode:
    @pytest.mark.asyncio
    async def test_sync_with_code_noop(self, pipeline, ctx):
        result = await pipeline.sync_with_code("conn-1", ctx)
        assert result.success is True
        assert "No code sync" in result.metadata.get("message", "")


class TestMCPPipelineGetStatus:
    @pytest.mark.asyncio
    async def test_get_status_with_docs(self, pipeline):
        conn = _make_conn()
        mock_session = AsyncMock()
        mock_conn_svc = MagicMock()
        mock_conn_svc.get = AsyncMock(return_value=conn)

        mock_collection = MagicMock()
        mock_collection.get = MagicMock(return_value={"ids": ["id1", "id2"]})
        mock_vs = MagicMock()
        mock_vs.get_or_create_collection = MagicMock(return_value=mock_collection)

        mods = {
            "app.services.connection_service": _mock_module(
                ConnectionService=MagicMock(return_value=mock_conn_svc),
            ),
            "app.knowledge.vector_store": _mock_module(
                VectorStore=MagicMock(return_value=mock_vs),
            ),
        }

        with (
            patch.dict(sys.modules, mods),
            patch("app.models.base.async_session_factory", return_value=AsyncCtx(mock_session)),
        ):
            status = await pipeline.get_status("conn-1")

        assert status.is_indexed is True
        assert status.items_count == 2

    @pytest.mark.asyncio
    async def test_get_status_no_docs(self, pipeline):
        conn = _make_conn()
        mock_session = AsyncMock()
        mock_conn_svc = MagicMock()
        mock_conn_svc.get = AsyncMock(return_value=conn)

        mock_collection = MagicMock()
        mock_collection.get = MagicMock(return_value={"ids": []})
        mock_vs = MagicMock()
        mock_vs.get_or_create_collection = MagicMock(return_value=mock_collection)

        mods = {
            "app.services.connection_service": _mock_module(
                ConnectionService=MagicMock(return_value=mock_conn_svc),
            ),
            "app.knowledge.vector_store": _mock_module(
                VectorStore=MagicMock(return_value=mock_vs),
            ),
        }

        with (
            patch.dict(sys.modules, mods),
            patch("app.models.base.async_session_factory", return_value=AsyncCtx(mock_session)),
        ):
            status = await pipeline.get_status("conn-1")

        assert status.is_indexed is False
        assert status.items_count == 0


class TestMCPPipelineProperties:
    def test_source_type_property(self, pipeline):
        assert pipeline.source_type == "mcp"

    def test_constructor_stores_config(self):
        p = MCPPipeline()
        assert isinstance(p, MCPPipeline)
        assert p.source_type == "mcp"
