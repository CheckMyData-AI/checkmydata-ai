import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.agent import ConversationalAgent
from app.core.rate_limit import limiter
from app.core.workflow_tracker import WorkflowEvent, tracker
from app.services.chat_service import ChatService
from app.services.connection_service import ConnectionService
from app.services.membership_service import MembershipService
from app.services.project_service import ProjectService
from app.services.rag_feedback_service import RAGFeedbackService
from app.viz.renderer import render

logger = logging.getLogger(__name__)

router = APIRouter()
_chat_svc = ChatService()
_conn_svc = ConnectionService()
_project_svc = ProjectService()
_agent = ConversationalAgent()
_rag_feedback_svc = RAGFeedbackService()
_membership_svc = MembershipService()


class ChatRequest(BaseModel):
    session_id: str | None = None
    project_id: str
    connection_id: str | None = None
    message: str
    preferred_provider: str | None = None
    model: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    query: str | None = None
    query_explanation: str | None = None
    visualization: dict | None = None
    raw_result: dict | None = None
    error: str | None = None
    workflow_id: str | None = None
    staleness_warning: str | None = None
    response_type: str = "text"
    assistant_message_id: str | None = None
    user_message_id: str | None = None
    rules_changed: bool = False


class SessionCreate(BaseModel):
    project_id: str
    title: str = "New Chat"
    connection_id: str | None = None


class SessionResponse(BaseModel):
    id: str
    project_id: str
    title: str
    connection_id: str | None = None


@router.post("/sessions", response_model=SessionResponse)
async def create_session(
    body: SessionCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, body.project_id, user["user_id"], "viewer")
    session = await _chat_svc.create_session(
        db,
        body.project_id,
        body.title,
        user_id=user["user_id"],
        connection_id=body.connection_id,
    )
    return session


