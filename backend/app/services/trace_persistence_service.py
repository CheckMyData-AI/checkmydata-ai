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

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.core.failure_kind import kind_for_terminal_detail
from app.core.request_lifetime import longest_request_seconds
from app.core.trace_meta import TraceMeta
from app.core.workflow_tracker import WorkflowEvent, WorkflowTracker
from app.models.base import async_session_factory
from app.models.request_trace import RequestTrace, TraceSpan

logger = logging.getLogger(__name__)

_PREVIEW_MAX_LEN = 1000

#: What a buffer evicted without a ``pipeline_end`` is recorded as. NOT ``failed``:
#: the eviction is a guess that the run is dead, and until PRJ-04 the guess fired at
#: 300 s — below every transport ceiling a live request runs under (REST/SSE 360 s,
#: WS relay 900 s). Production held 26 ``Stale: …`` rows, one of them on a run the
#: chat path later reported ``completed``. A later ``finalize_trace`` replaces it.
PROVISIONAL_STATUS = "provisional"
STALE_DETAIL = "Stale: pipeline_end never received"

#: Terminal ``pipeline_end`` status -> trace status. ``checkpoint`` is a pause that
#: waits for a person, not a failure, and was stored as ``failed`` (O-16).
_END_STATUS_TO_TRACE_STATUS = {
    "completed": "completed",
    "clarification": "completed",
    "checkpoint": "checkpoint",
    PROVISIONAL_STATUS: PROVISIONAL_STATUS,
}

#: How long ``finalize_trace`` waits for the buffer flush of the same workflow before
#: writing on its own. The two used to race, and 65 of 242 production rows were a
#: second row for a workflow that already had one (measured 2026-09-17).
_FLUSH_WAIT_SECONDS = 10.0


def stale_buffer_seconds() -> float:
    """Evict a buffer only after the longest a live request can run."""
    return longest_request_seconds()


def routing_from_events(events: list[WorkflowEvent]) -> tuple[str, str, int] | None:
    """The router's verdict, read from the run's own events (PRJ-04).

    The orchestrator emits it once per workflow, beside the ``Route: …`` line; the
    FIRST one wins, which is the rule ``_wf_routing`` applies (ORCH-07: a
    pipeline→loop bounce re-enters with a synthetic route that must not replace the
    router's). Read here because the buffer is the one record every exit path
    reaches — a crash, a timeout and a stale eviction included — while the
    response-borne copy exists only when the agent returned. 10 of 12 failed traces
    in 30 days read ``route='unknown'`` for that reason.
    """
    for evt in events:
        extra = evt.extra or {}
        route = extra.get("route")
        if isinstance(route, str) and route:
            complexity = extra.get("complexity")
            try:
                estimated = int(extra.get("estimated_queries") or 0)
            except (TypeError, ValueError):
                estimated = 0
            return route, complexity if isinstance(complexity, str) else "unknown", estimated
    return None


async def _find_trace(session: Any, workflow_id: str) -> RequestTrace | None:
    """The one row for a workflow — ``workflow_id`` is unique since PRJ-04."""
    result = await session.execute(
        select(RequestTrace).where(RequestTrace.workflow_id == workflow_id)
    )
    return result.scalar_one_or_none()


def log_request_summary(trace: dict[str, Any], *, writer: str) -> None:
    """One line per terminal, so "why did this take 90 s" starts from a log search."""
    logger.info(
        "request_summary wf=%s status=%s route=%s complexity=%s failure_kind=%s "
        "duration_ms=%s llm_calls=%s db_queries=%s writer=%s",
        str(trace.get("workflow_id", ""))[:8],
        trace.get("status"),
        trace.get("route"),
        trace.get("complexity"),
        trace.get("failure_kind"),
        trace.get("total_duration_ms"),
        trace.get("total_llm_calls"),
        trace.get("total_db_queries"),
        writer,
    )


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
    "data_gate": "validation",
    "answer_validate": "validation",
    "answer": "validation",
    "validate": "validation",
    "validate_tables": "validation",
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


_VALID_SPAN_TYPES = frozenset(
    {"llm_call", "db_query", "rag", "tool_call", "sub_agent", "viz", "validation"}
)


