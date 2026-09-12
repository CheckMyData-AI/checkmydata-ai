"""Central workflow tracking and observability system.

Emits structured step events for pipeline operations (indexing, querying)
and broadcasts them to SSE subscribers for real-time progress reporting.
"""

import asyncio
import contextvars
import dataclasses
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

workflow_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "workflow_id",
    default=None,
)

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id",
    default=None,
)


@dataclass
class WorkflowEvent:
    workflow_id: str
    step: str
    status: str  # started | completed | failed | skipped
    detail: str = ""
    elapsed_ms: float | None = None
    timestamp: float = field(default_factory=time.time)
    pipeline: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    # T14: structured span type emitted directly by the producer so downstream
    # trace persistence does not depend on fragile string parsing of ``step``.
    # One of: llm_call | db_query | rag | tool_call | sub_agent | viz |
    # validation | other. ``None`` preserves the heuristic fallback.
    span_type: str | None = None
    # First-class run/progress fields (sync & observability redesign). Background
    # runs carry these so the frontend renders N/M + percent without parsing.
    run_id: str | None = None
    kind: str | None = None
    step_index: int | None = None
    total_steps: int | None = None
    progress_pct: int | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)


BACKGROUND_PIPELINES = frozenset({"index_repo", "db_index", "code_db_sync", "daily_sync"})

ESSENTIAL_STEPS = frozenset(
    {
        "pipeline_end",
        "result",
        "answer",
        "error",
        "clarification",
        "interactive_required",
    }
)


def _is_essential(event: "WorkflowEvent") -> bool:
    return event.step in ESSENTIAL_STEPS or (
        event.status in {"failed", "completed"} and event.step == "pipeline_end"
    )


@dataclass
class _Subscriber:
    """SSE subscriber entry with optional tenancy filter.

    - ``user_id=None`` disables tenancy (admins / tests / internal use).
    - Otherwise the caller sees events whose workflow owner's ``user_id``
      matches or whose ``project_id`` is in ``accessible_project_ids``.
    """

    queue: asyncio.Queue["WorkflowEvent"]
    user_id: str | None = None
    accessible_project_ids: frozenset[str] = field(default_factory=frozenset)