@router.get("/sessions/{project_id}", response_model=list[SessionResponse])
async def list_sessions(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")
    return await _chat_svc.list_sessions(db, project_id, user_id=user["user_id"])


class SessionUpdate(BaseModel):
    title: str


async def _require_session_owner(db: AsyncSession, session_id: str, user_id: str):
    """Return the session if the user owns it, else raise 403/404."""
    session_obj = await _chat_svc.get_session(db, session_id)
    if not session_obj:
        raise HTTPException(status_code=404, detail="Session not found")
    if session_obj.user_id and session_obj.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not your session")
    return session_obj


@router.patch("/sessions/{session_id}", response_model=SessionResponse)
async def update_session(
    session_id: str,
    body: SessionUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _require_session_owner(db, session_id, user["user_id"])
    updated = await _chat_svc.update_session_title(db, session_id, body.title)
    if not updated:
        raise HTTPException(status_code=404, detail="Session not found")
    return updated


@router.post("/sessions/{session_id}/generate-title", response_model=SessionResponse)
async def generate_session_title(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Auto-generate a session title from the first user message."""
    from app.llm.base import Message as LLMMessage
    from app.llm.router import LLMRouter

    session_obj = await _require_session_owner(db, session_id, user["user_id"])

    first_user = next(
        (m.content for m in (session_obj.messages or []) if m.role == "user"),
        None,
    )
    if not first_user:
        raise HTTPException(status_code=400, detail="No user messages in session")

    try:
        router = LLMRouter()
        resp = await router.complete(
            messages=[
                LLMMessage(
                    role="system",
                    content=(
                        "Generate a short title (max 6 words) for a database chat session"
                        " based on the user's first question."
                        " Reply with ONLY the title, no quotes."
                    ),
                ),
                LLMMessage(role="user", content=first_user[:300]),
            ],
            max_tokens=30,
            temperature=0.3,
        )
        title = resp.content.strip().strip('"').strip("'")[:80] or first_user[:50]
    except Exception:
        title = first_user[:50]

    updated = await _chat_svc.update_session_title(db, session_id, title)
    return updated


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _require_session_owner(db, session_id, user["user_id"])
    deleted = await _chat_svc.delete_session(db, session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True}


class FeedbackRequest(BaseModel):
    message_id: str
    rating: int  # 1 (thumbs up) or -1 (thumbs down)


@router.post("/feedback")
async def submit_feedback(
    body: FeedbackRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Record user feedback (thumbs up/down) on an assistant message."""
    from sqlalchemy import select

    from app.models.chat_session import ChatMessage as ChatMessageModel

    result = await db.execute(
        select(ChatMessageModel).where(ChatMessageModel.id == body.message_id)
    )
    msg = result.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    if msg.role != "assistant":
        raise HTTPException(status_code=400, detail="Can only rate assistant messages")

    msg.user_rating = max(-1, min(1, body.rating))
    await db.commit()

    if body.rating == -1 and msg.metadata_json:
        try:
            import json as _json

            from app.knowledge.learning_analyzer import LearningAnalyzer
            from app.models.base import async_session_factory

            meta = _json.loads(msg.metadata_json)
            query = meta.get("query")
            question = meta.get("question", "")
            session_row = msg.session
            connection_id = getattr(session_row, "connection_id", None) if session_row else None

            if connection_id and query:
                analyzer = LearningAnalyzer()
                async with async_session_factory() as learn_session:
                    await analyzer.analyze_negative_feedback(
                        session=learn_session,
                        connection_id=connection_id,
                        query=query,
                        question=question,
                        error_detail="User rated this result as incorrect (thumbs down)",
                    )
        except Exception:
            logger.debug("Feedback-triggered learning extraction failed", exc_info=True)

    return {"ok": True, "message_id": body.message_id, "rating": msg.user_rating}


@router.get("/analytics/feedback/{project_id}")
async def get_feedback_analytics(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Return aggregated feedback stats for a project."""
    from sqlalchemy import and_, func, select

    from app.models.chat_session import ChatMessage as ChatMessageModel
    from app.models.chat_session import ChatSession

    stmt = (
        select(
            func.count().label("total_rated"),
            func.sum((ChatMessageModel.user_rating == 1).cast(int)).label("positive"),
            func.sum((ChatMessageModel.user_rating == -1).cast(int)).label("negative"),
        )
        .join(ChatSession, ChatMessageModel.session_id == ChatSession.id)
        .where(
            and_(
                ChatSession.project_id == project_id,
                ChatMessageModel.user_rating.isnot(None),
            ),
        )
    )
    result = await db.execute(stmt)
    row = result.one()
    return {
        "total_rated": row.total_rated or 0,
        "positive": row.positive or 0,
        "negative": row.negative or 0,
    }


class MessageResponse(BaseModel):
    id: str
    role: str
    content: str
    metadata_json: str | None = None
    tool_calls_json: str | None = None
    user_rating: int | None = None
    created_at: str


@router.get("/sessions/{session_id}/messages", response_model=list[MessageResponse])
async def get_session_messages(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    session = await _require_session_owner(db, session_id, user["user_id"])
    return [
        MessageResponse(
            id=m.id,
            role=m.role,
            content=m.content,
            metadata_json=m.metadata_json,
            tool_calls_json=m.tool_calls_json,
            user_rating=m.user_rating,
            created_at=m.created_at.isoformat() if m.created_at else "",
        )
        for m in session.messages
    ]


_RAW_RESULT_ROW_CAP = 500


def _has_rules_changed(tool_call_log: list[dict] | None) -> bool:
    """Return True if any tool call in the log is ``manage_custom_rules``."""
    if not tool_call_log:
        return False
    return any(tc.get("tool") == "manage_custom_rules" for tc in tool_call_log)


def _build_raw_result(results) -> dict | None:
    """Extract raw tabular data from query results, capped at 500 rows."""
    if not results:
        return None
    cols = getattr(results, "columns", None)
    rows = getattr(results, "rows", None)
    if not cols:
        return None
    from app.viz.utils import serialize_value

    return {
        "columns": list(cols),
        "rows": [
            [serialize_value(v) for v in row]
            for row in (rows or [])[:_RAW_RESULT_ROW_CAP]
        ],
        "total_rows": getattr(results, "row_count", len(rows or [])),
    }


@router.post("/ask", response_model=ChatResponse)
@limiter.limit("20/minute")
async def ask(
    request: Request,
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, body.project_id, user["user_id"], "viewer")

    config = None
    if body.connection_id:
        conn_model = await _conn_svc.get(db, body.connection_id)
        if not conn_model:
            raise HTTPException(status_code=404, detail="Connection not found")
        config = await _conn_svc.to_config(db, conn_model)
        config.connection_id = body.connection_id

    session_id = body.session_id
    if not session_id:
        chat_session = await _chat_svc.create_session(
            db,
            body.project_id,
            user_id=user["user_id"],
            connection_id=body.connection_id,
        )
        session_id = chat_session.id

    user_msg = await _chat_svc.add_message(db, session_id, "user", body.message)
    history = await _chat_svc.get_history_as_messages(db, session_id)

    logger.info(
        "Chat request: project=%s session=%s conn=%s",
        body.project_id[:8], session_id[:8], (body.connection_id or "none")[:8],
    )

    project = await _project_svc.get(db, body.project_id)
    agent_provider = body.preferred_provider or (project.agent_llm_provider if project else None)
    agent_model = body.model or (project.agent_llm_model if project else None)
    sql_provider = (project.sql_llm_provider if project else None) or agent_provider
    sql_model = (project.sql_llm_model if project else None) or agent_model

    result = await _agent.run(
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
    )

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

    assistant_msg = await _chat_svc.add_message(
        db,
        session_id,
        "assistant",
        result.answer,
        metadata={
            "query": result.query,
            "query_explanation": result.query_explanation,
            "viz_type": result.viz_type,
            "visualization": viz_data,
            "raw_result": raw_result,
            "error": result.error,
            "workflow_id": result.workflow_id,
            "row_count": (
                result.results.row_count if result.results else None
            ),
            "execution_time_ms": (
                result.results.execution_time_ms
                if result.results
                else None
            ),
            "rag_sources": rag_source_dicts,
            "token_usage": result.token_usage or None,
            "response_type": result.response_type,
            "staleness_warning": result.staleness_warning,
        },
        tool_calls_json=tool_calls_str,
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

    return ChatResponse(
        session_id=session_id,
        answer=result.answer,
        query=result.query or None,
        query_explanation=result.query_explanation or None,
        visualization=viz_data,
        raw_result=raw_result,
        error=result.error,
        workflow_id=result.workflow_id,
        staleness_warning=result.staleness_warning,
        response_type=result.response_type,
        assistant_message_id=assistant_msg.id,
        user_message_id=user_msg.id,
        rules_changed=_has_rules_changed(result.tool_call_log),
    )


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

    config = None
    if body.connection_id:
        conn_model = await _conn_svc.get(db, body.connection_id)
        if not conn_model:
            raise HTTPException(status_code=404, detail="Connection not found")
        config = await _conn_svc.to_config(db, conn_model)
        config.connection_id = body.connection_id

    session_id = body.session_id
    if not session_id:
        chat_session = await _chat_svc.create_session(
            db,
            body.project_id,
            user_id=user["user_id"],
            connection_id=body.connection_id,
        )
        session_id = chat_session.id

    user_msg = await _chat_svc.add_message(db, session_id, "user", body.message)
    user_message_id = user_msg.id
    history = await _chat_svc.get_history_as_messages(db, session_id)

    logger.info(
        "Chat stream request: project=%s session=%s conn=%s",
        body.project_id[:8], session_id[:8], (body.connection_id or "none")[:8],
    )

    project = await _project_svc.get(db, body.project_id)
    agent_provider = body.preferred_provider or (project.agent_llm_provider if project else None)
    agent_model = body.model or (project.agent_llm_model if project else None)
    sql_provider = (project.sql_llm_provider if project else None) or agent_provider
    sql_model = (project.sql_llm_model if project else None) or agent_model
    project_name = project.name if project else None

    async def _generate():
        result_holder: list = []
        queue = tracker.subscribe()

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
            )
            result_holder.append(res)

        task = asyncio.create_task(_process())

        wf_id = None
        while not task.done() or not queue.empty():
            try:
                event = await asyncio.wait_for(queue.get(), timeout=0.5)
            except TimeoutError:
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

            if event.step.startswith("tool:"):
                yield f"event: tool_call\ndata: {json.dumps(event_data, default=str)}\n\n"
            else:
                yield f"event: step\ndata: {json.dumps(event_data, default=str)}\n\n"

            if event.step == "pipeline_end":
                break

        try:
            await task
        except Exception as exc:
            tracker.unsubscribe(queue)
            yield f"event: error\ndata: {json.dumps({'error': str(exc)}, default=str)}\n\n"
            return
        tracker.unsubscribe(queue)
        result = result_holder[0] if result_holder else None
        if not result:
            yield f"event: error\ndata: {json.dumps({'error': 'No result'}, default=str)}\n\n"
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

        assistant_msg = await _chat_svc.add_message(
            db,
            session_id,
            "assistant",
            result.answer,
            metadata={
                "query": result.query,
                "query_explanation": result.query_explanation,
                "viz_type": result.viz_type,
                "visualization": viz_data,
                "raw_result": raw_result,
                "error": result.error,
                "workflow_id": result.workflow_id,
                "row_count": (
                    result.results.row_count if result.results else None
                ),
                "execution_time_ms": (
                    result.results.execution_time_ms
                    if result.results
                    else None
                ),
                "rag_sources": stream_rag,
                "token_usage": result.token_usage or None,
                "response_type": result.response_type,
                "staleness_warning": result.staleness_warning,
            },
            tool_calls_json=tool_calls_str,
        )

        if stream_rag:
            try:
                await _rag_feedback_svc.record(
                    session=db,
                    project_id=body.project_id,
                    rag_sources=stream_rag,
                    query_succeeded=not result.error,
                    question_snippet=body.message[:200],
                )
            except Exception:
                logger.warning("Failed to record RAG feedback", exc_info=True)

        final = {
            "session_id": session_id,
            "answer": result.answer,
            "query": result.query,
            "query_explanation": result.query_explanation,
            "visualization": viz_data,
            "raw_result": raw_result,
            "error": result.error,
            "workflow_id": result.workflow_id,
            "rag_sources": stream_rag,
            "staleness_warning": result.staleness_warning,
            "token_usage": result.token_usage or None,
            "response_type": result.response_type,
            "assistant_message_id": assistant_msg.id,
            "user_message_id": user_message_id,
            "rules_changed": _has_rules_changed(result.tool_call_log),
        }
        yield f"event: result\ndata: {json.dumps(final, default=str)}\n\n"

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.websocket("/ws/{project_id}/{connection_id}")
async def chat_websocket(
    websocket: WebSocket,
    project_id: str,
    connection_id: str,
    token: str | None = None,
):
    import asyncio

    from app.core.workflow_tracker import tracker
    from app.models.base import async_session_factory
    from app.services.auth_service import AuthService

    auth_svc = AuthService()
    user_id: str | None = None
    if token:
        payload = auth_svc.decode_token(token)
        if payload:
            async with async_session_factory() as db:
                u = await auth_svc.get_by_id(db, payload["sub"])
                if u and u.is_active:
                    user_id = u.id
    if not user_id:
        await websocket.close(code=4001, reason="Authentication required")
        return

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
                msg_type = "tool_call" if event.step.startswith("tool:") else "step"
                await websocket.send_json(
                    {
                        "type": msg_type,
                        "step": event.step,
                        "status": event.status,
                        "detail": event.detail,
                        "elapsed_ms": event.elapsed_ms,
                    }
                )
                if event.step == "pipeline_end":
                    break
        except (TimeoutError, Exception):
            pass

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
                config = await _conn_svc.to_config(db, conn_model)
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

        while True:
            data = await websocket.receive_json()
            message = data.get("message", "")
            if not message:
                continue

            async with async_session_factory() as db:
                await _chat_svc.add_message(db, session_id, "user", message)
                history = await _chat_svc.get_history_as_messages(db, session_id)

            queue = tracker.subscribe()
            relay_task = asyncio.create_task(_relay_events(queue))

            try:
                _proj_agent_prov = ws_project.agent_llm_provider if ws_project else None
                _proj_agent_mdl = ws_project.agent_llm_model if ws_project else None
                ws_agent_provider = data.get("preferred_provider") or _proj_agent_prov
                ws_agent_model = data.get("model") or _proj_agent_mdl
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
                    json.dumps(result.tool_call_log, default=str)
                    if result.tool_call_log
                    else None
                )

                async with async_session_factory() as db:
                    ws_assistant_msg = await _chat_svc.add_message(
                        db,
                        session_id,
                        "assistant",
                        result.answer,
                        metadata={
                            "query": result.query,
                            "query_explanation": result.query_explanation,
                            "viz_type": result.viz_type,
                            "visualization": viz_data,
                            "raw_result": ws_raw_result,
                            "error": result.error,
                            "workflow_id": result.workflow_id,
                            "row_count": (
                                result.results.row_count
                                if result.results
                                else None
                            ),
                            "execution_time_ms": (
                                result.results.execution_time_ms
                                if result.results
                                else None
                            ),
                            "rag_sources": rag_dicts,
                            "token_usage": result.token_usage or None,
                            "response_type": result.response_type,
                            "staleness_warning": result.staleness_warning,
                        },
                        tool_calls_json=ws_tool_calls_str,
                    )

                await websocket.send_json(
                    {
                        "type": "response",
                        "answer": result.answer,
                        "query": result.query,
                        "query_explanation": result.query_explanation,
                        "visualization": viz_data,
                        "raw_result": ws_raw_result,
                        "error": result.error,
                        "workflow_id": result.workflow_id,
                        "response_type": result.response_type,
                        "rag_sources": rag_dicts,
                        "staleness_warning": result.staleness_warning,
                        "assistant_message_id": ws_assistant_msg.id,
                        "rules_changed": _has_rules_changed(result.tool_call_log),
                    }
                )
            finally:
                if not relay_task.done():
                    relay_task.cancel()
                tracker.unsubscribe(queue)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for project %s", project_id)
    except Exception as e:
        logger.exception("WebSocket error")
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