def classify_span_type(step_name: str, explicit: str | None = None) -> str:
    """Pick the canonical span type for an event.

    T14: when a producer emits an explicit ``span_type`` we trust it and skip
    the heuristic. The heuristic is kept as a fallback for legacy producers
    and background pipelines that have not yet been migrated.
    """
    if explicit and explicit in _VALID_SPAN_TYPES:
        return explicit
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
        # Strong references to in-flight persist tasks. asyncio only keeps a
        # weak reference to a bare create_task(), so without this the trace
        # write can be garbage-collected mid-flight and silently lost.
        self._persist_tasks: set[asyncio.Task[None]] = set()
        # The same tasks by workflow, so ``finalize_trace`` can wait for its own
        # workflow's flush instead of racing it into a second row.
        self._persist_by_wf: dict[str, asyncio.Task[None]] = {}

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
        # Let any in-flight trace writes finish so they aren't dropped on shutdown.
        if self._persist_tasks:
            await asyncio.gather(*self._persist_tasks, return_exceptions=True)
        logger.info("TracePersistenceService stopped")

    async def _on_event(self, event: WorkflowEvent) -> None:
        """Called by WorkflowTracker on every broadcast.

        OPS-14: `_deliver_local` runs **every** hook, including on the Redis
        rebroadcast path — so a worker's `pipeline_start` reaches this method in the
        web process too. `RunCoordinator._on_event` guards against exactly that, and
        this one did not: the web process created a `_WorkflowBuffer` for a workflow it
        is not running, and only a matching `pipeline_end` **on the same process** ever
        frees one. The worker's `pipeline_end` arrives here as a rebroadcast as well, so
        under the old code the buffer was created by one branch and removed by another;
        any run whose end was lost — a dropped Redis message, a worker SIGKILL — left
        its spans in the web dyno's heap for the life of the process.
        """
        # The process that EXECUTES the pipeline persists its trace. A receiver only
        # relays SSE, and has nothing of its own to record. Read from the tracker this
        # service is attached to rather than the module singleton — they are the same
        # object in production, and only one of them is the truth in a test.
        if self._tracker._external_rebroadcast:
            return
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
                self._schedule_persist(buf, event)

        except Exception:
            logger.warning(
                "TracePersistence: failed to process event for wf=%s",
                event.workflow_id[:8],
                exc_info=True,
            )

    def _schedule_persist(self, buf: _WorkflowBuffer, event: WorkflowEvent) -> None:
        task = asyncio.create_task(self._persist_workflow(buf, event))
        self._persist_tasks.add(task)
        self._persist_by_wf[buf.workflow_id] = task

        def _done(t: asyncio.Task[None], wf: str = buf.workflow_id) -> None:
            self._persist_tasks.discard(t)
            if self._persist_by_wf.get(wf) is t:
                self._persist_by_wf.pop(wf, None)

        task.add_done_callback(_done)

    async def _await_flush(self, workflow_id: str) -> None:
        """Let this workflow's buffer flush land first, bounded and never raising."""
        task = self._persist_by_wf.get(workflow_id)
        if task is None or task.done():
            return
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=_FLUSH_WAIT_SECONDS)
        except TimeoutError:
            # The flush itself never raises (`_persist_workflow` logs and returns), so
            # the only way out of this wait other than success is the bound.
            logger.warning(
                "TracePersistence: flush for wf=%s did not finish in %.0fs; finalizing anyway",
                workflow_id[:8],
                _FLUSH_WAIT_SECONDS,
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
        meta: TraceMeta,
        total_duration_ms: float | None = None,
        total_tokens: int = 0,
        llm_provider: str = "unknown",
        llm_model: str = "unknown",
        steps_used: int = 0,
        steps_total: int = 0,
        tool_call_log: list[dict] | None = None,
    ) -> None:
        """Attach chat-route metadata to the trace and persist if buffer was already flushed.

        Called from chat.py after the assistant message is saved.

        ``meta`` has **no default**, and that is the whole point of Ш0. The four
        values it carries used to be loose keyword arguments with defaults, and
        production measured **zero of twelve call sites** supplying any of them —
        222 traces out of 222 read ``route = "unknown"`` while ``CLAUDE.md``
        claimed routing metrics were always populated. A parameter with a default
        is a parameter every caller can forget, and every caller did.
        """
        route = meta.route
        complexity = meta.complexity
        estimated_queries = meta.estimated_queries
        failure_kind = meta.failure_kind
        estimated_cost_usd = meta.cost_usd
        plan_json = meta.plan_json
        await self._await_flush(workflow_id)

        async def _update_existing(session: Any, trace: RequestTrace) -> dict[str, Any]:
            # The buffer flush at ``pipeline_end`` already wrote this row with real
            # numbers (duration, LLM/DB call counts). This UPDATE used to overwrite
            # every column unconditionally, so the *defaults of this function's own
            # parameters* clobbered them: a run that had taken 323 s came out with
            # total_duration_ms=NULL, steps 0/0 and route/complexity "unknown" --
            # exactly the production trace of 2026-08-06 11:39:24. Only write what
            # the caller actually supplied.
            values: dict[str, Any] = {
                "project_id": project_id,
                "user_id": user_id,
                "response_type": response_type,
                "status": status,
            }
            optional: dict[str, Any] = {
                "session_id": session_id,
                "message_id": message_id,
                "assistant_message_id": assistant_message_id,
                # Additive like its neighbours: a clean run's ``None`` must not
                # erase a kind the buffer flush already wrote. It sat in the
                # unconditional dict above, which is the same shape that erased
                # 323 s of duration once.
                "failure_kind": failure_kind,
                "plan_json": plan_json,
                "error_message": _truncate(error_message),
                "total_duration_ms": total_duration_ms,
                "estimated_cost_usd": estimated_cost_usd,
            }
            values.update({k: v for k, v in optional.items() if v is not None})
            if status == "completed":
                # ...except where the earlier writer's statement is now false. A run
                # the chat path completed has no failure, and a ``Stale: …`` note
                # written by a provisional eviction describes a death that did not
                # happen. Production carried one such row.
                values["failure_kind"] = None
                if (trace.error_message or "").startswith("Stale:") and not error_message:
                    values["error_message"] = None
            if question:
                values["question"] = _truncate(question, 500)
            if total_tokens:
                values["total_tokens"] = total_tokens
            if steps_used or steps_total:
                values["steps_used"] = steps_used
                values["steps_total"] = steps_total
            if estimated_queries:
                values["estimated_queries"] = estimated_queries
            for name, supplied in (
                ("llm_provider", llm_provider),
                ("llm_model", llm_model),
                ("route", route),
                ("complexity", complexity),
            ):
                if supplied and supplied != "unknown":
                    values[name] = supplied

            upd = update(RequestTrace).where(RequestTrace.id == trace.id).values(**values)
            await session.execute(upd)
            await session.commit()
            return values

        try:
            async with async_session_factory() as session:
                trace = await _find_trace(session, workflow_id)
                if trace is not None:
                    values = await _update_existing(session, trace)
                    log_request_summary(
                        {
                            "workflow_id": workflow_id,
                            "route": trace.route,
                            "complexity": trace.complexity,
                            "failure_kind": trace.failure_kind,
                            "total_duration_ms": trace.total_duration_ms,
                            "total_llm_calls": trace.total_llm_calls,
                            "total_db_queries": trace.total_db_queries,
                            **values,
                        },
                        writer="finalize",
                    )
                    return

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
                    failure_kind=failure_kind,
                    total_duration_ms=total_duration_ms,
                    total_llm_calls=llm_count,
                    total_db_queries=db_count,
                    total_tokens=total_tokens,
                    estimated_cost_usd=estimated_cost_usd,
                    llm_provider=llm_provider,
                    llm_model=llm_model,
                    steps_used=steps_used,
                    steps_total=steps_total,
                    route=route,
                    complexity=complexity,
                    estimated_queries=estimated_queries,
                    plan_json=plan_json,
                )
                session.add(trace)
                try:
                    await session.flush()
                except IntegrityError:
                    # The other writer inserted between our read and our write. The
                    # unique index on ``workflow_id`` is what makes this visible; the
                    # row it protects is updated rather than duplicated.
                    await session.rollback()
                    existing = await _find_trace(session, workflow_id)
                    if existing is None:
                        raise
                    await _update_existing(session, existing)
                    return

                for i, sd in enumerate(spans):
                    session.add(
                        TraceSpan(
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
                    )
                await session.commit()
                log_request_summary(
                    {
                        "workflow_id": workflow_id,
                        "status": status,
                        "route": route,
                        "complexity": complexity,
                        "failure_kind": failure_kind,
                        "total_duration_ms": total_duration_ms,
                        "total_llm_calls": llm_count,
                        "total_db_queries": db_count,
                    },
                    writer="finalize",
                )

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

                span_type = classify_span_type(evt.step, getattr(evt, "span_type", None))

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
            trace_status = _END_STATUS_TO_TRACE_STATUS.get(end_status, "failed")
            routing = routing_from_events(events)
            route, complexity, estimated_queries = routing or ("unknown", "unknown", 0)
            failure_kind = (
                kind_for_terminal_detail(end_event.detail) if trace_status == "failed" else None
            )
            error_message = (
                _truncate(end_event.detail)
                if trace_status in ("failed", PROVISIONAL_STATUS)
                else None
            )

            context = buf.context
            project_id = context.get("project_id") or ""
            user_id = context.get("user_id") or ""

            if not project_id or not user_id:
                # Userless/sync workflows legitimately have no user_id; they
                # call finalize_trace() later with the real context. This is
                # expected and benign — use debug, not warning.
                logger.debug(
                    "TracePersistence: skipping initial persist for wf=%s — "
                    "empty project_id=%r / user_id=%r (finalize_trace will create it)",
                    buf.workflow_id[:8],
                    project_id,
                    user_id,
                )
                return

            summary = {
                "workflow_id": buf.workflow_id,
                "status": trace_status,
                "route": route,
                "complexity": complexity,
                "failure_kind": failure_kind,
                "total_duration_ms": round(total_duration_ms, 1),
                "total_llm_calls": llm_count,
                "total_db_queries": db_count,
            }

            async with async_session_factory() as session:
                existing = await _find_trace(session, buf.workflow_id)
                trace: RequestTrace | None = None
                if existing is None:
                    trace = RequestTrace(
                        project_id=project_id,
                        user_id=user_id,
                        workflow_id=buf.workflow_id,
                        question=_truncate(context.get("question", ""), 500) or "",
                        status=trace_status,
                        error_message=error_message,
                        failure_kind=failure_kind,
                        total_duration_ms=round(total_duration_ms, 1),
                        total_llm_calls=llm_count,
                        total_db_queries=db_count,
                        llm_provider="unknown",
                        llm_model="unknown",
                        route=route,
                        complexity=complexity,
                        estimated_queries=estimated_queries,
                    )
                    session.add(trace)
                    try:
                        await session.flush()
                    except IntegrityError:
                        await session.rollback()
                        existing = await _find_trace(session, buf.workflow_id)
                        if existing is None:
                            raise
                        trace = None

                if existing is not None:
                    # ``finalize_trace`` got here first. Its status and message are
                    # the caller's statement and stand; what only the buffer
                    # measured is filled in where the row lacks it.
                    await self._merge_measurements(
                        session,
                        existing,
                        duration_ms=round(total_duration_ms, 1),
                        llm_count=llm_count,
                        db_count=db_count,
                        routing=routing,
                        failure_kind=failure_kind,
                        span_dicts=span_dicts,
                    )
                    await session.commit()
                    log_request_summary(summary, writer="flush-merge")
                    return

                assert trace is not None
                for sd in span_dicts:
                    session.add(self._span_row(trace.id, sd))

                await session.commit()
                if trace_status == "failed":
                    try:
                        from app.services.error_log_service import ErrorLogService

                        await ErrorLogService().upsert_from_trace(session, trace)
                    except Exception:
                        logger.debug("error_log upsert from trace failed", exc_info=True)
                log_request_summary(summary, writer="flush")

        except Exception:
            logger.warning(
                "TracePersistence: failed to persist workflow wf=%s",
                buf.workflow_id[:8],
                exc_info=True,
            )

    @staticmethod
    def _span_row(trace_id: str, sd: dict[str, Any]) -> TraceSpan:
        return TraceSpan(
            trace_id=trace_id,
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

    async def _merge_measurements(
        self,
        session: Any,
        trace: RequestTrace,
        *,
        duration_ms: float,
        llm_count: int,
        db_count: int,
        routing: tuple[str, str, int] | None,
        failure_kind: str | None,
        span_dicts: list[dict[str, Any]],
    ) -> None:
        values: dict[str, Any] = {}
        if trace.total_duration_ms is None:
            values["total_duration_ms"] = duration_ms
        if span_dicts:
            # The buffer's spans are the measured ones; a fallback row built from
            # the tool log is replaced by them rather than doubled.
            from sqlalchemy import delete

            await session.execute(delete(TraceSpan).where(TraceSpan.trace_id == trace.id))
            for sd in span_dicts:
                session.add(self._span_row(trace.id, sd))
            values["total_llm_calls"] = llm_count
            values["total_db_queries"] = db_count
        if routing is not None and (trace.route or "unknown") == "unknown":
            values["route"], values["complexity"], values["estimated_queries"] = routing
        if failure_kind and trace.failure_kind is None and trace.status == "failed":
            values["failure_kind"] = failure_kind
        if values:
            await session.execute(
                update(RequestTrace).where(RequestTrace.id == trace.id).values(**values)
            )

    async def _cleanup_stale_buffers(self) -> None:
        """Periodically persist stale buffers that never received pipeline_end."""
        while True:
            await asyncio.sleep(60)
            try:
                now = time.time()
                horizon = stale_buffer_seconds()
                stale_bufs: list[_WorkflowBuffer] = []
                async with self._lock:
                    stale_ids = [
                        wf_id
                        for wf_id, buf in self._buffers.items()
                        if now - buf.started_at > horizon
                    ]
                    for wf_id in stale_ids:
                        buf = self._buffers.pop(wf_id, None)
                        if buf is not None:
                            stale_bufs.append(buf)
                for buf in stale_bufs:
                    synthetic_end = WorkflowEvent(
                        workflow_id=buf.workflow_id,
                        step="pipeline_end",
                        status=PROVISIONAL_STATUS,
                        detail=STALE_DETAIL,
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
                        "TracePersistence: persisted %d stale buffer(s) as provisional traces",
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
