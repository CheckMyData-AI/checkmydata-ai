"""Conversational chat transports: HTTP /ask, SSE /ask/stream, WebSocket.

T-ARCH-1 decomposition: session CRUD lives in :mod:`chat_sessions`, feedback
and learning-credit logic in :mod:`chat_feedback`, and utility endpoints
(estimate / search / suggestions / explain-sql / summarize) in
:mod:`chat_utility`. All three are mounted under the same ``/api/chat``
prefix in ``app.main``.
"""

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Any, Literal

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db

# Re-exported for the transports below (and for backward compatibility with
# callers/tests that historically imported these from this module).
from app.api.routes.chat_feedback import (
    credit_validated_learnings,
    maybe_auto_investigate,
)
from app.core.agent import ConversationalAgent
from app.core.agent_limiter import agent_limiter
from app.core.context_budget import CHARS_PER_TOKEN
from app.core.rate_limit import limiter
from app.core.workflow_tracker import WorkflowEvent, tracker
from app.core.ws_tickets import ws_ticket_store
from app.services.chat_service import ChatService, SessionBusyError, session_processing_lock
from app.services.connection_service import ConnectionService
from app.services.membership_service import MembershipService
from app.services.project_service import ProjectService
from app.services.rag_feedback_service import RAGFeedbackService

if TYPE_CHECKING:
    from app.connectors.base import ConnectionConfig
from app.services.session_summarizer import SessionSummary, get_session_title, summarize_session
from app.services.usage_service import UsageService
from app.viz.renderer import render

logger = logging.getLogger(__name__)

router = APIRouter()
_chat_svc = ChatService()
_conn_svc = ConnectionService()
_project_svc = ProjectService()
_agent = ConversationalAgent()
_rag_feedback_svc = RAGFeedbackService()
_usage_svc = UsageService()
_membership_svc = MembershipService()

# Strong references to fire-and-forget background finalizer tasks. asyncio keeps
# only a weak reference to a bare create_task(), so without this the finalizer
# that persists agent results after a client disconnect can be garbage-collected
# mid-flight — losing the very results it was scheduled to save.
_background_finalize_tasks: set[asyncio.Task] = set()


async def _check_token_budget(db: AsyncSession, user_id: str) -> str | None:
    """F-FIN-1: enforce per-user token budgets before running the agent.

    Thin delegate to the shared helper so the MCP surface enforces the same
    gate. Returns an error message when exhausted, ``None`` to proceed.
    """
    return await _usage_svc.check_token_budget(db, user_id)


async def _safe_to_config(db: AsyncSession, conn_model) -> "ConnectionConfig":
    """Wrap to_config with a user-friendly error on decryption failure."""
    try:
        return await _conn_svc.to_config(db, conn_model)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cannot decrypt credentials for connection '{conn_model.name}'. "
                "Please re-enter the password in Settings → Connections."
            ),
        ) from exc


def _estimate_cost(model: str | None, prompt_tokens: int, completion_tokens: int) -> float | None:
    """Thin wrapper — see :mod:`cost_estimation_service`."""
    from app.services.cost_estimation_service import estimate_cost

    return estimate_cost(model, prompt_tokens, completion_tokens)


class ChatRequest(BaseModel):
    session_id: str | None = None
    project_id: str
    connection_id: str | None = None
    message: str = Field(max_length=20000)
    preferred_provider: str | None = None
    model: str | None = None
    max_steps: int | None = Field(None, ge=1, le=100)
    pipeline_action: Literal["continue", "modify", "retry", "continue_analysis"] | None = None
    pipeline_run_id: str | None = None
    modification: str | None = Field(None, max_length=5000)
    continuation_context: str | None = None


class WsChatMessage(BaseModel):
    """Validated WebSocket chat message."""

    message: str = Field(min_length=1, max_length=20000)
    preferred_provider: str | None = Field(None, max_length=50)
    model: str | None = Field(None, max_length=100)
    # L5: pipeline-control fields, parity with the HTTP/SSE ChatRequest — without
    # these the checkpoint "Continue / Modify / Retry" actions cannot be driven
    # over the WebSocket transport.
    pipeline_action: Literal["continue", "modify", "retry", "continue_analysis"] | None = None
    pipeline_run_id: str | None = Field(None, max_length=100)
    modification: str | None = Field(None, max_length=20000)
    continuation_context: str | None = Field(None, max_length=20000)


def _ws_pipeline_extra(session_id: str, ws_msg: "WsChatMessage") -> dict[str, Any]:
    """Build the agent ``extra`` for a WS message: session_id + pipeline control.

    Mirrors the HTTP/SSE paths so checkpoint Continue / Modify / Retry actions
    are driveable over the WebSocket transport (L5).
    """
    extra: dict[str, Any] = {"session_id": session_id}
    if ws_msg.pipeline_action:
        extra["pipeline_action"] = ws_msg.pipeline_action
        if ws_msg.pipeline_run_id:
            extra["pipeline_run_id"] = ws_msg.pipeline_run_id
        if ws_msg.modification:
            extra["modification"] = ws_msg.modification
        if ws_msg.continuation_context:
            extra["continuation_context"] = ws_msg.continuation_context
    return extra


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    query: str | None = None
    query_explanation: str | None = None
    visualization: dict | None = None
    # Raw agent viz config (chart spec + pipeline metadata). Carries
    # ``pipeline_run_id`` / ``stage_id`` for stage_checkpoint / stage_failed
    # responses so the frontend can resume the paused pipeline (the checkpoint
    # "Continue / Modify / Retry" buttons no-op without it).
    viz_config: dict | None = None
    raw_result: dict | None = None
    error: str | None = None
    workflow_id: str | None = None
    staleness_warning: str | None = None
    response_type: str = "text"
    assistant_message_id: str | None = None
    user_message_id: str | None = None
    rules_changed: bool = False
    steps_used: int = 0
    steps_total: int = 0
    continuation_context: str | None = None
    clarification_data: dict | None = None
    sql_results: list[dict] | None = None


def _raw_result_row_cap() -> int:
    """Configurable row cap for raw-result payloads (T25)."""
    from app.config import settings as _settings

    return _settings.chat_raw_result_row_cap


def _has_rules_changed(tool_call_log: list[dict] | None) -> bool:
    """Thin wrapper — see :mod:`chat_response_builder`."""
    from app.services.chat_response_builder import has_rules_changed

    return has_rules_changed(tool_call_log)


def _build_structured_error(exc: Exception) -> dict:
    """Thin wrapper — see :mod:`chat_response_builder`."""
    from app.services.chat_response_builder import build_structured_error

    return build_structured_error(exc)


def _build_raw_result(results) -> dict | None:
    """Thin wrapper — see :mod:`chat_response_builder`."""
    from app.services.chat_response_builder import build_raw_result

    return build_raw_result(results, row_cap=_raw_result_row_cap())


def _build_sql_results_payload(sql_result_blocks: list, answer: str = "") -> list[dict] | None:
    """Thin wrapper — see :mod:`chat_response_builder`."""
    from app.services.chat_response_builder import build_sql_results_payload

    return build_sql_results_payload(
        sql_result_blocks, row_cap=_raw_result_row_cap(), answer=answer
    )


