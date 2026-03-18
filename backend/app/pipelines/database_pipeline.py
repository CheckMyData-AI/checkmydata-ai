"""Database pipeline — wraps existing DbIndex and CodeDbSync logic.

This is the first (and currently only) pipeline plugin.  It adapts the
existing indexing infrastructure into the new pipeline abstraction.
"""

from __future__ import annotations

import logging

from app.agents.tools.sql_tools import get_sql_agent_tools
from app.llm.base import Tool
from app.pipelines.base import (
    DataSourcePipeline,
    PipelineContext,
    PipelineResult,
    PipelineStatus,
)

logger = logging.getLogger(__name__)


class DatabasePipeline(DataSourcePipeline):
    """Pipeline plugin for SQL / NoSQL databases."""

    @property
    def source_type(self) -> str:
        return "database"

    async def index(
        self,
        source_id: str,
        context: PipelineContext,
    ) -> PipelineResult:
        """Run the DB index pipeline for a given connection."""
        from app.knowledge.db_index_pipeline import DbIndexPipeline
        from app.models.base import async_session_factory

        try:
            pipeline = DbIndexPipeline()
            async with async_session_factory() as session:
                await pipeline.run(
                    session=session,
                    connection_id=source_id,
                    project_id=context.project_id,
                    workflow_id=context.workflow_id,
                    force_full=context.force_full,
                )
            return PipelineResult(success=True)
        except Exception as exc:
            logger.exception("Database index pipeline failed for %s", source_id)
            return PipelineResult(success=False, error=str(exc))

    async def sync_with_code(
        self,
        source_id: str,
        context: PipelineContext,
    ) -> PipelineResult:
        """Run code-DB sync for a given connection."""
        from app.knowledge.code_db_sync_pipeline import CodeDbSyncPipeline
        from app.models.base import async_session_factory

        try:
            pipeline = CodeDbSyncPipeline()
            async with async_session_factory() as session:
                await pipeline.run(
                    session=session,
                    connection_id=source_id,
                    project_id=context.project_id,
                    workflow_id=context.workflow_id,
                )
            return PipelineResult(success=True)
        except Exception as exc:
            logger.exception("Code-DB sync pipeline failed for %s", source_id)
            return PipelineResult(success=False, error=str(exc))

    async def get_status(self, source_id: str) -> PipelineStatus:
        from app.models.base import async_session_factory
        from app.services.code_db_sync_service import CodeDbSyncService
        from app.services.db_index_service import DbIndexService

        db_svc = DbIndexService()
        sync_svc = CodeDbSyncService()

        try:
            async with async_session_factory() as session:
                is_indexed = await db_svc.is_indexed(session, source_id)
                is_synced = await sync_svc.is_synced(session, source_id) if is_indexed else False
                is_stale = False
                items = 0
                if is_indexed:
                    from app.config import settings as app_settings

                    is_stale = await db_svc.is_stale(
                        session,
                        source_id,
                        ttl_hours=app_settings.db_index_ttl_hours,
                    )
                    entries = await db_svc.get_index(session, source_id)
                    items = len(entries)

                return PipelineStatus(
                    is_indexed=is_indexed,
                    is_synced=is_synced,
                    is_stale=is_stale,
                    items_count=items,
                )
        except Exception:
            return PipelineStatus()

    def get_agent_tools(self) -> list[Tool]:
        return get_sql_agent_tools(has_db_index=True, has_code_db_sync=True, has_learnings=True)
