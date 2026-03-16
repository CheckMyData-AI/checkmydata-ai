import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.orchestrator import Orchestrator
from app.core.rate_limit import limiter
from app.core.workflow_tracker import WorkflowEvent, tracker
from app.services.chat_service import ChatService
from app.services.connection_service import ConnectionService
from app.services.membership_service import MembershipService
from app.services.rag_feedback_service import RAGFeedbackService
from app.viz.renderer import render

logger = logging.getLogger(__name__)

router = APIRouter()
_chat_svc = ChatService()
_conn_svc = ConnectionService()
_orchestrator = Orchestrator()
_rag_feedback_svc = RAGFeedbackService()
_membership_svc = MembershipService()


class ChatRequest(BaseModel):
    session_id: str | None = None
    project_id: str
    connection_id: str
    message: str
    preferred_provider: str | None = None
    model: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    query: str | None = None
    query_explanation: str | None = None
    visualization: dict | None = None
    error: str | None = None
    workflow_id: str | None = None
    staleness_warning: str | None = None


class SessionCreate(BaseModel):
    project_id: str
    title: str = "New Chat"


class SessionResponse(BaseModel):
    id: str
    project_id: str
    title: str


@router.post("/sessions", response_model=SessionResponse)
async def create_session(
    body: SessionCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, body.project_id, user["user_id"], "viewer")
    session = await _chat_svc.create_session(
        db, body.project_id, body.title, user_id=user["user_id"],
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
                    content="Generate a short title (max 6 words) for a database chat session based on the user's first question. Reply with ONLY the title, no quotes.",
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
    return {"ok": True, "message_id": body.message_id, "rating": msg.user_rating}


@router.get("/analytics/feedback/{project_id}")
async def get_feedback_analytics(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Return aggregated feedback stats for a project."""
    from sqlalchemy import and_, func, select
    from app.models.chat_session import ChatMessage as ChatMessageModel, ChatSession

    stmt = (
        select(
            func.count().label("total_rated"),
            func.sum(
                (ChatMessageModel.user_rating == 1).cast(int)
            ).label("positive"),
            func.sum(
                (ChatMessageModel.user_rating == -1).cast(int)
            ).label("negative"),
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
            user_rating=m.user_rating,
            created_at=m.created_at.isoformat() if m.created_at else "",
        )
        for m in session.messages
    ]


@router.post("/ask", response_model=ChatResponse)
@limiter.limit("20/minute")
async def ask(
    request: Request,
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, body.project_id, user["user_id"], "viewer")
    conn_model = await _conn_svc.get(db, body.connection_id)
    if not conn_model:
        raise HTTPException(status_code=404, detail="Connection not found")

    config = await _conn_svc.to_config(db, conn_model)

    session_id = body.session_id
    if not session_id:
        chat_session = await _chat_svc.create_session(
            db, body.project_id, user_id=user["user_id"],
        )
        session_id = chat_session.id

    await _chat_svc.add_message(db, session_id, "user", body.message)

    history = await _chat_svc.get_history_as_messages(db, session_id)

    result = await _orchestrator.process_question(
        question=body.message,
        project_id=body.project_id,
        connection_config=config,
        chat_history=history[:-1],
        preferred_provider=body.preferred_provider,
        model=body.model,
    )

    viz_data = None
    if result.results and not result.error:
        viz_data = render(
            result=result.results,
            viz_type=result.viz_type,
            config=result.viz_config,
            summary=result.answer,
        )

    rag_source_dicts = [
        {
            "source_path": s.source_path,
            "distance": s.distance,
            "doc_type": s.doc_type,
        }
        for s in result.rag_sources
    ]

    await _chat_svc.add_message(
        db,
        session_id,
        "assistant",
        result.answer,
        metadata={
            "query": result.query,
            "viz_type": result.viz_type,
            "error": result.error,
            "workflow_id": result.workflow_id,
            "row_count": (
                result.results.row_count if result.results else None
            ),
            "execution_time_ms": (
                result.results.execution_time_ms
                if result.results else None
            ),
            "attempts": result.attempts,
            "total_attempts": result.total_attempts,
            "rag_sources": rag_source_dicts,
            "token_usage": result.token_usage or None,
        },
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

    return ChatResponse(
        session_id=session_id,
        answer=result.answer,
        query=result.query or None,
        query_explanation=result.query_explanation or None,
        visualization=viz_data,
        error=result.error,
        workflow_id=result.workflow_id,
        staleness_warning=result.staleness_warning,
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
    conn_model = await _conn_svc.get(db, body.connection_id)
    if not conn_model:
        raise HTTPException(status_code=404, detail="Connection not found")

    config = await _conn_svc.to_config(db, conn_model)

    session_id = body.session_id
    if not session_id:
        chat_session = await _chat_svc.create_session(
            db, body.project_id, user_id=user["user_id"],
        )
        session_id = chat_session.id

    await _chat_svc.add_message(db, session_id, "user", body.message)
    history = await _chat_svc.get_history_as_messages(db, session_id)

    async def _generate():
        result_holder: list = []
        queue = tracker.subscribe()

        async def _process():
            res = await _orchestrator.process_question(
                question=body.message,
                project_id=body.project_id,
                connection_config=config,
                chat_history=history[:-1],
                preferred_provider=body.preferred_provider,
                model=body.model,
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
            yield f"event: step\ndata: {json.dumps(event.to_dict())}\n\n"
            if event.step == "pipeline_end":
                break

        await task
        tracker.unsubscribe(queue)
        result = result_holder[0] if result_holder else None
        if not result:
            yield f"event: error\ndata: {json.dumps({'error': 'No result'})}\n\n"
            return

        viz_data = None
        if result.results and not result.error:
            viz_data = render(
                result=result.results,
                viz_type=result.viz_type,
                config=result.viz_config,
                summary=result.answer,
            )

        stream_rag = [
            {
                "source_path": s.source_path,
                "distance": s.distance,
                "doc_type": s.doc_type,
            }
            for s in result.rag_sources
        ]

        await _chat_svc.add_message(
            db, session_id, "assistant", result.answer,
            metadata={
                "query": result.query,
                "viz_type": result.viz_type,
                "error": result.error,
                "workflow_id": result.workflow_id,
                "row_count": (
                    result.results.row_count
                    if result.results else None
                ),
                "execution_time_ms": (
                    result.results.execution_time_ms
                    if result.results else None
                ),
                "attempts": result.attempts,
                "total_attempts": result.total_attempts,
                "rag_sources": stream_rag,
                "token_usage": result.token_usage or None,
            },
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
            "error": result.error,
            "workflow_id": result.workflow_id,
            "attempts": result.attempts,
            "total_attempts": result.total_attempts,
            "rag_sources": stream_rag,
            "staleness_warning": result.staleness_warning,
            "token_usage": result.token_usage or None,
        }
        yield f"event: result\ndata: {json.dumps(final)}\n\n"

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

    from app.core.workflow_tracker import WorkflowEvent, tracker
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
        """Forward tracker events over the WebSocket, discovering wf_id from first event."""
        wf_id: str | None = None
        try:
            while True:
                event = await asyncio.wait_for(queue.get(), timeout=60)
                if wf_id is None and event.step == "pipeline_start":
                    wf_id = event.workflow_id
                if wf_id and event.workflow_id != wf_id:
                    continue
                await websocket.send_json({
                    "type": "step",
                    "step": event.step,
                    "status": event.status,
                    "detail": event.detail,
                    "elapsed_ms": event.elapsed_ms,
                })
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
            conn_model = await _conn_svc.get(db, connection_id)
            if not conn_model:
                await websocket.send_json({"error": "Connection not found"})
                await websocket.close()
                return
            config = await _conn_svc.to_config(db, conn_model)
            chat_session = await _chat_svc.create_session(
                db, project_id, user_id=user_id,
            )
            session_id = chat_session.id

        await websocket.send_json({
            "type": "session_created",
            "session_id": session_id,
        })

        while True:
            data = await websocket.receive_json()
            message = data.get("message", "")
            if not message:
                continue

            async with async_session_factory() as db:
                await _chat_svc.add_message(db, session_id, "user", message)
                history = await _chat_svc.get_history_as_messages(
                    db, session_id,
                )

            queue = tracker.subscribe()
            relay_task = asyncio.create_task(_relay_events(queue))

            try:
                result = await _orchestrator.process_question(
                    question=message,
                    project_id=project_id,
                    connection_config=config,
                    chat_history=history[:-1],
                    preferred_provider=data.get("preferred_provider"),
                    model=data.get("model"),
                )

                viz_data = None
                if result.results and not result.error:
                    viz_data = render(
                        result=result.results,
                        viz_type=result.viz_type,
                        config=result.viz_config,
                        summary=result.answer,
                    )

                async with async_session_factory() as db:
                    await _chat_svc.add_message(
                        db,
                        session_id,
                        "assistant",
                        result.answer,
                        metadata={
                            "query": result.query,
                            "viz_type": result.viz_type,
                            "workflow_id": result.workflow_id,
                            "row_count": (
                                result.results.row_count
                                if result.results else None
                            ),
                            "execution_time_ms": (
                                result.results.execution_time_ms
                                if result.results else None
                            ),
                            "attempts": result.attempts,
                            "total_attempts": (
                                result.total_attempts
                            ),
                        },
                    )

                await websocket.send_json({
                    "type": "response",
                    "answer": result.answer,
                    "query": result.query,
                    "query_explanation": result.query_explanation,
                    "visualization": viz_data,
                    "error": result.error,
                    "workflow_id": result.workflow_id,
                })
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