@router.post("/ask", response_model=ChatResponse)
@limiter.limit("20/minute")
async def ask(
    request: Request,
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, body.project_id, user["user_id"], "viewer")

    # F-FIN-1: block before any LLM work when the user's token budget is spent.
    budget_error = await _check_token_budget(db, user["user_id"])
    if budget_error:
        raise HTTPException(status_code=429, detail=budget_error)

    config = None
    if body.connection_id:
        conn_model = await _conn_svc.get(db, body.connection_id)
        if not conn_model:
            raise HTTPException(status_code=404, detail="Connection not found")
        config = await _safe_to_config(db, conn_model)
        config.connection_id = body.connection_id

    session_id = body.session_id
    if session_id:
        validated = await _chat_svc.validate_session_access(
            db, session_id, body.project_id, user["user_id"]
        )
        if not validated:
            raise HTTPException(
                status_code=403,
                detail="Session does not belong to this user/project",
            )
    else:
        chat_session = await _chat_svc.create_session(
            db,
            body.project_id,
            user_id=user["user_id"],
            connection_id=body.connection_id,
        )
        session_id = chat_session.id

    _session_lock_cm = session_processing_lock(session_id)
    try:
        await _session_lock_cm.__aenter__()
    except SessionBusyError as exc:
        raise HTTPException(
            status_code=409,
            detail="This chat session is currently processing another request. "
            "Please wait for it to complete.",
        ) from exc

    # Acquire a per-user concurrency/hourly slot before any agent work, exactly
    # like /ask/stream and the WS path — otherwise /ask bypasses
    # ``max_concurrent_agent_calls`` / ``max_agent_calls_per_hour`` and a user
    # can run unbounded concurrent agent pipelines. Released in the finally
    # below. A denied acquire reserves nothing, so it must not be released.
    _limiter_acquired = False
    try:
        limit_err = await agent_limiter.acquire(user["user_id"])
        if limit_err:
            raise HTTPException(status_code=429, detail=limit_err)
        _limiter_acquired = True

        user_msg = await _chat_svc.add_message(db, session_id, "user", body.message)
        history = await _chat_svc.get_history_as_messages(db, session_id)
        logger.info(
            "Chat request: project=%s session=%s conn=%s",
            body.project_id[:8],
            session_id[:8],
            (body.connection_id or "none")[:8],
        )

        project = await _project_svc.get(db, body.project_id)
        agent_provider = body.preferred_provider or (
            project.agent_llm_provider if project else None
        )
        agent_model = body.model or (project.agent_llm_model if project else None)
        sql_provider = (project.sql_llm_provider if project else None) or agent_provider
        sql_model = (project.sql_llm_model if project else None) or agent_model
        max_steps = body.max_steps or (
            getattr(project, "max_orchestrator_steps", None) if project else None
        )

        extra: dict = {"session_id": session_id}
        if body.pipeline_action:
            extra["pipeline_action"] = body.pipeline_action
        if body.pipeline_run_id:
            extra["pipeline_run_id"] = body.pipeline_run_id
        if body.modification:
            extra["modification"] = body.modification
        if body.continuation_context:
            extra["continuation_context"] = body.continuation_context

        from app.config import settings as app_settings

        try:
            # Bound the inline agent run with the same wall-clock budget the
            # stream path applies, so a stuck pipeline cannot hold the request
            # (and its concurrency slot) open indefinitely.
            result = await asyncio.wait_for(
                _agent.run(
                    question=body.message,
                    project_id=body.project_id,
                    connection_config=config,
                    chat_history=history[:-1],
                    preferred_provider=agent_provider,
                    model=agent_model,
                    sql_provider=sql_provider,
                    sql_model=sql_model,
                    project_name=project.name if project else None,
                    user_id=user["user_id"],
                    extra=extra,
                    max_steps=max_steps,
                ),
                timeout=app_settings.stream_timeout_seconds,
            )
        except TimeoutError as timeout_exc:
            logger.warning(
                "Agent run timed out after %ss (session=%s)",
                app_settings.stream_timeout_seconds,
                session_id[:8],
            )
            try:
                trace_svc = getattr(request.app.state, "trace_persistence_service", None)
                if trace_svc is not None:
                    await trace_svc.finalize_trace(
                        f"unknown-{session_id}",
                        project_id=body.project_id,
                        user_id=user["user_id"],
                        session_id=session_id,
                        message_id=user_msg.id,
                        question=body.message,
                        response_type="error",
                        status="failed",
                        error_message="Agent run timed out",
                    )
            except Exception:
                logger.warning("Failed to finalize trace after agent timeout", exc_info=True)
            raise HTTPException(
                status_code=504,
                detail="The request took too long to process. Please try again.",
            ) from timeout_exc
        except Exception as agent_exc:
            logger.exception("Agent run raised an exception")
            _exc_msg = str(agent_exc)[:500]
            try:
                trace_svc = getattr(request.app.state, "trace_persistence_service", None)
                if trace_svc is not None:
                    await trace_svc.finalize_trace(
                        f"unknown-{session_id}",
                        project_id=body.project_id,
                        user_id=user["user_id"],
                        session_id=session_id,
                        message_id=user_msg.id,
                        question=body.message,
                        response_type="error",
                        status="failed",
                        error_message=_exc_msg,
                    )
            except Exception:
                logger.warning("Failed to finalize trace after agent crash", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail="An internal error occurred while processing your request.",
            ) from agent_exc

        viz_data = None
        if result.results and not result.error:
            viz_data = render(
                result=result.results,
                viz_type=result.viz_type,
                config=result.viz_config,
                summary=result.answer,
            )

        raw_result = _build_raw_result(result.results)

        rag_source_dicts = [
            {
                "source_path": s.source_path,
                "distance": s.distance,
                "doc_type": s.doc_type,
            }
            for s in result.knowledge_sources
        ]

        tool_calls_str = (
            json.dumps(result.tool_call_log, default=str) if result.tool_call_log else None
        )

        ask_usage = result.token_usage or {}
        ask_cost = _estimate_cost(
            result.llm_model,
            ask_usage.get("prompt_tokens", 0),
            ask_usage.get("completion_tokens", 0),
        )
        enriched_token_usage = (
            {
                **(result.token_usage or {}),
                "provider": result.llm_provider or "unknown",
                "model": result.llm_model or "unknown",
                "estimated_cost_usd": ask_cost,
                "prompt_version": result.prompt_version,
            }
            if result.token_usage
            else None
        )

        http_sql_results_payload = _build_sql_results_payload(result.sql_results, result.answer)

        assistant_msg = await _chat_svc.add_message(
            db,
            session_id,
            "assistant",
            result.answer,
            metadata={
                "query": result.query,
                "query_explanation": result.query_explanation,
                "question": body.message,
                "viz_type": result.viz_type,
                "visualization": viz_data,
                "raw_result": raw_result,
                "error": result.error,
                "workflow_id": result.workflow_id,
                "row_count": (result.results.row_count if result.results else None),
                "execution_time_ms": (result.results.execution_time_ms if result.results else None),
                "rag_sources": rag_source_dicts,
                "token_usage": enriched_token_usage,
                "response_type": result.response_type,
                "staleness_warning": result.staleness_warning,
                "insights": result.insights or [],
                "suggested_followups": result.suggested_followups or [],
                "clarification_data": result.clarification_data,
                "sql_results": http_sql_results_payload,
                "continuation_context": result.continuation_context,
                "exposed_learning_ids": result.exposed_learning_ids,
            },
            tool_calls_json=tool_calls_str,
        )

        # R4-2: credit exposed learnings now that the result validated successfully.
        await credit_validated_learnings(result, body.connection_id, message_id=assistant_msg.id)

        # R5-7: auto-route a suspicious result to the investigation agent.
        await maybe_auto_investigate(
            result,
            project_id=body.project_id,
            connection_id=body.connection_id,
            session_id=session_id,
            message_id=assistant_msg.id,
        )

        if rag_source_dicts:
            try:
                await _rag_feedback_svc.record(
                    session=db,
                    project_id=body.project_id,
                    rag_sources=rag_source_dicts,
                    query_succeeded=not result.error,
                    question_snippet=body.message[:200],
                )
            except Exception:
                logger.warning("Failed to record RAG feedback", exc_info=True)

        usage = result.token_usage or {}
        logger.info(
            "Chat response: type=%s tokens=%d error=%s",
            result.response_type,
            usage.get("total_tokens", 0)
            or (usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)),
            bool(result.error),
        )

        try:
            await _usage_svc.record_usage(
                db,
                user_id=user["user_id"],
                project_id=body.project_id,
                session_id=session_id,
                message_id=assistant_msg.id,
                provider=result.llm_provider or "unknown",
                model=result.llm_model or "unknown",
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
                estimated_cost_usd=_estimate_cost(
                    result.llm_model,
                    usage.get("prompt_tokens", 0),
                    usage.get("completion_tokens", 0),
                ),
            )
        except Exception:
            logger.warning("Failed to record token usage", exc_info=True)

        if result.workflow_id:
            try:
                trace_svc = getattr(request.app.state, "trace_persistence_service", None)
                if trace_svc is not None:
                    await trace_svc.finalize_trace(
                        result.workflow_id,
                        project_id=body.project_id,
                        user_id=user["user_id"],
                        session_id=session_id,
                        message_id=user_msg.id,
                        assistant_message_id=assistant_msg.id,
                        question=body.message,
                        response_type=result.response_type or "text",
                        status="failed" if result.error else "completed",
                        error_message=result.error,
                        total_duration_ms=(
                            result.results.execution_time_ms if result.results else None
                        ),
                        total_tokens=usage.get("total_tokens", 0)
                        or (usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)),
                        estimated_cost_usd=_estimate_cost(
                            result.llm_model,
                            usage.get("prompt_tokens", 0),
                            usage.get("completion_tokens", 0),
                        ),
                        llm_provider=result.llm_provider or "unknown",
                        llm_model=result.llm_model or "unknown",
                        steps_used=result.steps_used,
                        steps_total=result.steps_total,
                        tool_call_log=result.tool_call_log,
                    )
            except Exception:
                logger.warning("Failed to finalize request trace", exc_info=True)

        response = ChatResponse(
            session_id=session_id,
            answer=result.answer,
            query=result.query or None,
            query_explanation=result.query_explanation or None,
            visualization=viz_data,
            viz_config=result.viz_config or None,
            raw_result=raw_result,
            error=result.error,
            workflow_id=result.workflow_id,
            staleness_warning=result.staleness_warning,
            response_type=result.response_type,
            assistant_message_id=assistant_msg.id,
            user_message_id=user_msg.id,
            rules_changed=_has_rules_changed(result.tool_call_log),
            steps_used=result.steps_used,
            steps_total=result.steps_total,
            continuation_context=result.continuation_context,
            clarification_data=result.clarification_data,
            sql_results=http_sql_results_payload,
        )
        return response
    finally:
        if _limiter_acquired:
            try:
                await agent_limiter.release(user["user_id"])
            except Exception:
                logger.debug("Agent limiter release failed", exc_info=True)
        try:
            await _session_lock_cm.__aexit__(None, None, None)
        except Exception:
            logger.debug("Session lock release failed", exc_info=True)


