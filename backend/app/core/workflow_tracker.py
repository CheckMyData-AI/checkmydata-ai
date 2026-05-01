"""Central workflow tracking and observability system.

Emits structured step events for pipeline operations (indexing, querying)
and broadcasts them to SSE subscribers for real-time progress reporting.
"""

import asyncio
import contextvars
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

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)


BACKGROUND_PIPELINES = frozenset({"index_repo", "db_index", "code_db_sync"})

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

    def __init__(self) -> None:
        self._subscribers: list[_Subscriber] = []
        self._lock = asyncio.Lock()
        self._active_workflows: dict[str, dict[str, Any]] = {}
        self._workflow_owners: dict[str, dict[str, str]] = {}
        self._persistence_hooks: list[Any] = []
        self._ended_workflows: set[str] = set()

    def add_persistence_hook(self, callback: Any) -> None:
        """Register an async callback invoked on every broadcast (fire-and-forget)."""
        self._persistence_hooks.append(callback)

    async def begin(self, pipeline: str, context: dict[str, Any] | None = None) -> str:
        wf_id = str(uuid.uuid4())
        workflow_id_var.set(wf_id)

        extra = context or {}
        uid = str(extra.get("user_id") or "")
        pid = str(extra.get("project_id") or "")
        if uid or pid:
            self._workflow_owners[wf_id] = {"user_id": uid, "project_id": pid}
        if pipeline in BACKGROUND_PIPELINES:
            self._active_workflows[wf_id] = {
                "workflow_id": wf_id,
                "pipeline": pipeline,
                "started_at": time.time(),
                "extra": extra,
            }

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
        self._active_workflows.pop(workflow_id, None)
        self._ended_workflows.add(workflow_id)
        if len(self._ended_workflows) > self._ENDED_SET_MAX:
            to_remove = list(self._ended_workflows)[: self._ENDED_SET_MAX // 2]
            self._ended_workflows -= set(to_remove)
            for old in to_remove:
                self._workflow_owners.pop(old, None)

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

    def _event_matches_subscriber(
        self, event: "WorkflowEvent", sub: _Subscriber
    ) -> bool:
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

    async def _broadcast(self, event: WorkflowEvent) -> None:
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
