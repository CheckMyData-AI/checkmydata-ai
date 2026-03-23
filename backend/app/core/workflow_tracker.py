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

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)


BACKGROUND_PIPELINES = frozenset({"index_repo", "db_index", "code_db_sync"})


class WorkflowTracker:
    """In-memory event bus that broadcasts workflow step events to subscribers."""

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[WorkflowEvent]] = []
        self._lock = asyncio.Lock()
        self._active_workflows: dict[str, dict[str, Any]] = {}

    async def begin(self, pipeline: str, context: dict[str, Any] | None = None) -> str:
        wf_id = str(uuid.uuid4())
        workflow_id_var.set(wf_id)

        extra = context or {}
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

    def get_active(self) -> list[dict[str, Any]]:
        """Return a snapshot of currently running background workflows."""
        return list(self._active_workflows.values())

    def _resolve_pipeline(self, workflow_id: str) -> str:
        entry = self._active_workflows.get(workflow_id)
        return entry["pipeline"] if entry else ""

    @asynccontextmanager
    async def step(self, workflow_id: str, step_name: str, detail: str = ""):
        pipeline = self._resolve_pipeline(workflow_id)
        start_event = WorkflowEvent(
            workflow_id=workflow_id,
            step=step_name,
            status="started",
            detail=detail,
            pipeline=pipeline,
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
            )
            await self._broadcast(fail_event)
            raise

    async def emit(
        self, workflow_id: str, step: str, status: str, detail: str = "", **extra: Any
    ) -> None:
        event = WorkflowEvent(
            workflow_id=workflow_id,
            step=step,
            status=status,
            detail=detail,
            pipeline=self._resolve_pipeline(workflow_id),
            extra=extra,
        )
        await self._broadcast(event)

    _QUEUE_MAXSIZE = 1024

    async def subscribe(self) -> asyncio.Queue[WorkflowEvent]:
        queue: asyncio.Queue[WorkflowEvent] = asyncio.Queue(maxsize=self._QUEUE_MAXSIZE)
        async with self._lock:
            self._subscribers.append(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue[WorkflowEvent]) -> None:
        async with self._lock:
            try:
                self._subscribers.remove(queue)
            except ValueError:
                pass

    async def _broadcast(self, event: WorkflowEvent) -> None:
        logger.info(
            "workflow[%s] %s: %s (%s)%s",
            event.workflow_id[:8],
            event.step,
            event.status,
            event.detail,
            f" {event.elapsed_ms:.0f}ms" if event.elapsed_ms is not None else "",
        )
        async with self._lock:
            dead: list[asyncio.Queue[WorkflowEvent]] = []
            for queue in self._subscribers:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    dead.append(queue)
            if dead:
                logger.warning(
                    "Dropping %d subscriber(s) due to full queues (maxsize=%d)",
                    len(dead),
                    self._QUEUE_MAXSIZE,
                )
                for q in dead:
                    try:
                        self._subscribers.remove(q)
                    except ValueError:
                        pass


tracker = WorkflowTracker()