@router.post("/ask/stream")
@limiter.limit("20/minute")
async def ask_stream(
    request: Request,
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """SSE streaming endpoint that sends workflow progress + final answer."""
    await _membership_svc.require_role(db, body.project_id, user["user_id"], "viewer")

    # F-FIN-1: block before any LLM work when the user's token budget is spent.
    budget_error = await _check_token_budget(db, user["user_id"])
    if budget_error:
        raise HTTPException(status_code=429, detail=budget_error)

    config = None
    if body.connection_id:
        conn_model = await _conn_svc.get(db, body.connection_id)
        if not conn_model:
            raise HTTPException(status_code=404, detail="Connection not found")
        config = await _safe_to_config(db, conn_model)
        config.connection_id = body.connection_id

    session_id = body.session_id
    if session_id:
        validated = await _chat_svc.validate_session_access(
            db, session_id, body.project_id, user["user_id"]
        )
        if not validated:
            raise HTTPException(
                status_code=403,
                detail="Session does not belong to this user/project",
            )
    else:
        chat_session = await _chat_svc.create_session(
            db,
            body.project_id,
            user_id=user["user_id"],
            connection_id=body.connection_id,
        )
        session_id = chat_session.id

    _stream_lock_cm = session_processing_lock(session_id)
    try:
        await _stream_lock_cm.__aenter__()
    except SessionBusyError as exc:
        raise HTTPException(
            status_code=409,
            detail="This chat session is currently processing another request. "
            "Please wait for it to complete.",
        ) from exc

    try:
        user_msg = await _chat_svc.add_message(db, session_id, "user", body.message)
        user_message_id = user_msg.id
        history = await _chat_svc.get_history_as_messages(db, session_id)
    except Exception:
        # Release the per-session lock acquired above if the initial message
        # persistence fails before the streaming generator (whose finally owns
        # the release) is created — otherwise the session is wedged "busy".
        try:
            await _stream_lock_cm.__aexit__(None, None, None)
        except Exception:
            logger.debug("Session lock release failed", exc_info=True)
        raise

    logger.info(
        "Chat stream request: project=%s session=%s conn=%s",
        body.project_id[:8],
        session_id[:8],
        (body.connection_id or "none")[:8],
    )

    project = await _project_svc.get(db, body.project_id)
    agent_provider = body.preferred_provider or (project.agent_llm_provider if project else None)
    agent_model = body.model or (project.agent_llm_model if project else None)
    sql_provider = (project.sql_llm_provider if project else None) or agent_provider
    sql_model = (project.sql_llm_model if project else None) or agent_model
    project_name = project.name if project else None
    stream_max_steps = body.max_steps or (
        getattr(project, "max_orchestrator_steps", None) if project else None
    )

    from app.config import settings as app_settings

    # --- Session rotation: detect context exhaustion before running agent ---
    rotated_from: str | None = None
    rotation_summary: SessionSummary | None = None
    if (
        app_settings.session_rotation_enabled
        and body.session_id  # only rotate existing sessions
        and len(history) >= 4
    ):
        history_chars = sum(len(m.content) for m in history)
        history_tokens_est = history_chars // CHARS_PER_TOKEN
        threshold = int(
            app_settings.max_context_tokens * app_settings.session_rotation_threshold_pct / 100
        )
        if history_tokens_est >= threshold:
            logger.info(
                "Session rotation triggered: session=%s tokens_est=%d threshold=%d",
                session_id[:8],
                history_tokens_est,
                threshold,
            )
            try:
                from app.llm.router import LLMRouter

                _rotation_llm = LLMRouter()
                rotation_summary = await summarize_session(
                    db,
                    session_id,
                    _rotation_llm,
                    preferred_provider=agent_provider,
                    model=agent_model,
                )
                old_title = await get_session_title(db, session_id)
                rotated_from = session_id

                new_chat_session = await _chat_svc.create_session(
                    db,
                    body.project_id,
                    title=f"Continued: {old_title}",
                    user_id=user["user_id"],
                    connection_id=body.connection_id,
                )
                session_id = new_chat_session.id

                await _chat_svc.add_message(
                    db,
                    session_id,
                    "system",
                    f"[Previous conversation summary"
                    f" ({rotation_summary.message_count} messages)]"
                    f"\n{rotation_summary.text}",
                )
                user_msg = await _chat_svc.add_message(db, session_id, "user", body.message)
                user_message_id = user_msg.id
                history = await _chat_svc.get_history_as_messages(db, session_id)

                logger.info(
                    "Session rotated: old=%s new=%s summary_len=%d",
                    rotated_from[:8],
                    session_id[:8],
                    len(rotation_summary.text),
                )
            except Exception:
                logger.warning(
                    "Session rotation failed, continuing with original session",
                    exc_info=True,
                )
                rotated_from = None
                rotation_summary = None

    limit_err = await agent_limiter.acquire(user["user_id"])
    if limit_err:
        raise HTTPException(status_code=429, detail=limit_err)

    stream_timeout_seconds = app_settings.stream_timeout_seconds

    from app.models.base import async_session_factory as _stream_session_factory

    # Mark the session as processing so the frontend can detect in-progress runs
    async with _stream_session_factory() as _status_db:
        await _chat_svc.update_session_status(_status_db, session_id, "processing")

    async def _background_finalize(
        bg_task: asyncio.Task,
        bg_session_id: str,
        bg_body: ChatRequest,
        bg_user_message_id: str,
        bg_user_id: str,
        bg_request_app,
    ) -> None:
        """Await the agent task and persist results even after SSE disconnect."""
        bg_timeout = stream_timeout_seconds + 30
        try:
            try:
                await asyncio.wait_for(asyncio.shield(bg_task), timeout=bg_timeout)
            except TimeoutError:
                logger.warning("Background finalize timed out for session %s", bg_session_id[:8])
                bg_task.cancel()
                try:
                    await bg_task
                except (asyncio.CancelledError, Exception):
                    pass
                return
            except (asyncio.CancelledError, Exception):
                logger.debug(
                    "Background task error for session %s",
                    bg_session_id[:8],
                    exc_info=True,
                )
                return

            if not bg_task.done() or bg_task.cancelled():
                return
            try:
                bg_result = bg_task.result()
            except Exception:
                logger.debug(
                    "Background task raised for session %s",
                    bg_session_id[:8],
                    exc_info=True,
                )
                return
            if bg_result is None:
                return

            bg_viz_data = None
            if bg_result.results and not bg_result.error:
                bg_viz_data = render(
                    result=bg_result.results,
                    viz_type=bg_result.viz_type,
                    config=bg_result.viz_config,
                    summary=bg_result.answer,
                )

            bg_raw_result = _build_raw_result(bg_result.results)
            bg_rag = [
                {"source_path": s.source_path, "distance": s.distance, "doc_type": s.doc_type}
                for s in bg_result.knowledge_sources
            ]
            bg_tool_calls_str = (
                json.dumps(bg_result.tool_call_log, default=str)
                if bg_result.tool_call_log
                else None
            )
            bg_usage = bg_result.token_usage or {}
            bg_cost = _estimate_cost(
                bg_result.llm_model,
                bg_usage.get("prompt_tokens", 0),
                bg_usage.get("completion_tokens", 0),
            )
            bg_enriched_usage = (
                {
                    **(bg_result.token_usage or {}),
                    "provider": bg_result.llm_provider or "unknown",
                    "model": bg_result.llm_model or "unknown",
                    "estimated_cost_usd": bg_cost,
                    "prompt_version": bg_result.prompt_version,
                }
                if bg_result.token_usage
                else None
            )
            bg_sql_results = _build_sql_results_payload(bg_result.sql_results, bg_result.answer)

            async with _stream_session_factory() as bg_db:
                bg_assistant_msg = await _chat_svc.add_message(
                    bg_db,
                    bg_session_id,
                    "assistant",
                    bg_result.answer,
                    metadata={
                        "query": bg_result.query,
                        "query_explanation": bg_result.query_explanation,
                        "question": bg_body.message,
                        "viz_type": bg_result.viz_type,
                        "visualization": bg_viz_data,
                        "raw_result": bg_raw_result,
                        "error": bg_result.error,
                        "workflow_id": bg_result.workflow_id,
                        "row_count": (bg_result.results.row_count if bg_result.results else None),
                        "execution_time_ms": (
                            bg_result.results.execution_time_ms if bg_result.results else None
                        ),
                        "rag_sources": bg_rag,
                        "token_usage": bg_enriched_usage,
                        "response_type": bg_result.response_type,
                        "staleness_warning": bg_result.staleness_warning,
                        "insights": bg_result.insights or [],
                        "suggested_followups": bg_result.suggested_followups or [],
                        "clarification_data": bg_result.clarification_data,
                        "sql_results": bg_sql_results,
                        "continuation_context": bg_result.continuation_context,
                        "exposed_learning_ids": bg_result.exposed_learning_ids,
                    },
                    tool_calls_json=bg_tool_calls_str,
                )

                # R4-2: credit exposed learnings on a validated background result.
                await credit_validated_learnings(
                    bg_result, bg_body.connection_id, message_id=bg_assistant_msg.id
                )

                # R5-7: auto-route a suspicious background result to investigation.
                await maybe_auto_investigate(
                    bg_result,
                    project_id=bg_body.project_id,
                    connection_id=bg_body.connection_id,
                    session_id=bg_session_id,
                    message_id=bg_assistant_msg.id,
                )

                try:
                    await _usage_svc.record_usage(
                        bg_db,
                        user_id=bg_user_id,
                        project_id=bg_body.project_id,
                        session_id=bg_session_id,
                        message_id=bg_assistant_msg.id,
                        provider=bg_result.llm_provider or "unknown",
                        model=bg_result.llm_model or "unknown",
                        prompt_tokens=bg_usage.get("prompt_tokens", 0),
                        completion_tokens=bg_usage.get("completion_tokens", 0),
                        total_tokens=bg_usage.get("total_tokens", 0),
                        estimated_cost_usd=bg_cost,
                    )
                except Exception:
                    logger.warning("Background finalize: failed to record usage", exc_info=True)

                if bg_result.workflow_id:
                    try:
                        trace_svc = getattr(bg_request_app.state, "trace_persistence_service", None)
                        if trace_svc is not None:
                            await trace_svc.finalize_trace(
                                bg_result.workflow_id,
                                project_id=bg_body.project_id,
                                user_id=bg_user_id,
                                session_id=bg_session_id,
                                message_id=bg_user_message_id,
                                assistant_message_id=bg_assistant_msg.id,
                                question=bg_body.message,
                                response_type=bg_result.response_type or "text",
                                status="failed" if bg_result.error else "completed",
                                error_message=bg_result.error,
                            )
                    except Exception:
                        logger.warning("Background finalize: trace failed", exc_info=True)

            logger.info("Background finalize completed for session %s", bg_session_id[:8])
        except Exception:
            logger.warning(
                "Background finalize failed for session %s",
                bg_session_id[:8],
                exc_info=True,
            )
        finally:
            async with _stream_session_factory() as _fin_db:
                await _chat_svc.update_session_status(_fin_db, bg_session_id, "idle")
            await agent_limiter.release(bg_user_id)
            try:
                await _stream_lock_cm.__aexit__(None, None, None)
            except Exception:
                logger.debug("Stream session lock release failed", exc_info=True)

    async def _generate():
        result_holder: list = []
        # Tenant-scope the subscription: the workflow tracker is a process-wide
        # singleton, so an unfiltered subscribe() would relay EVERY user's
        # in-flight workflow events (question previews, SQL, table names) to this
        # stream and let it latch onto another user's workflow. Pass the caller's
        # identity so the tracker's tenancy filter only delivers their events.
        queue = await tracker.subscribe(
            user_id=user["user_id"],
            accessible_project_ids={body.project_id},
        )
        released = False
        lock_released = False

        # Emit session_rotated event before any other events
        if rotated_from and rotation_summary:
            rotation_event = {
                "old_session_id": rotated_from,
                "new_session_id": session_id,
                "summary_preview": rotation_summary.text[:200],
                "message_count": rotation_summary.message_count,
                "topics": rotation_summary.topics[:5],
            }
            yield f"event: session_rotated\ndata: {json.dumps(rotation_event, default=str)}\n\n"

        stream_extra: dict = {"session_id": session_id}
        if body.pipeline_action:
            stream_extra["pipeline_action"] = body.pipeline_action
        if body.pipeline_run_id:
            stream_extra["pipeline_run_id"] = body.pipeline_run_id
        if body.modification:
            stream_extra["modification"] = body.modification
        if body.continuation_context:
            stream_extra["continuation_context"] = body.continuation_context

        async def _process():
            res = await _agent.run(
                question=body.message,
                project_id=body.project_id,
                connection_config=config,
                chat_history=history[:-1],
                preferred_provider=agent_provider,
                model=agent_model,
                sql_provider=sql_provider,
                sql_model=sql_model,
                project_name=project_name,
                user_id=user["user_id"],
                extra=stream_extra,
                max_steps=stream_max_steps,
            )
            result_holder.append(res)
            return res

        task = asyncio.create_task(_process())

        async def _finalize_on_error(workflow_id: str | None, error_msg: str) -> None:
            effective_wf_id = workflow_id or f"stream-error-{session_id}"
            if not workflow_id:
                logger.warning(
                    "Stream error but wf_id is None; using fallback ID %s",
                    effective_wf_id[:16],
                )
            try:
                trace_svc = getattr(request.app.state, "trace_persistence_service", None)
                if trace_svc is not None:
                    await trace_svc.finalize_trace(
                        effective_wf_id,
                        project_id=body.project_id,
                        user_id=user["user_id"],
                        session_id=session_id,
                        message_id=user_message_id,
                        question=body.message,
                        response_type="error",
                        status="failed",
                        error_message=error_msg[:500],
                    )
            except Exception:
                logger.warning("Failed to finalize trace on error path", exc_info=True)

        try:
            wf_id = None
            safety = app_settings.stream_safety_margin_seconds
            loop_deadline = time.monotonic() + stream_timeout_seconds + safety
            last_heartbeat = time.monotonic()
            while not task.done() or not queue.empty():
                if time.monotonic() > loop_deadline:
                    logger.warning("SSE event loop exceeded safety timeout, breaking")
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.5)
                except TimeoutError:
                    now = time.monotonic()
                    if now - last_heartbeat >= 20:
                        yield ": heartbeat\n\n"
                        last_heartbeat = now
                    continue
                if wf_id is None and event.step == "pipeline_start":
                    wf_id = event.workflow_id
                if wf_id and event.workflow_id != wf_id:
                    continue

                event_data = {
                    "workflow_id": event.workflow_id,
                    "step": event.step,
                    "status": event.status,
                    "detail": event.detail,
                    "elapsed_ms": event.elapsed_ms,
                }

                pipeline_events = frozenset(
                    {
                        "plan",
                        "plan_summary",
                        "stage_start",
                        "stage_result",
                        "stage_validation",
                        "stage_complete",
                        "checkpoint",
                        "stage_retry",
                        "data_gate",
                    }
                )

                if event.step == "token":
                    yield (
                        f"event: token\ndata: "
                        f"{json.dumps({'chunk': event.detail}, default=str)}\n\n"
                    )
                    continue
                if event.step == "thinking":
                    yield f"event: thinking\ndata: {json.dumps(event_data, default=str)}\n\n"
                elif event.step in pipeline_events:
                    event_data["extra"] = event.extra
                    yield (f"event: {event.step}\ndata: {json.dumps(event_data, default=str)}\n\n")
                elif event.step.startswith("tool:") or ":tool:" in event.step:
                    yield f"event: tool_call\ndata: {json.dumps(event_data, default=str)}\n\n"
                elif any(event.step.startswith(p) for p in ("orchestrator:", "sql:", "knowledge:")):
                    agent_name = event.step.split(":")[0]
                    event_data["agent"] = agent_name
                    if event.extra:
                        event_data["extra"] = event.extra
                    if event.status == "started":
                        yield (
                            f"event: agent_start\ndata: {json.dumps(event_data, default=str)}\n\n"
                        )
                    elif event.status in ("completed", "failed"):
                        yield (f"event: agent_end\ndata: {json.dumps(event_data, default=str)}\n\n")
                    else:
                        yield f"event: step\ndata: {json.dumps(event_data, default=str)}\n\n"
                else:
                    yield f"event: step\ndata: {json.dumps(event_data, default=str)}\n\n"

                if event.step == "pipeline_end":
                    break

            _grace_period = min(20, stream_timeout_seconds)
            wait_deadline = time.monotonic() + _grace_period
            while not task.done():
                remaining = wait_deadline - time.monotonic()
                if remaining <= 0:
                    task.cancel()
                    await _finalize_on_error(wf_id, "Request timed out")
                    async with _stream_session_factory() as _err_db:
                        await _chat_svc.update_session_status(_err_db, session_id, "idle")
                    error_payload = {
                        "error": "Request timed out",
                        "error_type": "timeout",
                        "is_retryable": True,
                        "user_message": (
                            "The request took too long to complete. "
                            "Please try again with a simpler question."
                        ),
                    }
                    yield f"event: error\ndata: {json.dumps(error_payload, default=str)}\n\n"
                    return
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=min(20, remaining))
                except TimeoutError:
                    yield ": heartbeat\n\n"
                except Exception as exc:
                    await _finalize_on_error(wf_id, str(exc))
                    async with _stream_session_factory() as _err_db:
                        await _chat_svc.update_session_status(_err_db, session_id, "idle")
                    error_payload = _build_structured_error(exc)
                    yield f"event: error\ndata: {json.dumps(error_payload, default=str)}\n\n"
                    return
            result = result_holder[0] if result_holder else None
            if not result:
                _task_err_msg = "No result produced"
                if task.done() and not task.cancelled():
                    try:
                        task_exc = task.exception()
                        if task_exc:
                            _task_err_msg = f"Agent error: {task_exc}"[:500]
                    except Exception:
                        pass
                await _finalize_on_error(wf_id, _task_err_msg)
                async with _stream_session_factory() as _err_db:
                    await _chat_svc.update_session_status(_err_db, session_id, "idle")
                error_payload = {
                    "error": "No result",
                    "error_type": "internal",
                    "is_retryable": True,
                    "user_message": "An unexpected error occurred. Please try again.",
                }
                yield f"event: error\ndata: {json.dumps(error_payload, default=str)}\n\n"
                return
            viz_data = None
            if result.results and not result.error:
                viz_data = render(
                    result=result.results,
                    viz_type=result.viz_type,
                    config=result.viz_config,
                    summary=result.answer,
                )

            raw_result = _build_raw_result(result.results)

            stream_rag = [
                {
                    "source_path": s.source_path,
                    "distance": s.distance,
                    "doc_type": s.doc_type,
                }
                for s in result.knowledge_sources
            ]

            tool_calls_str = (
                json.dumps(result.tool_call_log, default=str) if result.tool_call_log else None
            )

            s_usage = result.token_usage or {}
            s_cost = _estimate_cost(
                result.llm_model,
                s_usage.get("prompt_tokens", 0),
                s_usage.get("completion_tokens", 0),
            )
            s_enriched_usage = (
                {
                    **(result.token_usage or {}),
                    "provider": result.llm_provider or "unknown",
                    "model": result.llm_model or "unknown",
                    "estimated_cost_usd": s_cost,
                    "prompt_version": result.prompt_version,
                }
                if result.token_usage
                else None
            )

            stream_sql_results = _build_sql_results_payload(result.sql_results, result.answer)

            async with _stream_session_factory() as stream_db:
                assistant_msg = await _chat_svc.add_message(
                    stream_db,
                    session_id,
                    "assistant",
                    result.answer,
                    metadata={
                        "query": result.query,
                        "query_explanation": result.query_explanation,
                        "question": body.message,
                        "viz_type": result.viz_type,
                        "visualization": viz_data,
                        "raw_result": raw_result,
                        "error": result.error,
                        "workflow_id": result.workflow_id,
                        "row_count": (result.results.row_count if result.results else None),
                        "execution_time_ms": (
                            result.results.execution_time_ms if result.results else None
                        ),
                        "rag_sources": stream_rag,
                        "token_usage": s_enriched_usage,
                        "response_type": result.response_type,
                        "staleness_warning": result.staleness_warning,
                        "insights": result.insights or [],
                        "suggested_followups": result.suggested_followups or [],
                        "clarification_data": result.clarification_data,
                        "sql_results": stream_sql_results,
                        "continuation_context": result.continuation_context,
                        "exposed_learning_ids": result.exposed_learning_ids,
                    },
                    tool_calls_json=tool_calls_str,
                )

                # R4-2: credit exposed learnings on a validated streamed result.
                await credit_validated_learnings(
                    result, body.connection_id, message_id=assistant_msg.id
                )

                # R5-7: auto-route a suspicious streamed result to investigation.
                await maybe_auto_investigate(
                    result,
                    project_id=body.project_id,
                    connection_id=body.connection_id,
                    session_id=session_id,
                    message_id=assistant_msg.id,
                )

                if stream_rag:
                    try:
                        await _rag_feedback_svc.record(
                            session=stream_db,
                            project_id=body.project_id,
                            rag_sources=stream_rag,
                            query_succeeded=not result.error,
                            question_snippet=body.message[:200],
                        )
                    except Exception:
                        logger.warning("Failed to record RAG feedback", exc_info=True)

                stream_usage = result.token_usage or {}
                try:
                    await _usage_svc.record_usage(
                        stream_db,
                        user_id=user["user_id"],
                        project_id=body.project_id,
                        session_id=session_id,
                        message_id=assistant_msg.id,
                        provider=result.llm_provider or "unknown",
                        model=result.llm_model or "unknown",
                        prompt_tokens=stream_usage.get("prompt_tokens", 0),
                        completion_tokens=stream_usage.get("completion_tokens", 0),
                        total_tokens=stream_usage.get("total_tokens", 0),
                        estimated_cost_usd=_estimate_cost(
                            result.llm_model,
                            stream_usage.get("prompt_tokens", 0),
                            stream_usage.get("completion_tokens", 0),
                        ),
                    )
                except Exception:
                    logger.warning("Failed to record token usage", exc_info=True)

                if result.workflow_id:
                    try:
                        trace_svc = getattr(request.app.state, "trace_persistence_service", None)
                        if trace_svc is not None:
                            await trace_svc.finalize_trace(
                                result.workflow_id,
                                project_id=body.project_id,
                                user_id=user["user_id"],
                                session_id=session_id,
                                message_id=user_message_id,
                                assistant_message_id=assistant_msg.id,
                                question=body.message,
                                response_type=result.response_type or "text",
                                status="failed" if result.error else "completed",
                                error_message=result.error,
                                total_duration_ms=result.results.execution_time_ms
                                if result.results
                                else None,
                                total_tokens=stream_usage.get("total_tokens", 0)
                                or (
                                    stream_usage.get("prompt_tokens", 0)
                                    + stream_usage.get("completion_tokens", 0)
                                ),
                                estimated_cost_usd=_estimate_cost(
                                    result.llm_model,
                                    stream_usage.get("prompt_tokens", 0),
                                    stream_usage.get("completion_tokens", 0),
                                ),
                                llm_provider=result.llm_provider or "unknown",
                                llm_model=result.llm_model or "unknown",
                                steps_used=result.steps_used,
                                steps_total=result.steps_total,
                                tool_call_log=result.tool_call_log,
                            )
                    except Exception:
                        logger.warning("Failed to finalize request trace (stream)", exc_info=True)

            final = {
                "session_id": session_id,
                "answer": result.answer,
                "query": result.query,
                "query_explanation": result.query_explanation,
                "visualization": viz_data,
                "viz_config": result.viz_config or None,
                "raw_result": raw_result,
                "error": result.error,
                "workflow_id": result.workflow_id,
                "rag_sources": stream_rag,
                "staleness_warning": result.staleness_warning,
                "token_usage": s_enriched_usage,
                "response_type": result.response_type,
                "assistant_message_id": assistant_msg.id,
                "user_message_id": user_message_id,
                "rules_changed": _has_rules_changed(result.tool_call_log),
                "insights": result.insights or [],
                "suggested_followups": result.suggested_followups or [],
                "steps_used": result.steps_used,
                "steps_total": result.steps_total,
                "continuation_context": result.continuation_context,
                "clarification_data": result.clarification_data,
                "sql_results": stream_sql_results,
            }
            yield f"event: result\ndata: {json.dumps(final, default=str)}\n\n"
            # Normal completion: mark session idle
            async with _stream_session_factory() as _idle_db:
                await _chat_svc.update_session_status(_idle_db, session_id, "idle")
        finally:
            await tracker.unsubscribe(queue)
            if not task.done():
                # Client disconnected while agent is still running.
                # Schedule a background finalizer to persist results instead of cancelling.
                _bg_task = asyncio.create_task(
                    _background_finalize(
                        bg_task=task,
                        bg_session_id=session_id,
                        bg_body=body,
                        bg_user_message_id=user_message_id,
                        bg_user_id=user["user_id"],
                        bg_request_app=request.app,
                    )
                )
                _background_finalize_tasks.add(_bg_task)
                _bg_task.add_done_callback(_background_finalize_tasks.discard)
            else:
                # Task already done (normal flow or error already handled).
                # Release the limiter only if background finalizer wasn't scheduled.
                if not released:
                    released = True
                    await agent_limiter.release(user["user_id"])
                # Release the per-session processing lock. On the disconnect
                # path the lock is released inside _background_finalize; on the
                # normal-completion path it must be released here, otherwise the
                # session stays "busy" (asyncio.Lock held) and every subsequent
                # request to it gets HTTP 409 until the 1h TTL evicts the entry.
                if not lock_released:
                    lock_released = True
                    try:
                        await _stream_lock_cm.__aexit__(None, None, None)
                    except Exception:
                        logger.debug("Stream session lock release failed", exc_info=True)

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class WsTicketRequest(BaseModel):
    """Body for minting a single-use WebSocket ticket."""

    project_id: str
    connection_id: str = "_none"


