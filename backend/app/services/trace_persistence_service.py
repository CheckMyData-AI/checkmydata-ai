"""Persists WorkflowTracker events into request_traces / trace_spans tables.

Accumulates span events in memory per workflow_id, then batch-inserts them
when the workflow ends. All persistence is fire-and-forget so it never blocks
the chat response path.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.workflow_tracker import WorkflowEvent, WorkflowTracker
from app.models.base import async_session_factory
from app.models.request_trace import RequestTrace, TraceSpan

logger = logging.getLogger(__name__)

_PREVIEW_MAX_LEN = 1000
_STALE_BUFFER_SECONDS = 300  # 5 minutes


SPAN_TYPE_MAP: dict[str, str] = {
    # Orchestrator
    "orchestrator:llm_call": "llm_call",
    "orchestrator:planning": "tool_call",
    "orchestrator:sql_agent": "sub_agent",
    "orchestrator:knowledge_agent": "sub_agent",
    "orchestrator:mcp_source_agent": "sub_agent",
    "orchestrator:manage_rules": "tool_call",
    "orchestrator:viz": "viz",
    # SQL agent
    "sql:llm_call": "llm_call",
    "sql:tool:execute_query": "db_query",
    "sql:tool:get_schema_info": "db_query",
    "sql:tool:get_db_index": "rag",
    "sql:tool:get_query_context": "rag",
    "sql:tool:get_sync_context": "rag",
    "sql:tool:record_learning": "tool_call",
    "sql:tool:read_notes": "tool_call",
    "sql:tool:write_note": "tool_call",
    # Knowledge agent
    "knowledge:llm_call": "llm_call",
    "knowledge:tool:search_knowledge": "rag",
    "knowledge:tool:get_entity_info": "rag",
    # Validation loop
    "execute_query": "db_query",
    "safety_check": "validation",
    "pre_validate": "validation",
    "post_validate": "validation",
    "explain_check": "validation",
    "error_classify": "validation",
    "query_repair": "validation",
    # Standalone LLM endpoints
    "generate_title:llm_call": "llm_call",
    "explain_sql:llm_call": "llm_call",
    "summarize:llm_call": "llm_call",
    # Other
    "build_query": "tool_call",
    "render_viz": "viz",
    "rag_context": "rag",
    "load_rules": "rag",
    "interpret_results": "llm_call",
    "load_context": "rag",
}

_SUB_AGENT_PREFIXES = (
    "sql_agent:",
    "knowledge_agent:",
    "viz_agent:",
    "mcp_source_agent:",
    "orchestrator:",
    "sql:",
    "knowledge:",
)


def classify_span_type(step_name: str) -> str:
    if step_name in SPAN_TYPE_MAP:
        return SPAN_TYPE_MAP[step_name]
    for prefix in _SUB_AGENT_PREFIXES:
        if step_name.startswith(prefix):
            return "sub_agent"
    if "llm" in step_name.lower():
        return "llm_call"
    if "query" in step_name.lower() or "execute" in step_name.lower():
        return "db_query"
    return "tool_call"


def _truncate(text: str | None, max_len: int = _PREVIEW_MAX_LEN) -> str | None:
    if text is None:
        return None
    return text[:max_len] if len(text) > max_len else text


class _WorkflowBuffer:
    """In-memory accumulator for a single workflow's events."""

    __slots__ = ("workflow_id", "pipeline", "events", "started_at", "context")

    def __init__(self, workflow_id: str, pipeline: str, context: dict[str, Any]) -> None:
        self.workflow_id = workflow_id
        self.pipeline = pipeline
        self.events: list[WorkflowEvent] = []
        self.started_at = time.time()
        self.context = context


