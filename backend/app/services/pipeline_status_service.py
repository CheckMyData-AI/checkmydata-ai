"""Unified project-scoped pipeline status for repo index, DB index, and code-DB sync."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.git_tracker import GitTracker
from app.models.indexing_run import IndexingRun
from app.services.code_db_sync_service import CodeDbSyncService
from app.services.connection_service import ConnectionService
from app.services.db_index_service import DbIndexService
from app.services.project_service import ProjectService

logger = logging.getLogger(__name__)

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

        # Active IndexingRun rows are the source of truth for "is running" + progress.
        active = await self._active_runs(session, project_id)
        by_key: dict[tuple[str, str | None], IndexingRun] = {
            (r.kind, r.connection_id or None): r for r in active
        }

        project = await _project_svc.get(session, project_id)
        record = None
        if project and project.repo_url:
            record = await _git_tracker.get_last_indexed_record(
                session,
                project_id,
                branch=project.repo_branch,
            )

        repo_run = by_key.get(("index_repo", None))
        repo_is_indexing = repo_run is not None or in_memory_repo_indexing
        repo: dict[str, Any] = {
            "is_indexing": repo_is_indexing,
            "last_indexed_at": (
                record.created_at.isoformat() if record and record.created_at else None
            ),
            "last_indexed_commit": record.commit_sha if record else None,
            **self._run_fields(repo_run),
        }

        connections_out: list[dict[str, Any]] = []
        any_running = repo_is_indexing
        seen_conn_ids: set[str] = set()

        connections = await _conn_svc.list_by_project(session, project_id)
        for conn in connections:
            seen_conn_ids.add(conn.id)
            db_status = await _db_index_svc.get_status(session, conn.id)
            sync_status = await _sync_svc.get_status(session, conn.id)

            db_run = by_key.get(("db_index", conn.id))
            sync_run = by_key.get(("code_db_sync", conn.id))
            db_is_indexing = db_run is not None or in_memory_db_index.get(conn.id, False)
            sync_is_syncing = sync_run is not None or in_memory_sync.get(conn.id, False)

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
                        **self._run_fields(db_run),
                    },
                    "code_db_sync": {
                        "is_syncing": sync_is_syncing,
                        "sync_status": sync_status.get("sync_status", "idle"),
                        "synced_at": sync_status.get("synced_at"),
                        "total_tables": sync_status.get("total_tables", 0) or 0,
                        "synced_tables": sync_status.get("synced_tables", 0) or 0,
                        **self._run_fields(sync_run),
                    },
                }
            )

        # Surface active runs whose connection row is missing/not listed so a
        # running pipeline is never invisible.
        for run in active:
            if run.kind not in ("db_index", "code_db_sync"):
                continue
            if run.connection_id in seen_conn_ids:
                continue
            seen_conn_ids.add(run.connection_id or "")
            any_running = True
            db_run = run if run.kind == "db_index" else None
            sync_run = run if run.kind == "code_db_sync" else None
            connections_out.append(
                {
                    "connection_id": run.connection_id,
                    "connection_name": run.connection_id,
                    "db_index": {"is_indexing": db_run is not None, **self._run_fields(db_run)},
                    "code_db_sync": {
                        "is_syncing": sync_run is not None,
                        **self._run_fields(sync_run),
                    },
                }
            )

        return {
            "project_id": project_id,
            "repo": repo,
            "connections": connections_out,
            "any_running": any_running,
        }

    async def _active_runs(self, session: AsyncSession, project_id: str) -> list[IndexingRun]:
        stmt = select(IndexingRun).where(
            IndexingRun.project_id == project_id,
            IndexingRun.status.in_(("queued", "running", "cancelling")),
        )
        return list((await session.execute(stmt)).scalars().all())

    @staticmethod
    def _run_fields(run: IndexingRun | None) -> dict[str, Any]:
        if run is None:
            return {
                "run_id": None,
                "workflow_id": None,
                "progress_pct": 0,
                "current_step": None,
                "step_index": 0,
                "total_steps": 0,
                "failure_kind": None,
            }
        return {
            "run_id": run.id,
            "workflow_id": run.workflow_id,
            "progress_pct": run.progress_pct,
            "current_step": run.current_step,
            "step_index": run.step_index,
            "total_steps": run.total_steps,
            "failure_kind": run.failure_kind,
        }

    async def list_synthetic_active_tasks(
        self,
        session: AsyncSession,
        *,
        accessible_project_ids: set[str] | frozenset[str],
    ) -> list[dict[str, Any]]:
        """Return active background runs as task entries (DB-backed, both modes).

        Sourced from ``indexing_runs`` so there are no synthetic ids and the same
        list is authoritative whether the work runs in-process or in an ARQ worker.
        """
        if not accessible_project_ids:
            return []

        stmt = select(IndexingRun).where(
            IndexingRun.project_id.in_(list(accessible_project_ids)),
            IndexingRun.status.in_(("queued", "running", "cancelling")),
        )
        rows = (await session.execute(stmt)).scalars().all()
        return [
            {
                "workflow_id": r.workflow_id,
                "run_id": r.id,
                "pipeline": r.kind,
                "kind": r.kind,
                "started_at": r.started_at.timestamp() if r.started_at else 0.0,
                "progress_pct": r.progress_pct,
                "extra": {"project_id": r.project_id, "connection_id": r.connection_id},
            }
            for r in rows
        ]