class WsTicketResponse(BaseModel):
    ticket: str
    expires_in: int


@router.post("/ws-ticket", response_model=WsTicketResponse)
async def issue_ws_ticket(
    body: WsTicketRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> WsTicketResponse:
    """Issue a short-lived, single-use ticket for the chat WebSocket (T-SEC-2).

    The browser calls this authenticated endpoint, then passes the returned
    ticket to the WS handshake via ``Sec-WebSocket-Protocol`` so no credential
    ever appears in a URL. The ticket is bound to this user and the exact
    project/connection it is issued for.
    """
    await _membership_svc.require_role(db, body.project_id, user["user_id"], "viewer")
    ticket, ttl = await ws_ticket_store.issue(
        user_id=user["user_id"],
        project_id=body.project_id,
        connection_id=body.connection_id,
    )
    return WsTicketResponse(ticket=ticket, expires_in=ttl)


@router.websocket("/ws/{project_id}/{connection_id}")
async def chat_websocket(
    websocket: WebSocket,
    project_id: str,
    connection_id: str,
):
    import asyncio

    from sqlalchemy import or_, select

    from app.core.workflow_tracker import tracker
    from app.core.ws_tickets import TICKET_SUBPROTOCOL_PREFIX, ws_ticket_store
    from app.models.base import async_session_factory
    from app.models.project import Project
    from app.models.project_member import ProjectMember

    # T-SEC-2: authenticate via a single-use ticket carried in
    # Sec-WebSocket-Protocol, never via a token in the URL query string.
    offered = websocket.headers.get("sec-websocket-protocol", "")
    ticket: str | None = None
    accept_subprotocol: str | None = None
    for proto in (p.strip() for p in offered.split(",") if p.strip()):
        if proto.startswith(TICKET_SUBPROTOCOL_PREFIX):
            ticket = proto[len(TICKET_SUBPROTOCOL_PREFIX) :]
            accept_subprotocol = proto
            break

    user_id: str | None = None
    if ticket:
        user_id = await ws_ticket_store.redeem(ticket, project_id, connection_id)
    if not user_id:
        await websocket.close(code=4001, reason="Authentication required")
        return

    async with async_session_factory() as db:
        access_check = await db.execute(
            select(Project.id).where(
                Project.id == project_id,
                or_(
                    Project.owner_id == user_id,
                    Project.id.in_(
                        select(ProjectMember.project_id).where(ProjectMember.user_id == user_id)
                    ),
                ),
            )
        )
        if not access_check.scalar_one_or_none():
            await websocket.close(code=4003, reason="Access denied")
            return

    # Echo the ticket subprotocol so the browser handshake completes.
    if accept_subprotocol:
        await websocket.accept(subprotocol=accept_subprotocol)
    else:
        await websocket.accept()

    session_id: str | None = None
    config = None

    async def _relay_events(
        queue: asyncio.Queue[WorkflowEvent],
    ) -> None:
        wf_id: str | None = None
        try:
            while True:
                event = await asyncio.wait_for(queue.get(), timeout=60)
                if wf_id is None and event.step == "pipeline_start":
                    wf_id = event.workflow_id
                if wf_id and event.workflow_id != wf_id:
                    continue
                if event.step.startswith("tool:") or ":tool:" in event.step:
                    msg_type = "tool_call"
                elif event.step.startswith(("orchestrator:", "sql:", "knowledge:")):
                    agent_name = event.step.split(":")[0]
                    msg_type = (
                        "agent_start"
                        if event.status == "started"
                        else ("agent_end" if event.status in ("completed", "failed") else "step")
                    )
                else:
                    msg_type = "step"
                payload: dict = {
                    "type": msg_type,
                    "step": event.step,
                    "status": event.status,
                    "detail": event.detail,
                    "elapsed_ms": event.elapsed_ms,
                }
                if msg_type in ("agent_start", "agent_end"):
                    payload["agent"] = agent_name
                await websocket.send_json(payload)
                if event.step == "pipeline_end":
                    break
        except TimeoutError:
            logger.debug("WebSocket relay timed out (no events for 60s)")
        except Exception:
            logger.warning("WebSocket relay error", exc_info=True)

    try:
        async with async_session_factory() as db:
            role = await _membership_svc.get_role(db, project_id, user_id)
            if not role:
                await websocket.send_json({"error": "Not a member of this project"})
                await websocket.close()
                return

            config = None
            if connection_id and connection_id != "_none":
                conn_model = await _conn_svc.get(db, connection_id)
                if not conn_model:
                    await websocket.send_json({"error": "Connection not found"})
                    await websocket.close()
                    return
                try:
                    config = await _conn_svc.to_config(db, conn_model)
                except ValueError:
                    await websocket.send_json(
                        {
                            "error": (
                                f"Cannot decrypt credentials for"
                                f" '{conn_model.name}'."
                                " Re-enter the password in Settings."
                            ),
                        }
                    )
                    await websocket.close()
                    return
                config.connection_id = connection_id

            ws_project = await _project_svc.get(db, project_id)

            ws_conn_id = connection_id if connection_id and connection_id != "_none" else None
            chat_session = await _chat_svc.create_session(
                db,
                project_id,
                user_id=user_id,
                connection_id=ws_conn_id,
            )
            session_id = chat_session.id

        await websocket.send_json(
            {
                "type": "session_created",
                "session_id": session_id,
            }
        )

        from app.config import settings as app_settings

        while True:
            # L5: bound idle waits so an abandoned socket doesn't hold resources
            # indefinitely. 0 disables the timeout.
            ws_idle = app_settings.ws_idle_timeout_seconds
            try:
                if ws_idle and ws_idle > 0:
                    data = await asyncio.wait_for(websocket.receive_json(), timeout=ws_idle)
                else:
                    data = await websocket.receive_json()
            except TimeoutError:
                logger.info("WS chat idle timeout (%ss) — closing connection", ws_idle)
                try:
                    await websocket.send_json(
                        {
                            "type": "idle_timeout",
                            "message": "Connection closed due to inactivity.",
                        }
                    )
                except Exception:
                    logger.debug("WS: failed to send idle_timeout notice", exc_info=True)
                await websocket.close(code=1000)
                break
            try:
                ws_msg = WsChatMessage.model_validate(data)
            except Exception as val_err:
                await websocket.send_json(
                    {"type": "error", "message": f"Invalid message: {val_err}"}
                )
                continue
            message = ws_msg.message

            limit_err = await agent_limiter.acquire(user_id)
            if limit_err:
                await websocket.send_json({"type": "error", "message": limit_err})
                continue

            # F-FIN-1: enforce the per-user token budget on the WS path too.
            async with async_session_factory() as db:
                budget_error = await _check_token_budget(db, user_id)
            if budget_error:
                await websocket.send_json({"type": "error", "message": budget_error})
                await agent_limiter.release(user_id)
                continue

            # R5-5: serialize concurrent requests for the same session (e.g. two
            # browser tabs on one session) exactly like the HTTP/stream paths,
            # otherwise interleaved runs corrupt shared session/pipeline state.
            ws_lock_cm = session_processing_lock(session_id)
            try:
                await ws_lock_cm.__aenter__()
            except SessionBusyError:
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": "This chat session is currently processing another "
                        "request. Please wait for it to complete.",
                    }
                )
                await agent_limiter.release(user_id)
                continue

            try:
                async with async_session_factory() as db:
                    ws_user_msg = await _chat_svc.add_message(db, session_id, "user", message)
                    ws_user_message_id = ws_user_msg.id
                    history = await _chat_svc.get_history_as_messages(db, session_id)

                queue = await tracker.subscribe(
                    user_id=user_id,
                    accessible_project_ids={project_id},
                )
                relay_task = asyncio.create_task(_relay_events(queue))
            except Exception:
                # Setup failed AFTER acquiring the limiter + per-session lock but
                # before the main try/finally below — release them here so the
                # session is not wedged "busy" (lock leak, ~1h TTL) and the
                # concurrency token is returned. Keep the socket open.
                logger.warning("WS message setup failed", exc_info=True)
                await agent_limiter.release(user_id)
                try:
                    await ws_lock_cm.__aexit__(None, None, None)
                except Exception:
                    logger.debug("WS session lock release failed", exc_info=True)
                try:
                    await websocket.send_json(
                        {"type": "error", "message": "Failed to start processing this message."}
                    )
                except Exception:
                    logger.debug("WS: failed to send setup error", exc_info=True)
                continue

            try:
                _proj_agent_prov = ws_project.agent_llm_provider if ws_project else None
                _proj_agent_mdl = ws_project.agent_llm_model if ws_project else None
                ws_agent_provider = ws_msg.preferred_provider or _proj_agent_prov
                ws_agent_model = ws_msg.model or _proj_agent_mdl
                _proj_sql_prov = ws_project.sql_llm_provider if ws_project else None
                _proj_sql_mdl = ws_project.sql_llm_model if ws_project else None
                ws_sql_provider = _proj_sql_prov or ws_agent_provider
                ws_sql_model = _proj_sql_mdl or ws_agent_model

                result = await _agent.run(
                    question=message,
                    project_id=project_id,
                    connection_config=config,
                    chat_history=history[:-1],
                    preferred_provider=ws_agent_provider,
                    model=ws_agent_model,
                    sql_provider=ws_sql_provider,
                    sql_model=ws_sql_model,
                    project_name=ws_project.name if ws_project else None,
                    user_id=user_id,
                    # R5-5: the HTTP/stream paths thread session_id through ``extra``
                    # so session-scoped features (pipeline state, continuation,
                    # session notes) work; the WS path silently omitted it.
                    # L5: also thread the pipeline-control fields so checkpoint
                    # Continue / Modify / Retry work over the WebSocket transport.
                    extra=_ws_pipeline_extra(session_id, ws_msg),
                )

                viz_data = None
                if result.results and not result.error:
                    viz_data = render(
                        result=result.results,
                        viz_type=result.viz_type,
                        config=result.viz_config,
                        summary=result.answer,
                    )

                ws_raw_result = _build_raw_result(result.results)

                rag_dicts = [
                    {
                        "source_path": s.source_path,
                        "distance": s.distance,
                        "doc_type": s.doc_type,
                    }
                    for s in result.knowledge_sources
                ]

                ws_tool_calls_str = (
                    json.dumps(result.tool_call_log, default=str) if result.tool_call_log else None
                )

                ws_sql_results = _build_sql_results_payload(result.sql_results, result.answer)

                async with async_session_factory() as db:
                    ws_assistant_msg = await _chat_svc.add_message(
                        db,
                        session_id,
                        "assistant",
                        result.answer,
                        metadata={
                            "query": result.query,
                            "query_explanation": result.query_explanation,
                            "question": message,
                            "viz_type": result.viz_type,
                            "visualization": viz_data,
                            "raw_result": ws_raw_result,
                            "error": result.error,
                            "workflow_id": result.workflow_id,
                            "row_count": (result.results.row_count if result.results else None),
                            "execution_time_ms": (
                                result.results.execution_time_ms if result.results else None
                            ),
                            "rag_sources": rag_dicts,
                            "token_usage": result.token_usage or None,
                            "response_type": result.response_type,
                            "staleness_warning": result.staleness_warning,
                            "suggested_followups": result.suggested_followups or [],
                            "clarification_data": result.clarification_data,
                            "sql_results": ws_sql_results,
                            "continuation_context": result.continuation_context,
                            "exposed_learning_ids": result.exposed_learning_ids,
                        },
                        tool_calls_json=ws_tool_calls_str,
                    )

                    # R4-2: credit exposed learnings on a validated WS result.
                    await credit_validated_learnings(
                        result, ws_conn_id, message_id=ws_assistant_msg.id
                    )

                    # R5-7: auto-route a suspicious WS result to investigation.
                    await maybe_auto_investigate(
                        result,
                        project_id=project_id,
                        connection_id=ws_conn_id,
                        session_id=session_id,
                        message_id=ws_assistant_msg.id,
                    )

                    ws_usage = result.token_usage or {}
                    try:
                        await _usage_svc.record_usage(
                            db,
                            user_id=user_id,
                            project_id=project_id,
                            session_id=session_id,
                            message_id=ws_assistant_msg.id,
                            provider=result.llm_provider or "unknown",
                            model=result.llm_model or "unknown",
                            prompt_tokens=ws_usage.get("prompt_tokens", 0),
                            completion_tokens=ws_usage.get("completion_tokens", 0),
                            total_tokens=ws_usage.get("total_tokens", 0),
                            estimated_cost_usd=_estimate_cost(
                                result.llm_model,
                                ws_usage.get("prompt_tokens", 0),
                                ws_usage.get("completion_tokens", 0),
                            ),
                        )
                    except Exception:
                        logger.warning("WS: Failed to record token usage", exc_info=True)

                    if result.workflow_id:
                        try:
                            trace_svc = getattr(
                                websocket.app.state, "trace_persistence_service", None
                            )
                            if trace_svc is not None:
                                await trace_svc.finalize_trace(
                                    result.workflow_id,
                                    project_id=project_id,
                                    user_id=user_id,
                                    session_id=session_id,
                                    message_id=ws_user_message_id,
                                    assistant_message_id=ws_assistant_msg.id,
                                    question=message,
                                    response_type=result.response_type or "text",
                                    status="failed" if result.error else "completed",
                                    error_message=result.error,
                                    total_duration_ms=(
                                        result.results.execution_time_ms if result.results else None
                                    ),
                                    total_tokens=ws_usage.get("total_tokens", 0)
                                    or (
                                        ws_usage.get("prompt_tokens", 0)
                                        + ws_usage.get("completion_tokens", 0)
                                    ),
                                    estimated_cost_usd=_estimate_cost(
                                        result.llm_model,
                                        ws_usage.get("prompt_tokens", 0),
                                        ws_usage.get("completion_tokens", 0),
                                    ),
                                    llm_provider=result.llm_provider or "unknown",
                                    llm_model=result.llm_model or "unknown",
                                    steps_used=result.steps_used,
                                    steps_total=result.steps_total,
                                    tool_call_log=result.tool_call_log,
                                )
                        except Exception:
                            logger.warning("WS: Failed to finalize request trace", exc_info=True)

                await websocket.send_json(
                    {
                        "type": "response",
                        "answer": result.answer,
                        "query": result.query,
                        "query_explanation": result.query_explanation,
                        "visualization": viz_data,
                        "viz_config": result.viz_config or None,
                        "raw_result": ws_raw_result,
                        "error": result.error,
                        "workflow_id": result.workflow_id,
                        "response_type": result.response_type,
                        "rag_sources": rag_dicts,
                        "staleness_warning": result.staleness_warning,
                        "assistant_message_id": ws_assistant_msg.id,
                        "rules_changed": _has_rules_changed(result.tool_call_log),
                        "suggested_followups": result.suggested_followups or [],
                        "clarification_data": result.clarification_data,
                        "sql_results": ws_sql_results,
                    }
                )
            finally:
                if not relay_task.done():
                    relay_task.cancel()
                    try:
                        await relay_task
                    except (asyncio.CancelledError, Exception):
                        pass
                await tracker.unsubscribe(queue)
                await agent_limiter.release(user_id)
                # R5-5: release the per-session lock acquired above.
                try:
                    await ws_lock_cm.__aexit__(None, None, None)
                except Exception:
                    logger.debug("WS session lock release failed", exc_info=True)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for project %s", project_id)
    except Exception:
        logger.exception("WebSocket error")
        try:
            err_msg = "An internal error occurred. Please try again."
            await websocket.send_json({"type": "error", "message": err_msg})
        except Exception:
            logger.debug("Failed to send error over WebSocket", exc_info=True)
