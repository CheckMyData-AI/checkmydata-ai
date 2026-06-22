"""Single seam owning the lifecycle of every background run.

Writes the :class:`IndexingRun` projection AND the :class:`IndexingRunEvent`
journal, emits WorkflowEvents with first-class progress, enforces single-active,
and supports cooperative cancel + retry. Used by every trigger and by both the
in-process and ARQ execution paths.

Sessions are threaded explicitly (``db``) rather than discovered from the ORM
instance: under SQLAlchemy async, ``inspect(obj).session`` returns the *sync*
session, whose ``commit`` is not awaitable.
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.workflow_tracker import tracker
from app.knowledge.run_manifests import (
    Step,
    progress_for,
    resolve_manifest,
    step_position,
    total_steps,
)
from app.models.indexing_run import IndexingRun, IndexingRunEvent

logger = logging.getLogger(__name__)

_ACTIVE_STATUSES = ("queued", "running", "cancelling")
_TERMINAL_STATUSES = ("completed", "failed", "cancelled")


class RunAlreadyActiveError(Exception):
    """Raised when a run already exists for (project, kind, connection)."""

    def __init__(self, run_id: str) -> None:
        super().__init__(f"run already active: {run_id}")
        self.run_id = run_id


class RunCancelledError(Exception):
    """Raised inside a step when cancellation was requested."""


def _now() -> datetime:
    return datetime.now(UTC)


def _manifest_flags() -> dict[str, bool]:
    return {
        "code_graph_enabled": settings.code_graph_enabled,
        "hybrid_retrieval_enabled": settings.hybrid_retrieval_enabled,
        "schema_retrieval_enabled": settings.schema_retrieval_enabled,
        "lineage_enabled": settings.lineage_enabled,
        "clustering_enabled": settings.clustering_enabled,
    }


class RunCoordinator:
    def __init__(self) -> None:
        self._manifests: dict[str, list[Step]] = {}

    async def _find_active(
        self, db: AsyncSession, project_id: str, kind: str, connection_id: str | None
    ) -> IndexingRun | None:
        stmt = select(IndexingRun).where(
            IndexingRun.project_id == project_id,
            IndexingRun.kind == kind,
            IndexingRun.status.in_(_ACTIVE_STATUSES),
        )
        for row in (await db.execute(stmt)).scalars().all():
            if (row.connection_id or None) == (connection_id or None):
                return row
        return None

    def _manifest_for(self, run: IndexingRun) -> list[Step]:
        cached = self._manifests.get(run.id)
        if cached is not None:
            return cached
        manifest = resolve_manifest(run.kind, flags=_manifest_flags())
        self._manifests[run.id] = manifest
        return manifest

    async def start(
        self,
        db: AsyncSession,
        *,
        kind: str,
        project_id: str,
        connection_id: str | None = None,
        trigger: str = "manual",
        force_full: bool = False,
    ) -> IndexingRun:
        existing = await self._find_active(db, project_id, kind, connection_id)
        if existing is not None:
            raise RunAlreadyActiveError(existing.id)

        manifest = resolve_manifest(kind, flags=_manifest_flags())
        wf_id = await tracker.begin(
            kind,
            {"project_id": project_id, "connection_id": connection_id or "", "trigger": trigger},
        )
        run = IndexingRun(
            workflow_id=wf_id,
            project_id=project_id,
            connection_id=connection_id,
            kind=kind,
            trigger=trigger,
            status="running",
            step_index=0,
            total_steps=total_steps(manifest),
            progress_pct=0,
            started_at=_now(),
            heartbeat_at=_now(),
            meta_json=json.dumps({"force_full": force_full}),
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)
        self._manifests[run.id] = manifest
        await self._record(db, run, "pipeline_start", "started", f"Starting {kind}")
        return run

    async def _record(
        self,
        db: AsyncSession,
        run: IndexingRun,
        step: str,
        status: str,
        detail: str = "",
        *,
        elapsed_ms: float | None = None,
        level: str = "info",
    ) -> None:
        db.add(
            IndexingRunEvent(
                run_id=run.id,
                step=step,
                status=status,
                detail=detail,
                elapsed_ms=elapsed_ms,
                progress_pct=run.progress_pct,
                level=level,
            )
        )
        await db.commit()
        await tracker.emit(
            run.workflow_id,
            step,
            status,
            detail,
            run_id=run.id,
            kind=run.kind,
            step_index=run.step_index,
            total_steps=run.total_steps,
            progress_pct=run.progress_pct,
        )

    @asynccontextmanager
    async def step(self, db: AsyncSession, run: IndexingRun, step_key: str):
        await db.refresh(run)
        if run.cancel_requested:
            run.status = "cancelling"
            await db.commit()
            raise RunCancelledError(run.id)

        manifest = self._manifest_for(run)
        position = step_position(manifest, step_key)
        run.current_step = step_key
        run.step_index = position
        run.heartbeat_at = _now()
        await db.commit()
        await self._record(db, run, step_key, "started")

        t0 = _now()
        try:
            yield
        except Exception as exc:
            elapsed = (_now() - t0).total_seconds() * 1000
            await self._record(
                db, run, step_key, "failed", str(exc), elapsed_ms=elapsed, level="error"
            )
            raise
        else:
            elapsed = (_now() - t0).total_seconds() * 1000
            run.progress_pct = progress_for(manifest, position)
            run.version += 1
            run.heartbeat_at = _now()
            await db.commit()
            await self._record(db, run, step_key, "completed", elapsed_ms=elapsed)
