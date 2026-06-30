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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.workflow_tracker import WorkflowEvent, tracker
from app.knowledge.run_manifests import (
    Step,
    progress_for,
    resolve_manifest,
    step_position,
    total_steps,
)
from app.models.base import async_session_factory
from app.models.indexing_run import IndexingRun, IndexingRunEvent
from app.services.error_log_service import ErrorLogService

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


def _diagnostic_flags() -> dict[str, bool]:
    """Snapshot the ingestion-automation flags that drive background/sync runs.

    Persisted into ``IndexingRun.meta_json["flags"]`` at run creation so a failed
    background job is diagnosable after the fact ("which flag produced this run?").
    Captures the live ``settings`` value, not a constant (spec §3.5).
    """
    return {
        "git_webhook_enabled": settings.git_webhook_enabled,
        "git_poll_enabled": settings.git_poll_enabled,
        "auto_sync_after_index": settings.auto_sync_after_index,
        "freshness_reconciler_enabled": settings.freshness_reconciler_enabled,
        "schema_change_alerts_enabled": settings.schema_change_alerts_enabled,
        "db_index_incremental_enabled": settings.db_index_incremental_enabled,
    }


def _aware(dt: datetime) -> datetime:
    """Normalise to UTC-aware (SQLite reads timestamps back naive)."""
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _emit_terminal_metrics(run: IndexingRun) -> None:
    """SLI counters for a run reaching a terminal state (best-effort)."""
    try:
        from app.core.metrics import get_metrics_collector

        mc = get_metrics_collector()
        mc.inc("indexing_runs_total", kind=run.kind, status=run.status)
        if run.started_at and run.finished_at:
            mc.add(
                "indexing_run_duration_seconds",
                (_aware(run.finished_at) - _aware(run.started_at)).total_seconds(),
                kind=run.kind,
            )
    except Exception:  # noqa: BLE001 — metrics must never break a run
        logger.debug("run terminal metrics failed", exc_info=True)


def _emit_ttfp_metric(run: IndexingRun) -> None:
    """Time-to-first-progress SLI: first step start relative to run start."""
    try:
        from app.core.metrics import get_metrics_collector

        if run.started_at is not None:
            get_metrics_collector().add(
                "indexing_run_time_to_first_progress_seconds",
                (_now() - _aware(run.started_at)).total_seconds(),
                kind=run.kind,
            )
    except Exception:  # noqa: BLE001
        logger.debug("ttfp metric failed", exc_info=True)


