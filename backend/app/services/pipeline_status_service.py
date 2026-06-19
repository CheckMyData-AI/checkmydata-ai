"""Unified project-scoped pipeline status for repo index, DB index, and code-DB sync."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import task_queue
from app.knowledge.git_tracker import GitTracker
from app.services.checkpoint_service import CheckpointService
from app.services.code_db_sync_service import CodeDbSyncService
from app.services.connection_service import ConnectionService
from app.services.db_index_service import DbIndexService
from app.services.project_service import ProjectService

logger = logging.getLogger(__name__)

_checkpoint_svc = CheckpointService()
_conn_svc = ConnectionService()
_db_index_svc = DbIndexService()
_sync_svc = CodeDbSyncService()
_git_tracker = GitTracker()
_project_svc = ProjectService()


class PipelineStatusService:
    async def get_status(
        self,
        session: AsyncSession,
        project_id: str,
        *,
        in_memory_repo_indexing: bool = False,
        in_memory_db_index: dict[str, bool] | None = None,
        in_memory_sync: dict[str, bool] | None = None,
    ) -> dict[str, Any]:
        """Return aggregated pipeline status for a project.

        Optional in-memory flags mirror route-module task dicts so in-process
        asyncio jobs are visible even before DB status flips to ``running``.
        """
        in_memory_db_index = in_memory_db_index or {}
        in_memory_sync = in_memory_sync or {}

        project = await _project_svc.get(session, project_id)
        checkpoint = await _checkpoint_svc.get_active(session, project_id)
        checkpoint_running = checkpoint is not None and checkpoint.status == "running"
        repo_is_indexing = in_memory_repo_indexing or checkpoint_running

        record = None
        if project and project.repo_url:
            record = await _git_tracker.get_last_indexed_record(
                session,
                project_id,
                branch=project.repo_branch,
            )

        repo: dict[str, Any] = {
            "is_indexing": repo_is_indexing,
            "checkpoint_status": checkpoint.status if checkpoint else None,
            "workflow_id": checkpoint.workflow_id if checkpoint else None,
            "last_indexed_at": (
                record.created_at.isoformat() if record and record.created_at else None
            ),
            "last_indexed_commit": record.commit_sha if record else None,
        }

        connections_out: list[dict[str, Any]] = []
        any_running = repo_is_indexing

        connections = await _conn_svc.list_by_project(session, project_id)
        for conn in connections:
            db_status = await _db_index_svc.get_status(session, conn.id)
            sync_status = await _sync_svc.get_status(session, conn.id)

            db_running = db_status.get("indexing_status") == "running"
            sync_running = sync_status.get("sync_status") == "running"
            db_is_indexing = in_memory_db_index.get(conn.id, False) or db_running
            sync_is_syncing = in_memory_sync.get(conn.id, False) or sync_running

            if db_is_indexing or sync_is_syncing:
                any_running = True

            connections_out.append(
                {
                    "connection_id": conn.id,
                    "connection_name": conn.name,
                    "db_index": {
                        "is_indexing": db_is_indexing,
                        "indexing_status": db_status.get("indexing_status", "idle"),
                        "indexed_at": db_status.get("indexed_at"),
                        "table_count": db_status.get("total_tables", 0) or 0,
                    },
                    "code_db_sync": {
                        "is_syncing": sync_is_syncing,
                        "sync_status": sync_status.get("sync_status", "idle"),
                        "synced_at": sync_status.get("synced_at"),
                        "total_tables": sync_status.get("total_tables", 0) or 0,
                        "synced_tables": sync_status.get("synced_tables", 0) or 0,
                    },
                }
            )

        if any_running:
            logger.debug(
                "pipeline-status any_running=true project=%s repo=%s connections=%d",
                project_id[:8],
                "running" if repo_is_indexing else "idle",
                len(connections_out),
            )

        return {
            "project_id": project_id,
            "repo": repo,
            "connections": connections_out,
            "any_running": any_running,
        }

    async def list_synthetic_active_tasks(
        self,
        session: AsyncSession,
        *,
        accessible_project_ids: set[str] | frozenset[str],
    ) -> list[dict[str, Any]]:
        """Build running-task entries from DB when ARQ worker holds the jobs."""
        if not task_queue.is_arq_active():
            return []

        import time

        out: list[dict[str, Any]] = []
        now = time.time()

        for project_id in accessible_project_ids:
            checkpoint = await _checkpoint_svc.get_active(session, project_id)
            if checkpoint and checkpoint.status == "running" and checkpoint.workflow_id:
                out.append(
                    {
                        "workflow_id": checkpoint.workflow_id,
                        "pipeline": "index_repo",
                        "started_at": now,
                        "extra": {"project_id": project_id},
                    }
                )

            connections = await _conn_svc.list_by_project(session, project_id)
            for conn in connections:
                db_status = await _db_index_svc.get_status(session, conn.id)
                if db_status.get("indexing_status") == "running":
                    out.append(
                        {
                            "workflow_id": f"db:{conn.id}",
                            "pipeline": "db_index",
                            "started_at": now,
                            "extra": {
                                "project_id": project_id,
                                "connection_id": conn.id,
                            },
                        }
                    )

                sync_status = await _sync_svc.get_status(session, conn.id)
                if sync_status.get("sync_status") == "running":
                    out.append(
                        {
                            "workflow_id": f"sync:{conn.id}",
                            "pipeline": "code_db_sync",
                            "started_at": now,
                            "extra": {
                                "project_id": project_id,
                                "connection_id": conn.id,
                            },
                        }
                    )

        return out