class WorkflowTracker:
    """In-memory event bus that broadcasts workflow step events to subscribers."""

    _ENDED_SET_MAX = 2000
    _OWNERS_MAX = 2000

    #: Margin over the longest job this product can run, for the active-workflow map.
    #: An entry is removed by a matching `pipeline_end`; drop that one message — a
    #: worker SIGKILL mid-publish, a Redis blip — and nothing else ever removes it,
    #: so `/api/tasks/active` reports the workflow running for ever, to every member
    #: of the project (COR-08). The ceiling is derived from the job budgets rather
    #: than guessed, because a constant here would go stale the moment one moves.
    _ACTIVE_AGE_MARGIN_SECONDS = 3600

    def __init__(self) -> None:
        self._subscribers: list[_Subscriber] = []
        self._lock = asyncio.Lock()
        self._active_workflows: dict[str, dict[str, Any]] = {}
        self._workflow_owners: dict[str, dict[str, str]] = {}
        self._persistence_hooks: list[Any] = []
        self._ended_workflows: set[str] = set()
        self._cross_process_publish = False
        self._external_rebroadcast = False

    def enable_cross_process_publish(self) -> None:
        """Worker process: publish events to Redis for API SSE subscribers."""
        self._cross_process_publish = True

    def add_persistence_hook(self, callback: Any) -> None:
        """Register an async callback invoked on every broadcast (fire-and-forget)."""
        self._persistence_hooks.append(callback)

    async def begin(
        self,
        pipeline: str,
        context: dict[str, Any] | None = None,
        *,
        broadcast: bool = True,
    ) -> str:
        """Open a workflow and, by default, announce its start.

        Pass ``broadcast=False`` when the caller will emit the canonical
        ``pipeline_start`` itself — :class:`RunCoordinator` does, because only it
        knows the ``run_id`` the UI needs to attach the step to a run. Without
        the opt-out both fire and every subscriber sees the step twice
        (AUD-0819-04). The workflow is registered either way; only the event is
        withheld.
        """
        wf_id = str(uuid.uuid4())
        workflow_id_var.set(wf_id)

        extra = context or {}
        uid = str(extra.get("user_id") or "")
        pid = str(extra.get("project_id") or "")
        self._remember_owner(wf_id, uid, pid)
        if pipeline in BACKGROUND_PIPELINES:
            self._remember_active(wf_id, pipeline, time.time(), extra)

        if broadcast:
            event = WorkflowEvent(
                workflow_id=wf_id,
                step="pipeline_start",
                status="started",
                detail=f"Starting {pipeline}",
                pipeline=pipeline,
                extra=extra,
            )
            await self._broadcast(event)
        return wf_id

    async def end(
        self, workflow_id: str, pipeline: str, status: str = "completed", detail: str = ""
    ) -> None:
        self._mark_ended(workflow_id)

        event = WorkflowEvent(
            workflow_id=workflow_id,
            step="pipeline_end",
            status=status,
            detail=detail or f"Pipeline {pipeline} {status}",
            pipeline=pipeline,
        )
        try:
            await self._broadcast(event)
        except Exception:
            logger.warning(
                "Failed to broadcast pipeline_end for workflow %s",
                workflow_id[:8],
                exc_info=True,
            )
        finally:
            workflow_id_var.set(None)

    # ------------------------------------------------------------------
    # The three maps have ONE writer each (COR-08).
    #
    # Before this, `begin()` and `end()` applied the caps and `broadcast_external`
    # — the path every worker workflow takes to reach the web dyno — applied
    # neither. So on the process that serves users, where no workflow is ever begun
    # or ended locally, the bounds guarding these maps were dead code.
    # ------------------------------------------------------------------

    def _remember_owner(self, workflow_id: str, user_id: str, project_id: str) -> None:
        if not user_id and not project_id:
            return
        self._workflow_owners[workflow_id] = {"user_id": user_id, "project_id": project_id}
        # L2: bound the owners map independently of end(). The end()-time eviction
        # only drops owners of ENDED workflows; a workflow that never reaches end()
        # (crash, abandoned) would otherwise leak its entry forever. FIFO-evict the
        # oldest half when over the cap.
        if len(self._workflow_owners) > self._OWNERS_MAX:
            for old in list(self._workflow_owners)[: self._OWNERS_MAX // 2]:
                self._workflow_owners.pop(old, None)

    def _mark_ended(self, workflow_id: str) -> None:
        self._active_workflows.pop(workflow_id, None)
        self._ended_workflows.add(workflow_id)
        if len(self._ended_workflows) > self._ENDED_SET_MAX:
            to_remove = list(self._ended_workflows)[: self._ENDED_SET_MAX // 2]
            self._ended_workflows -= set(to_remove)
            for old in to_remove:
                self._workflow_owners.pop(old, None)

    def _remember_active(
        self, workflow_id: str, pipeline: str, started_at: float, extra: dict[str, Any]
    ) -> None:
        self._active_workflows[workflow_id] = {
            "workflow_id": workflow_id,
            "pipeline": pipeline,
            "started_at": started_at,
            "extra": extra,
        }
        self._expire_active()

    def _active_max_age_seconds(self) -> float:
        """The longest a workflow could still honestly be running.

        Derived from the job budgets rather than hardcoded: ARQ cancels at these,
        so an entry older than the largest of them plus a margin describes a job
        that cannot still exist. Reading them here means raising a budget moves
        this ceiling with it instead of leaving a stale constant behind.
        """
        from app.config import settings

        budgets = [
            getattr(settings, name, 0) or 0
            for name in (
                "repo_index_job_timeout_seconds",
                "daily_knowledge_sync_job_timeout_seconds",
                "db_index_job_timeout_seconds",
                "analytics_collect_job_timeout_seconds",
            )
        ]
        return float(max(budgets) or 0) + self._ACTIVE_AGE_MARGIN_SECONDS

    def _expire_active(self, now: float | None = None) -> None:
        """Drop active entries no job could still be inside (COR-08)."""
        moment = now if now is not None else time.time()
        cutoff = moment - self._active_max_age_seconds()
        stale = [
            (wf_id, float(entry.get("started_at") or 0))
            for wf_id, entry in self._active_workflows.items()
            if float(entry.get("started_at") or 0) < cutoff
        ]
        for wf_id, started_at in stale:
            self._active_workflows.pop(wf_id, None)
            # Read the age BEFORE the pop, or the line reports the epoch.
            logger.info(
                "workflow[%s] dropped from the active map after %.0fs — longer than "
                "any job budget, so its pipeline_end never arrived (project=%s)",
                wf_id[:8],
                moment - started_at,
                self._workflow_owners.get(wf_id, {}).get("project_id", "?"),
            )

    def has_ended(self, workflow_id: str) -> bool:
        """Check whether ``end()`` was already called for *workflow_id*."""
        return workflow_id in self._ended_workflows

    def get_owner(self, workflow_id: str) -> dict[str, str]:
        """Return ``{'user_id','project_id'}`` for the workflow (may be empty)."""
        return self._workflow_owners.get(workflow_id, {})

    def get_active(
        self,
        *,
        user_id: str | None = None,
        accessible_project_ids: set[str] | frozenset[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return a snapshot of currently running background workflows.

        When ``user_id`` is provided, the list is filtered to workflows owned
        by that user or belonging to one of ``accessible_project_ids`` (member
        of the project). Pass ``user_id=None`` for unfiltered access (admins,
        tests, internal use).
        """
        self._expire_active()
        snapshot = list(self._active_workflows.values())
        if user_id is None:
            return snapshot
        accessible = set(accessible_project_ids or ())
        out: list[dict[str, Any]] = []
        for entry in snapshot:
            extra = entry.get("extra", {}) or {}
            wf_uid = str(extra.get("user_id") or "")
            wf_pid = str(extra.get("project_id") or "")
            if wf_uid and wf_uid == user_id:
                out.append(entry)
                continue
            if wf_pid and wf_pid in accessible:
                out.append(entry)
                continue
        return out

    def _resolve_pipeline(self, workflow_id: str) -> str:
        entry = self._active_workflows.get(workflow_id)
        return entry["pipeline"] if entry else ""

    def _event_matches_subscriber(self, event: "WorkflowEvent", sub: _Subscriber) -> bool:
        """True when ``sub`` is allowed to see ``event`` under tenancy rules."""
        if sub.user_id is None:
            return True
        owner = self._workflow_owners.get(event.workflow_id, {})
        wf_uid = owner.get("user_id") or str(event.extra.get("user_id") or "")
        wf_pid = owner.get("project_id") or str(event.extra.get("project_id") or "")
        if wf_uid and wf_uid == sub.user_id:
            return True
        if wf_pid and wf_pid in sub.accessible_project_ids:
            return True
        return False

    @asynccontextmanager
    async def step(
        self,
        workflow_id: str,
        step_name: str,
        detail: str = "",
        step_data: dict[str, Any] | None = None,
        *,
        span_type: str | None = None,
    ):
        """Context manager that emits started/completed/failed events.

        ``step_data`` is a mutable dict that the caller can populate inside the
        ``async with`` block.  Its contents are forwarded as ``extra`` on the
        completion (or failure) event so that TracePersistenceService can store
        input/output previews and token usage alongside the span.

        ``span_type`` (T14): structured span type (``llm_call``, ``db_query``,
        ``rag``, ``tool_call``, ``sub_agent``, ``viz``, ``validation``). Emit
        this explicitly to remove the dependency on downstream string parsing.
        """
        pipeline = self._resolve_pipeline(workflow_id)
        start_event = WorkflowEvent(
            workflow_id=workflow_id,
            step=step_name,
            status="started",
            detail=detail,
            pipeline=pipeline,
            span_type=span_type,
        )
        await self._broadcast(start_event)
        t0 = time.monotonic()
        try:
            yield
            elapsed = (time.monotonic() - t0) * 1000
            end_event = WorkflowEvent(
                workflow_id=workflow_id,
                step=step_name,
                status="completed",
                detail=detail,
                elapsed_ms=round(elapsed, 1),
                pipeline=pipeline,
                extra=dict(step_data) if step_data else {},
                span_type=span_type,
            )
            await self._broadcast(end_event)
        except Exception as exc:
            elapsed = (time.monotonic() - t0) * 1000
            fail_event = WorkflowEvent(
                workflow_id=workflow_id,
                step=step_name,
                status="failed",
                detail=str(exc),
                elapsed_ms=round(elapsed, 1),
                pipeline=pipeline,
                extra=dict(step_data) if step_data else {},
                span_type=span_type,
            )
            await self._broadcast(fail_event)
            raise

    async def emit(
        self,
        workflow_id: str,
        step: str,
        status: str,
        detail: str = "",
        *,
        span_type: str | None = None,
        run_id: str | None = None,
        kind: str | None = None,
        step_index: int | None = None,
        total_steps: int | None = None,
        progress_pct: int | None = None,
        **extra: Any,
    ) -> None:
        event = WorkflowEvent(
            workflow_id=workflow_id,
            step=step,
            status=status,
            detail=detail,
            pipeline=self._resolve_pipeline(workflow_id),
            extra=extra,
            span_type=span_type,
            run_id=run_id,
            kind=kind,
            step_index=step_index,
            total_steps=total_steps,
            progress_pct=progress_pct,
        )
        await self._broadcast(event)

    _QUEUE_MAXSIZE = 1024

    async def subscribe(
        self,
        *,
        user_id: str | None = None,
        accessible_project_ids: set[str] | frozenset[str] | None = None,
    ) -> asyncio.Queue[WorkflowEvent]:
        """Register a subscriber and return its event queue.

        Pass ``user_id=None`` (default) to opt out of tenancy filtering. Pass
        a concrete user id together with ``accessible_project_ids`` to filter
        events down to workflows the user owns or is a member of.
        """
        queue: asyncio.Queue[WorkflowEvent] = asyncio.Queue(maxsize=self._QUEUE_MAXSIZE)
        sub = _Subscriber(
            queue=queue,
            user_id=user_id,
            accessible_project_ids=frozenset(accessible_project_ids or ()),
        )
        async with self._lock:
            self._subscribers.append(sub)
        return queue

    @staticmethod
    def _drop_oldest_non_essential(queue: asyncio.Queue["WorkflowEvent"]) -> int:
        """Best-effort drop of oldest non-essential events from *queue*.

        Returns number of events dropped. We rebuild the queue's internal deque
        in-place to skip non-essential events while preserving order of the rest.
        """
        try:
            internal = queue._queue  # type: ignore[attr-defined]
        except AttributeError:
            return 0
        before = len(internal)
        if before == 0:
            return 0
        kept = [e for e in internal if _is_essential(e)]
        dropped = before - len(kept)
        if dropped <= 0:
            return 0
        internal.clear()
        for e in kept:
            internal.append(e)
        return dropped

    async def unsubscribe(self, queue: asyncio.Queue[WorkflowEvent]) -> None:
        async with self._lock:
            self._subscribers = [s for s in self._subscribers if s.queue is not queue]

    async def broadcast_external(self, event: WorkflowEvent) -> None:
        """Deliver an event received from another process (Redis) to local SSE only."""
        # Tolerate unknown/extra keys as the event contract evolves (greenfield-safe):
        # rebuild from known dataclass fields so a future field never drops an event.
        _fields = {f.name for f in dataclasses.fields(WorkflowEvent)}
        if any(k not in _fields for k in vars(event)):
            event = WorkflowEvent(**{k: v for k, v in vars(event).items() if k in _fields})
        self._external_rebroadcast = True
        try:
            if event.step == "pipeline_start" and event.pipeline in BACKGROUND_PIPELINES:
                self._remember_active(
                    event.workflow_id, event.pipeline, event.timestamp, event.extra or {}
                )
                self._remember_owner(
                    event.workflow_id,
                    str((event.extra or {}).get("user_id") or ""),
                    str((event.extra or {}).get("project_id") or ""),
                )
            elif event.step == "pipeline_end":
                self._mark_ended(event.workflow_id)
            await self._deliver_local(event)
        finally:
            self._external_rebroadcast = False

    async def _broadcast(self, event: WorkflowEvent) -> None:
        await self._deliver_local(event)
        if self._cross_process_publish and not self._external_rebroadcast:
            from app.core.workflow_events import publish_workflow_event

            await publish_workflow_event(event)

    async def _deliver_local(self, event: WorkflowEvent) -> None:
        short = event.detail[:30] + "…" if len(event.detail) > 30 else event.detail
        logger.info(
            "workflow[%s] %s: %s (%s)%s",
            event.workflow_id[:8],
            event.step,
            event.status,
            short,
            f" {event.elapsed_ms:.0f}ms" if event.elapsed_ms is not None else "",
        )
        essential = _is_essential(event)
        async with self._lock:
            dead: list[_Subscriber] = []
            for sub in self._subscribers:
                if not self._event_matches_subscriber(event, sub):
                    continue
                queue = sub.queue
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    if essential:
                        dropped = self._drop_oldest_non_essential(queue)
                        if dropped:
                            try:
                                queue.put_nowait(event)
                                logger.warning(
                                    "Backpressure: dropped %d non-essential event(s) "
                                    "to deliver essential %s",
                                    dropped,
                                    event.step,
                                )
                                continue
                            except asyncio.QueueFull:
                                pass
                        dead.append(sub)
                    else:
                        logger.debug(
                            "Backpressure: dropping non-essential event %s on full queue",
                            event.step,
                        )
            if dead:
                logger.warning(
                    "Dropping %d subscriber(s) due to full queues with essential events "
                    "undeliverable (maxsize=%d)",
                    len(dead),
                    self._QUEUE_MAXSIZE,
                )
                for s in dead:
                    try:
                        self._subscribers.remove(s)
                    except ValueError:
                        pass
        for hook in self._persistence_hooks:
            try:
                await hook(event)
            except Exception:
                logger.debug("Persistence hook error", exc_info=True)


tracker = WorkflowTracker()