class RunCoordinator:
    _error_log = ErrorLogService()
    _attached = False
    _wf_to_run: dict[str, str] = {}

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
            meta_json=json.dumps({"force_full": force_full, "flags": _diagnostic_flags()}),
        )
        db.add(run)
        try:
            await db.commit()
        except IntegrityError as exc:
            # TOCTOU race: another process committed a run between our _find_active
            # pre-check and this commit.  Roll back (required — the session is
            # poisoned after an IntegrityError and must not be used without it),
            # then re-query for the winner so we can surface its run_id.
            await db.rollback()
            existing = await self._find_active(db, project_id, kind, connection_id)
            raise RunAlreadyActiveError(existing.id if existing else "unknown") from exc
        await db.refresh(run)
        self._manifests[run.id] = manifest
        RunCoordinator._wf_to_run[run.workflow_id] = run.id
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
        if run.step_index == 0:
            _emit_ttfp_metric(run)
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

    async def finish(
        self,
        db: AsyncSession,
        run: IndexingRun,
        status: str,
        error: str | None = None,
        failure_kind: str | None = None,
    ) -> None:
        run.status = status
        run.finished_at = _now()
        run.heartbeat_at = _now()
        run.version += 1
        if status == "completed":
            run.progress_pct = 100
        if error is not None:
            run.error = error
        if failure_kind is not None:
            run.failure_kind = failure_kind
        await db.commit()
        # Journal the terminal event directly; tracker.end emits the canonical SSE.
        db.add(
            IndexingRunEvent(
                run_id=run.id,
                step="pipeline_end",
                status=status,
                detail=error or f"Pipeline {run.kind} {status}",
                progress_pct=run.progress_pct,
                level="error" if status == "failed" else "info",
            )
        )
        await db.commit()
        await tracker.end(run.workflow_id, run.kind, status, error or "")
        if status == "failed":
            await self._error_log.upsert_from_run(db, run)
        self._manifests.pop(run.id, None)
        _emit_terminal_metrics(run)

    async def request_cancel(self, db: AsyncSession, run_id: str) -> bool:
        run = await db.get(IndexingRun, run_id)
        if run is None or run.status not in _ACTIVE_STATUSES:
            return False
        run.cancel_requested = True
        await db.commit()
        try:
            from app.core import redis_client

            client = redis_client.get_redis()
            if client is not None:
                await client.set(f"cmd:cancel:{run_id}", "1", ex=3600)
        except Exception:  # noqa: BLE001 — Redis is best-effort
            logger.debug("cancel flag redis set failed", exc_info=True)
        return True

    async def retry(self, db: AsyncSession, run_id: str, *, force_full: bool) -> IndexingRun:
        old = await db.get(IndexingRun, run_id)
        if old is None:
            raise KeyError(f"run not found: {run_id}")
        new = await self.start(
            db,
            kind=old.kind,
            project_id=old.project_id,
            connection_id=old.connection_id,
            trigger="manual",
            force_full=force_full,
        )
        # Merge provenance onto the snapshot `start` already wrote — never clobber
        # the flag snapshot (meta_json["flags"]) that makes the run diagnosable.
        meta = json.loads(new.meta_json or "{}")
        meta.update({"force_full": force_full, "retried_from": old.id})
        new.meta_json = json.dumps(meta)
        await db.commit()
        return new

    # -- persistence hook: map pipeline-emitted workflow events onto the run ----

    def attach(self) -> None:
        """Register the run-projection persistence hook (idempotent, process-wide)."""
        if RunCoordinator._attached:
            return
        tracker.add_persistence_hook(self._on_event)
        RunCoordinator._attached = True

    async def _on_event(self, event: WorkflowEvent) -> None:
        # Guard 1: coordinator-emitted events already carry run_id and were
        # persisted in-process by _record/finish — never double-write them.
        if event.run_id is not None:
            return
        # Guard 2: cross-process echo (Redis -> API). The process that actually
        # executes the pipeline persists the event; the receiver only relays SSE.
        if tracker._external_rebroadcast:
            return
        run_id = RunCoordinator._wf_to_run.get(event.workflow_id)
        async with async_session_factory() as db:
            run = None
            if run_id is not None:
                run = await db.get(IndexingRun, run_id)
            if run is None:
                stmt = select(IndexingRun).where(IndexingRun.workflow_id == event.workflow_id)
                run = (await db.execute(stmt)).scalar_one_or_none()
            if run is None or run.status in _TERMINAL_STATUSES:
                return
            RunCoordinator._wf_to_run[event.workflow_id] = run.id
            await self._apply_event(db, run, event)

    async def _apply_event(self, db: AsyncSession, run: IndexingRun, event: WorkflowEvent) -> None:
        manifest = self._manifest_for(run)
        if event.step == "pipeline_start":
            return
        if event.step == "pipeline_end":
            terminal = (
                "cancelled"
                if run.cancel_requested
                else ("failed" if event.status == "failed" else "completed")
            )
            run.status = terminal
            run.finished_at = _now()
            run.heartbeat_at = _now()
            run.version += 1
            if terminal == "completed":
                run.progress_pct = 100
            elif event.detail:
                run.error = event.detail
            if terminal == "failed":
                run.failure_kind = run.failure_kind or "fatal"
            await db.commit()
            await self._journal(
                db,
                run,
                event.step,
                terminal,
                event.detail or "",
                level="error" if terminal == "failed" else "info",
            )
            if terminal == "failed":
                await self._error_log.upsert_from_run(db, run)
            RunCoordinator._wf_to_run.pop(run.workflow_id, None)
            self._manifests.pop(run.id, None)
            _emit_terminal_metrics(run)
            return
        try:
            position = step_position(manifest, event.step)
        except KeyError:
            # Free-form detail emit (not a manifest step): journal only.
            await self._journal(db, run, event.step, event.status, event.detail or "")
            return
        if event.status == "started":
            if run.step_index == 0:
                _emit_ttfp_metric(run)
            run.current_step = event.step
            run.step_index = position
            run.heartbeat_at = _now()
            await db.commit()
            await self._journal(db, run, event.step, "started", event.detail or "")
        elif event.status in ("completed", "skipped"):
            run.progress_pct = progress_for(manifest, position)
            run.heartbeat_at = _now()
            run.version += 1
            await db.commit()
            await self._journal(
                db, run, event.step, event.status, event.detail or "", elapsed_ms=event.elapsed_ms
            )
        elif event.status == "failed":
            await self._journal(
                db,
                run,
                event.step,
                "failed",
                event.detail or "",
                elapsed_ms=event.elapsed_ms,
                level="error",
            )

    async def _journal(
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