class TracePersistenceService:
    """Collects workflow events and persists them as traces + spans."""

    def __init__(self, tracker: WorkflowTracker) -> None:
        self._tracker = tracker
        self._buffers: dict[str, _WorkflowBuffer] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._tracker.add_persistence_hook(self._on_event)
        self._cleanup_task = asyncio.create_task(self._cleanup_stale_buffers())
        logger.info("TracePersistenceService started")

    async def stop(self) -> None:
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        logger.info("TracePersistenceService stopped")

    async def _on_event(self, event: WorkflowEvent) -> None:
        """Called by WorkflowTracker on every broadcast."""
        try:
            async with self._lock:
                if event.step == "pipeline_start":
                    self._buffers[event.workflow_id] = _WorkflowBuffer(
                        workflow_id=event.workflow_id,
                        pipeline=event.pipeline,
                        context=event.extra,
                    )
                    return

                buf = self._buffers.get(event.workflow_id)
                if buf is None:
                    return

                buf.events.append(event)

                if event.step == "pipeline_end":
                    self._buffers.pop(event.workflow_id, None)

            if event.step == "pipeline_end":
                asyncio.create_task(self._persist_workflow(buf, event))

        except Exception:
            logger.warning(
                "TracePersistence: failed to process event for wf=%s",
                event.workflow_id[:8],
                exc_info=True,
            )

    async def finalize_trace(
        self,
        workflow_id: str,
        *,
        project_id: str,
        user_id: str,
        session_id: str | None = None,
        message_id: str | None = None,
        assistant_message_id: str | None = None,
        question: str = "",
        response_type: str = "text",
        status: str = "completed",
        error_message: str | None = None,
        total_duration_ms: float | None = None,
        total_tokens: int = 0,
        estimated_cost_usd: float | None = None,
        llm_provider: str = "unknown",
        llm_model: str = "unknown",
        steps_used: int = 0,
        steps_total: int = 0,
        tool_call_log: list[dict] | None = None,
    ) -> None:
        """Attach chat-route metadata to the trace and persist if buffer was already flushed.

        Called from chat.py after the assistant message is saved.
        """
        try:
            async with async_session_factory() as session:
                from sqlalchemy import select, update

                stmt = select(RequestTrace).where(RequestTrace.workflow_id == workflow_id).limit(1)
                result = await session.execute(stmt)
                trace = result.scalar_one_or_none()

                if trace is not None:
                    upd = (
                        update(RequestTrace)
                        .where(RequestTrace.id == trace.id)
                        .values(
                            project_id=project_id,
                            user_id=user_id,
                            session_id=session_id,
                            message_id=message_id,
                            assistant_message_id=assistant_message_id,
                            question=_truncate(question, 500) or "",
                            response_type=response_type,
                            status=status,
                            error_message=_truncate(error_message),
                            total_duration_ms=total_duration_ms,
                            total_tokens=total_tokens,
                            estimated_cost_usd=estimated_cost_usd,
                            llm_provider=llm_provider,
                            llm_model=llm_model,
                            steps_used=steps_used,
                            steps_total=steps_total,
                        )
                    )
                    await session.execute(upd)
                    await session.commit()
                else:
                    spans = self._build_spans_from_tool_log(tool_call_log or [])
                    llm_count = sum(1 for s in spans if s["span_type"] == "llm_call")
                    db_count = sum(1 for s in spans if s["span_type"] == "db_query")

                    trace = RequestTrace(
                        project_id=project_id,
                        user_id=user_id,
                        session_id=session_id,
                        message_id=message_id,
                        assistant_message_id=assistant_message_id,
                        workflow_id=workflow_id,
                        question=_truncate(question, 500) or "",
                        response_type=response_type,
                        status=status,
                        error_message=_truncate(error_message),
                        total_duration_ms=total_duration_ms,
                        total_llm_calls=llm_count,
                        total_db_queries=db_count,
                        total_tokens=total_tokens,
                        estimated_cost_usd=estimated_cost_usd,
                        llm_provider=llm_provider,
                        llm_model=llm_model,
                        steps_used=steps_used,
                        steps_total=steps_total,
                    )
                    session.add(trace)
                    await session.flush()

                    for i, sd in enumerate(spans):
                        span = TraceSpan(
                            trace_id=trace.id,
                            span_type=sd["span_type"],
                            name=sd["name"],
                            status=sd["status"],
                            detail=sd.get("detail", ""),
                            duration_ms=sd.get("duration_ms"),
                            input_preview=_truncate(sd.get("input_preview")),
                            output_preview=_truncate(sd.get("output_preview")),
                            metadata_json=sd.get("metadata_json"),
                            order_index=i,
                        )
                        session.add(span)
                    await session.commit()

        except Exception:
            logger.warning(
                "TracePersistence: failed to finalize trace for wf=%s",
                workflow_id[:8],
                exc_info=True,
            )

    def _build_spans_from_tool_log(self, tool_call_log: list[dict]) -> list[dict]:
        """Build span dicts from the orchestrator's tool_call_log (fallback path)."""
        spans: list[dict] = []
        for entry in tool_call_log:
            name = entry.get("tool", entry.get("name", "unknown"))
            span_type = classify_span_type(name)
            raw_args = entry.get("arguments") or entry.get("args") or {}
            raw_result = entry.get("result_preview") or entry.get("result") or ""
            spans.append(
                {
                    "span_type": span_type,
                    "name": name,
                    "status": "completed" if not entry.get("error") else "failed",
                    "detail": str(entry.get("error", ""))[:500],
                    "duration_ms": entry.get("elapsed_ms"),
                    "input_preview": _truncate(
                        json.dumps(raw_args, default=str) if raw_args else None
                    ),
                    "output_preview": _truncate(str(raw_result)[:500] if raw_result else None),
                }
            )
        return spans

    _SKIP_STEPS = frozenset(
        {
            "pipeline_start",
            "pipeline_end",
            "thinking",
            "token",
            "orchestrator:warning",
            "orchestrator:llm_retry",
        }
    )

    _TOKEN_USAGE_KEYS = ("prompt_tokens", "completion_tokens", "total_tokens", "model")

    @staticmethod
    def _extract_token_usage(extra: dict[str, Any]) -> str | None:
        if not any(k in extra for k in TracePersistenceService._TOKEN_USAGE_KEYS):
            return None
        return json.dumps(
            {k: extra[k] for k in TracePersistenceService._TOKEN_USAGE_KEYS if k in extra}
        )

    @staticmethod
    def _extra_to_metadata(extra: dict[str, Any]) -> str | None:
        """Serialize extra dict to JSON, excluding keys already stored in dedicated columns."""
        remaining = {
            k: v
            for k, v in extra.items()
            if k
            not in ("input_preview", "output_preview", *TracePersistenceService._TOKEN_USAGE_KEYS)
        }
        return json.dumps(remaining, default=str) if remaining else None

    async def _persist_workflow(self, buf: _WorkflowBuffer, end_event: WorkflowEvent) -> None:
        """Batch-insert a RequestTrace with all its spans."""
        try:
            events = buf.events
            start_ts = buf.started_at
            end_ts = end_event.timestamp
            total_duration_ms = (end_ts - start_ts) * 1000

            span_dicts: list[dict[str, Any]] = []
            order = 0
            llm_count = 0
            db_count = 0

            for evt in events:
                if evt.step in self._SKIP_STEPS:
                    continue

                if evt.status == "started":
                    continue

                # Deduplicate: emit-based execute_query has no elapsed_ms
                if evt.step == "execute_query" and evt.elapsed_ms is None:
                    continue

                span_type = classify_span_type(evt.step)

                if span_type == "llm_call":
                    llm_count += 1
                elif span_type == "db_query":
                    db_count += 1

                extra = evt.extra or {}
                input_preview = _truncate(extra.get("input_preview"))
                output_preview = _truncate(extra.get("output_preview"))
                token_usage = self._extract_token_usage(extra)

                span_dicts.append(
                    {
                        "span_type": span_type,
                        "name": evt.step,
                        "status": evt.status,
                        "detail": _truncate(evt.detail, 500) or "",
                        "started_at": datetime.fromtimestamp(
                            evt.timestamp - (evt.elapsed_ms / 1000 if evt.elapsed_ms else 0),
                            tz=UTC,
                        ),
                        "ended_at": datetime.fromtimestamp(evt.timestamp, tz=UTC),
                        "duration_ms": evt.elapsed_ms,
                        "input_preview": input_preview,
                        "output_preview": output_preview,
                        "token_usage_json": token_usage,
                        "metadata_json": self._extra_to_metadata(extra),
                        "order_index": order,
                    }
                )
                order += 1

            end_status = end_event.status
            if end_status == "completed":
                trace_status = "completed"
            elif end_status == "clarification":
                trace_status = "completed"
            else:
                trace_status = "failed"

            context = buf.context
            project_id = context.get("project_id") or ""
            user_id = context.get("user_id") or ""

            if not project_id or not user_id:
                logger.warning(
                    "TracePersistence: skipping initial persist for wf=%s — "
                    "empty project_id=%r / user_id=%r (finalize_trace will create it)",
                    buf.workflow_id[:8],
                    project_id,
                    user_id,
                )
                return

            async with async_session_factory() as session:
                trace = RequestTrace(
                    project_id=project_id,
                    user_id=user_id,
                    workflow_id=buf.workflow_id,
                    question=_truncate(context.get("question", ""), 500) or "",
                    status=trace_status,
                    error_message=_truncate(end_event.detail) if trace_status == "failed" else None,
                    total_duration_ms=round(total_duration_ms, 1),
                    total_llm_calls=llm_count,
                    total_db_queries=db_count,
                    llm_provider="unknown",
                    llm_model="unknown",
                )
                session.add(trace)
                await session.flush()

                for sd in span_dicts:
                    span = TraceSpan(
                        trace_id=trace.id,
                        span_type=sd["span_type"],
                        name=sd["name"],
                        status=sd["status"],
                        detail=sd["detail"],
                        started_at=sd["started_at"],
                        ended_at=sd["ended_at"],
                        duration_ms=sd["duration_ms"],
                        input_preview=sd.get("input_preview"),
                        output_preview=sd.get("output_preview"),
                        token_usage_json=sd.get("token_usage_json"),
                        metadata_json=sd.get("metadata_json"),
                        order_index=sd["order_index"],
                    )
                    session.add(span)

                await session.commit()
                logger.debug(
                    "TracePersistence: saved trace wf=%s with %d spans",
                    buf.workflow_id[:8],
                    len(span_dicts),
                )

        except Exception:
            logger.warning(
                "TracePersistence: failed to persist workflow wf=%s",
                buf.workflow_id[:8],
                exc_info=True,
            )

    async def _cleanup_stale_buffers(self) -> None:
        """Periodically persist stale buffers that never received pipeline_end."""
        while True:
            await asyncio.sleep(60)
            try:
                now = time.time()
                stale_bufs: list[_WorkflowBuffer] = []
                async with self._lock:
                    stale_ids = [
                        wf_id
                        for wf_id, buf in self._buffers.items()
                        if now - buf.started_at > _STALE_BUFFER_SECONDS
                    ]
                    for wf_id in stale_ids:
                        buf = self._buffers.pop(wf_id, None)
                        if buf is not None:
                            stale_bufs.append(buf)
                for buf in stale_bufs:
                    synthetic_end = WorkflowEvent(
                        workflow_id=buf.workflow_id,
                        step="pipeline_end",
                        status="failed",
                        detail="Stale: pipeline_end never received",
                        pipeline=buf.pipeline,
                    )
                    try:
                        await self._persist_workflow(buf, synthetic_end)
                    except Exception:
                        logger.warning(
                            "TracePersistence: failed to persist stale buffer wf=%s",
                            buf.workflow_id[:8],
                            exc_info=True,
                        )
                if stale_bufs:
                    logger.info(
                        "TracePersistence: persisted %d stale buffer(s) as failed traces",
                        len(stale_bufs),
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("TracePersistence: cleanup error", exc_info=True)

    async def cleanup_old_traces(self, retention_days: int = 90) -> int:
        """Delete traces older than retention_days. Returns count deleted."""
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        try:
            async with async_session_factory() as session:
                from sqlalchemy import delete

                stmt = delete(RequestTrace).where(RequestTrace.created_at < cutoff)
                result = await session.execute(stmt)
                await session.commit()
                count = result.rowcount  # type: ignore[attr-defined]
                if count:
                    logger.info("TracePersistence: deleted %d old trace(s)", count)
                return count
        except Exception:
            logger.warning("TracePersistence: cleanup_old_traces failed", exc_info=True)
            return 0
