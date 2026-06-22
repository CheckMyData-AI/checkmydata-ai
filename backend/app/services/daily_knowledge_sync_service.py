"""Daily scheduled knowledge sync: repo index → DB index → code↔DB sync."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.base import async_session_factory
from app.models.connection import Connection
from app.models.indexing_run import IndexingRun
from app.models.project import Project
from app.services.checkpoint_service import CheckpointService
from app.services.connection_service import ConnectionService
from app.services.project_service import ProjectService
from app.services.run_coordinator import RunCoordinator

logger = logging.getLogger(__name__)

_STEP_COMPLETED = "completed"
_STEP_FAILED = "failed"
_STEP_SKIPPED = "skipped"

_STATUS_SUCCESS = "success"
_STATUS_PARTIAL = "partial"
_STATUS_FAILED = "failed"
_STATUS_SKIPPED = "skipped"


@dataclass
class KnowledgeSyncRunResult:
    project_id: str
    trigger: str = "scheduled"
    status: str = _STATUS_SKIPPED
    duration_seconds: float = 0.0
    steps_json: dict = field(default_factory=dict)
    error_message: str | None = None


def _daily_wf_status(status: str) -> str:
    """Map a run status to its terminal workflow-tracker status.

    Only a hard failure surfaces as ``failed``; success/partial/skipped all
    represent a completed daily-sync workflow.
    """
    completed = (_STATUS_SUCCESS, _STATUS_PARTIAL, _STATUS_SKIPPED)
    return "completed" if status in completed else "failed"


def compute_next_scheduled_run(
    now: datetime,
    *,
    hour: int,
    timezone_name: str,
) -> datetime:
    """Return the next scheduled run instant in *timezone_name*."""
    tz = ZoneInfo(timezone_name)
    if now.tzinfo is None:
        local_now = now.replace(tzinfo=tz)
    else:
        local_now = now.astimezone(tz)
    next_run = local_now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if next_run <= local_now:
        next_run += timedelta(days=1)
    return next_run


class DailyKnowledgeSyncService:
    def __init__(self) -> None:
        self._project_svc = ProjectService()
        self._conn_svc = ConnectionService()
        self._checkpoint_svc = CheckpointService()

    async def list_eligible_projects(self, session: AsyncSession) -> list[Project]:
        from app.services.sync_schedule_service import SyncScheduleService

        sched = SyncScheduleService()
        projects = await self._project_svc.list_all(session)
        eligible: list[Project] = []
        for project in projects:
            if not project.repo_url:
                continue
            eff = await sched.effective(session, project.id)
            if not eff["enabled"]:
                continue
            connections = await self._active_connections(session, project.id)
            if connections:
                eligible.append(project)
        return eligible

    async def run_for_project(
        self, project_id: str, *, trigger: str = "schedule"
    ) -> KnowledgeSyncRunResult:
        """Run the daily sync under a first-class ``daily_sync`` IndexingRun.

        Adopts an already-active run for the project (e.g. a manual ``sync-now``
        that minted the run before enqueueing) instead of creating a duplicate.
        The orchestration body is unchanged; per-operation progress comes from the
        child runs created by the repo/db/sync sub-steps.
        """
        coord = RunCoordinator()
        async with async_session_factory() as db:
            existing = await coord._find_active(db, project_id, "daily_sync", None)
            run_id = (
                existing.id
                if existing
                else (
                    await coord.start(
                        db,
                        kind="daily_sync",
                        project_id=project_id,
                        connection_id=None,
                        trigger=trigger,
                    )
                ).id
            )

        result = await self._orchestrate(project_id)

        terminal = "failed" if result.status == _STATUS_FAILED else "completed"
        failure_kind = "fatal" if terminal == "failed" else None
        async with async_session_factory() as db:
            run = await db.get(IndexingRun, run_id)
            if run is not None and run.status not in ("completed", "failed", "cancelled"):
                run.meta_json = json.dumps(
                    {"status": result.status, "steps": result.steps_json}, default=str
                )
                await db.commit()
                await coord.finish(
                    db, run, terminal, error=result.error_message, failure_kind=failure_kind
                )
        return result

    async def _orchestrate(self, project_id: str) -> KnowledgeSyncRunResult:
        started = time.monotonic()
        result = KnowledgeSyncRunResult(project_id=project_id)

        async with async_session_factory() as session:
            project = await self._project_svc.get(session, project_id)
            if not project:
                result.status = _STATUS_SKIPPED
                result.steps_json = {"reason": "project_not_found"}
                result.error_message = "project not found"
                result.duration_seconds = time.monotonic() - started
                return result

            if not project.repo_url:
                result.status = _STATUS_SKIPPED
                result.steps_json = {"reason": "no_repo"}
                result.error_message = "project has no repository"
                result.duration_seconds = time.monotonic() - started
                return result

            active_connections = await self._active_connections(session, project.id)
            if not active_connections:
                result.status = _STATUS_SKIPPED
                result.steps_json = {"reason": "no_active_connections"}
                result.error_message = "project has no active connections"
                result.duration_seconds = time.monotonic() - started
                return result

        logger.info(
            "Cron: daily knowledge sync started project=%s connections=%d",
            project_id[:8],
            len(active_connections),
        )

        steps: dict = {
            "repo_index": {"status": _STEP_SKIPPED, "error": None},
            "connections": [],
        }

        repo_status, repo_error = await self._run_repo_index(project_id)
        steps["repo_index"] = {"status": repo_status, "error": repo_error}

        if repo_status != _STEP_COMPLETED:
            result.status = _STATUS_FAILED if repo_status == _STEP_FAILED else _STATUS_PARTIAL
            result.steps_json = steps
            result.error_message = repo_error
            result.duration_seconds = time.monotonic() - started
            logger.error(
                "Cron: daily knowledge sync failed project=%s step=repo_index error=%s",
                project_id[:8],
                repo_error or repo_status,
            )
            return result

        any_failure = False
        any_skip = False
        for conn in active_connections:
            conn_steps: dict = {
                "connection_id": conn.id,
                "db_index": {"status": _STEP_SKIPPED, "error": None},
                "code_db_sync": {"status": _STEP_SKIPPED, "error": None},
            }

            db_status, db_error = await self._run_db_index(conn.id, project_id)
            conn_steps["db_index"] = {"status": db_status, "error": db_error}
            if db_status == _STEP_FAILED:
                any_failure = True
                conn_steps["code_db_sync"] = {
                    "status": _STEP_SKIPPED,
                    "error": "db index failed",
                }
                steps["connections"].append(conn_steps)
                logger.error(
                    "Cron: daily knowledge sync failed project=%s step=db_index "
                    "connection=%s error=%s",
                    project_id[:8],
                    conn.id[:8],
                    db_error,
                )
                continue
            if db_status == _STEP_SKIPPED:
                any_skip = True
                conn_steps["code_db_sync"] = {
                    "status": _STEP_SKIPPED,
                    "error": "db index skipped",
                }
                steps["connections"].append(conn_steps)
                continue

            sync_status, sync_error = await self._run_code_db_sync(conn.id, project_id)
            conn_steps["code_db_sync"] = {"status": sync_status, "error": sync_error}
            if sync_status == _STEP_FAILED:
                any_failure = True
                logger.error(
                    "Cron: daily knowledge sync failed project=%s step=code_db_sync "
                    "connection=%s error=%s",
                    project_id[:8],
                    conn.id[:8],
                    sync_error,
                )
            elif sync_status == _STEP_SKIPPED:
                any_skip = True
            steps["connections"].append(conn_steps)

        if any_failure or any_skip:
            result.status = _STATUS_PARTIAL
        else:
            result.status = _STATUS_SUCCESS

        result.steps_json = steps
        result.duration_seconds = time.monotonic() - started
        logger.info(
            "Cron: daily knowledge sync completed project=%s status=%s duration=%.0fs",
            project_id[:8],
            result.status,
            result.duration_seconds,
        )
        return result

    async def _active_connections(
        self,
        session: AsyncSession,
        project_id: str,
    ) -> list[Connection]:
        connections = await self._conn_svc.list_by_project(session, project_id)
        active = [c for c in connections if getattr(c, "is_active", True)]
        active.sort(key=lambda c: c.created_at)
        return active

    async def _run_repo_index(self, project_id: str) -> tuple[str, str | None]:
        from app.api.routes.repos import run_repo_index_task

        async with async_session_factory() as session:
            cp = await self._checkpoint_svc.get_active(session, project_id)
            if cp and cp.status == "running":
                return _STEP_SKIPPED, "repo index already running"

        child_wf = await self._start_child_wf("index_repo", None, project_id)
        try:
            await run_repo_index_task(
                project_id, force_full=False, chain_sync=False, wf_id=child_wf
            )
        except Exception as exc:
            logger.exception(
                "Cron: daily knowledge sync repo index raised project=%s",
                project_id[:8],
            )
            return _STEP_FAILED, str(exc)

        return await self._repo_index_outcome(project_id)

    async def _repo_index_outcome(self, project_id: str) -> tuple[str, str | None]:
        async with async_session_factory() as session:
            cp = await self._checkpoint_svc.get_active(session, project_id)
        if cp is None:
            return _STEP_COMPLETED, None
        if cp.status == "failed":
            return _STEP_FAILED, cp.error_detail
        return _STEP_FAILED, f"checkpoint status={cp.status}"

    async def _start_child_wf(
        self, kind: str, connection_id: str | None, project_id: str
    ) -> str | None:
        """Create a child IndexingRun for a daily-sync sub-operation and return its
        workflow id. The pipeline's emitted events are mapped onto the run (and
        finalised) by the RunCoordinator persistence hook. Returns ``None`` when a
        run is already active (the pipeline then begins its own untracked workflow).
        """
        from app.services.run_coordinator import RunAlreadyActiveError, RunCoordinator

        try:
            async with async_session_factory() as rdb:
                run = await RunCoordinator().start(
                    rdb,
                    kind=kind,
                    project_id=project_id,
                    connection_id=connection_id,
                    trigger="schedule",
                )
                return run.workflow_id
        except RunAlreadyActiveError:
            return None

    async def _run_db_index(
        self,
        connection_id: str,
        project_id: str,
    ) -> tuple[str, str | None]:
        from app.services.db_index_service import DbIndexService

        idx_svc = DbIndexService()

        async with async_session_factory() as session:
            if await idx_svc.get_indexing_status(session, connection_id) == "running":
                return _STEP_SKIPPED, "db index already running"
            conn = await self._conn_svc.get(session, connection_id)
            if not conn:
                return _STEP_FAILED, "connection not found"
            config = await self._conn_svc.to_config(session, conn)

        child_wf = await self._start_child_wf("db_index", connection_id, project_id)
        final_status = _STEP_FAILED
        error: str | None = None
        pipeline_result: dict | str | None = None
        try:
            async with async_session_factory() as session:
                await idx_svc.set_indexing_status(session, connection_id, "running")
                await session.commit()

            from app.knowledge.db_index_pipeline import DbIndexPipeline

            pipeline = DbIndexPipeline(
                db_index_batch_size=settings.db_index_batch_size,
            )
            pipeline_result = await pipeline.run(
                connection_id=connection_id,
                connection_config=config,
                project_id=project_id,
                wf_id=child_wf,
            )
            if isinstance(pipeline_result, dict) and pipeline_result.get("status") == "failed":
                error = pipeline_result.get("error", "unknown")
            else:
                final_status = _STEP_COMPLETED
                try:
                    from app.api.routes.connections import (
                        _regenerate_overview,
                        _run_data_probes,
                    )

                    await _regenerate_overview(project_id, connection_id)
                    await _run_data_probes(connection_id, config, project_id)
                except Exception:
                    logger.debug(
                        "Daily sync db index post-steps failed connection=%s",
                        connection_id[:8],
                        exc_info=True,
                    )
        except Exception as exc:
            logger.exception(
                "Cron: daily knowledge sync db index failed connection=%s",
                connection_id[:8],
            )
            error = str(exc)
        finally:
            db_status = "completed" if final_status == _STEP_COMPLETED else "failed"
            if (
                final_status == _STEP_COMPLETED
                and isinstance(pipeline_result, dict)
                and pipeline_result.get("partial")
            ):
                db_status = "completed_partial"
            try:
                async with async_session_factory() as session:
                    await idx_svc.set_indexing_status(session, connection_id, db_status)
                    await session.commit()
            except Exception:
                logger.debug("Failed to update indexing_status", exc_info=True)

        if final_status == _STEP_COMPLETED:
            return _STEP_COMPLETED, None
        return _STEP_FAILED, error

    async def _run_code_db_sync(
        self,
        connection_id: str,
        project_id: str,
    ) -> tuple[str, str | None]:
        from app.services.code_db_sync_service import CodeDbSyncService
        from app.services.db_index_service import DbIndexService

        sync_svc = CodeDbSyncService()
        idx_svc = DbIndexService()

        async with async_session_factory() as session:
            if await sync_svc.get_sync_status(session, connection_id) == "running":
                return _STEP_SKIPPED, "sync already running"
            if not await idx_svc.is_indexed(session, connection_id):
                return _STEP_SKIPPED, "connection not DB-indexed"

        child_wf = await self._start_child_wf("code_db_sync", connection_id, project_id)
        final_status = _STEP_FAILED
        error: str | None = None
        try:
            async with async_session_factory() as session:
                await sync_svc.set_sync_status(session, connection_id, "running")
                await session.commit()

            from app.knowledge.code_db_sync_pipeline import CodeDbSyncPipeline

            pipeline = CodeDbSyncPipeline()
            pipeline_result = await pipeline.run(
                connection_id=connection_id,
                project_id=project_id,
                wf_id=child_wf,
            )
            if isinstance(pipeline_result, dict) and pipeline_result.get("status") == "failed":
                error = pipeline_result.get("error", "unknown")
            else:
                final_status = _STEP_COMPLETED
        except Exception as exc:
            logger.exception(
                "Cron: daily knowledge sync code-db sync failed connection=%s",
                connection_id[:8],
            )
            error = str(exc)
        finally:
            sync_status = "completed" if final_status == _STEP_COMPLETED else "failed"
            try:
                async with async_session_factory() as session:
                    await sync_svc.set_sync_status(session, connection_id, sync_status)
                    await session.commit()
            except Exception:
                logger.debug("Failed to update sync_status", exc_info=True)

        if final_status == _STEP_COMPLETED:
            return _STEP_COMPLETED, None
        return _STEP_FAILED, error
