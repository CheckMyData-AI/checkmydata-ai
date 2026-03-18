"""MCP pipeline — indexes MCP tool schemas and metadata.

When a user adds an MCP source connection, this pipeline connects to the
MCP server, discovers its tools, and stores the tool schemas in the
knowledge base so that agents know what capabilities are available.
"""

from __future__ import annotations

import json
import logging

from app.core.retry import retry
from app.llm.base import Tool
from app.pipelines.base import (
    DataSourcePipeline,
    PipelineContext,
    PipelineResult,
    PipelineStatus,
)

logger = logging.getLogger(__name__)


class MCPPipeline(DataSourcePipeline):
    """Pipeline plugin for MCP data sources."""

    @property
    def source_type(self) -> str:
        return "mcp"

    async def index(
        self,
        source_id: str,
        context: PipelineContext,
    ) -> PipelineResult:
        """Connect to the MCP server and index its tool schemas.

        Stores the tool names, descriptions, and input schemas in the
        project's vector store for agent reference.
        """
        from app.connectors.mcp_client import MCPClientAdapter
        from app.models.base import async_session_factory
        from app.services.connection_service import ConnectionService

        conn_svc = ConnectionService()

        try:
            async with async_session_factory() as session:
                conn = await conn_svc.get(session, source_id)
                if not conn:
                    return PipelineResult(success=False, error="Connection not found")
                if conn.source_type != "mcp":
                    return PipelineResult(
                        success=False, error=f"Connection is not MCP type: {conn.source_type}"
                    )
                config = await conn_svc.to_config(session, conn)

            adapter = MCPClientAdapter()

            @retry(
                max_attempts=3,
                backoff_seconds=1.0,
                retryable_exceptions=(TimeoutError, ConnectionError, OSError),
            )
            async def _connect_with_retry():
                await adapter.connect(config)

            await _connect_with_retry()
            try:
                schemas = adapter.get_tool_schemas()
            finally:
                await adapter.disconnect()

            if not schemas:
                return PipelineResult(
                    success=True,
                    items_processed=0,
                    metadata={"message": "MCP server has no tools"},
                )

            tool_docs: list[str] = []
            for schema in schemas:
                doc = (
                    f"MCP Tool: {schema['name']}\n"
                    f"Description: {schema.get('description', 'N/A')}\n"
                    f"Input Schema: {json.dumps(schema.get('input_schema', {}), indent=2)}"
                )
                tool_docs.append(doc)

            try:
                from app.knowledge.vector_store import VectorStore

                vs = VectorStore()
                collection = vs.get_or_create_collection(context.project_id)
                ids = [f"mcp-tool-{source_id}-{s['name']}" for s in schemas]
                metadatas = [
                    {
                        "source": f"mcp:{conn.name}",
                        "type": "mcp_tool_schema",
                        "tool_name": s["name"],
                        "connection_id": source_id,
                    }
                    for s in schemas
                ]
                collection.upsert(documents=tool_docs, ids=ids, metadatas=metadatas)
            except Exception:
                logger.warning("Failed to store MCP tool schemas in vector store", exc_info=True)

            return PipelineResult(
                success=True,
                items_processed=len(schemas),
                metadata={
                    "tools": [s["name"] for s in schemas],
                    "connection_name": conn.name,
                },
            )

        except Exception as exc:
            logger.exception("MCP index pipeline failed for %s", source_id)
            return PipelineResult(success=False, error=str(exc))

    async def sync_with_code(
        self,
        source_id: str,
        context: PipelineContext,
    ) -> PipelineResult:
        """MCP sources don't have a code-sync step, so this is a no-op."""
        return PipelineResult(success=True, metadata={"message": "No code sync for MCP sources"})

    async def get_status(self, source_id: str) -> PipelineStatus:
        """Check if MCP tool schemas have been indexed."""
        try:
            from app.knowledge.vector_store import VectorStore
            from app.models.base import async_session_factory
            from app.services.connection_service import ConnectionService

            conn_svc = ConnectionService()
            async with async_session_factory() as session:
                conn = await conn_svc.get(session, source_id)
                if not conn or conn.source_type != "mcp":
                    return PipelineStatus()

            vs = VectorStore()
            collection = vs.get_or_create_collection(conn.project_id)

            results = collection.get(
                where={"connection_id": source_id, "type": "mcp_tool_schema"},
            )
            count = len(results.get("ids", [])) if results else 0

            return PipelineStatus(
                is_indexed=count > 0,
                is_synced=True,
                items_count=count,
            )
        except Exception:
            logger.debug("Failed to get MCP pipeline status", exc_info=True)
            return PipelineStatus()

    def get_agent_tools(self) -> list[Tool]:
        """MCP pipeline doesn't add extra tools directly; the MCPSourceAgent handles tool calls."""
        return []
