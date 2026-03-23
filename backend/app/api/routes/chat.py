import asyncio
import hashlib
import json
import logging
import re
import time
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.agent import ConversationalAgent
from app.core.agent_limiter import agent_limiter
from app.core.context_budget import CHARS_PER_TOKEN
from app.core.rate_limit import limiter
from app.core.workflow_tracker import WorkflowEvent, tracker
from app.llm.errors import LLMError
from app.services.chat_service import ChatService
from app.services.connection_service import ConnectionService
from app.services.membership_service import MembershipService
from app.services.project_service import ProjectService
from app.services.rag_feedback_service import RAGFeedbackService
from app.services.suggestion_engine import SuggestionEngine
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
_suggestion_engine = SuggestionEngine()

_SQL_EXPLAIN_CACHE: OrderedDict[str, dict] = OrderedDict()
_SQL_EXPLAIN_CACHE_MAX = 100
_SQL_EXPLAIN_CACHE_LOCK = asyncio.Lock()


def _compute_sql_complexity(sql: str) -> str:
    upper = sql.upper()
    has_recursive = bool(re.search(r"\bWITH\s+RECURSIVE\b", upper))
    has_cte = bool(re.search(r"\bWITH\b\s+\w+\s+AS\s*\(", upper))
    has_window = bool(re.search(r"\bOVER\s*\(", upper))
    join_count = len(re.findall(r"\bJOIN\b", upper))
    has_subquery = "SELECT" in upper[upper.find("FROM") + 1 :] if "FROM" in upper else False

    if has_recursive:
        return "expert"
    if has_cte and (has_window or join_count > 2):
        return "expert"
    if has_cte or has_window or has_subquery or join_count > 2:
        return "complex"
    if join_count >= 1:
        return "moderate"
    return "simple"


def _estimate_cost(model: str | None, prompt_tokens: int, completion_tokens: int) -> float | None:
    """Estimate USD cost using cached OpenRouter pricing data when available."""
    if not model:
        return None
    try:
        from app.api.routes.models import _cache

        cached = _cache.get("openrouter")
        if not cached:
            return None
        _, models_list = cached
        for m in models_list:
            if m["id"] == model:
                pricing = m.get("pricing", {})
                prompt_price = float(pricing.get("prompt", "0"))
                completion_price = float(pricing.get("completion", "0"))
                return round(prompt_tokens * prompt_price + completion_tokens * completion_price, 8)
    except Exception:
        logger.debug("Cost computation failed", exc_info=True)
    return None


def _estimate_tokens(text: str) -> int:
    return max(0, len(text) // CHARS_PER_TOKEN) if text else 0


class CostEstimateBreakdown(BaseModel):
    schema_context: int = 0
    rules: int = 0
    learnings: int = 0
    overview: int = 0
    history_budget_remaining: int = 0


class CostEstimateResponse(BaseModel):
    estimated_prompt_tokens: int = 0
    estimated_completion_tokens: int = 0
    estimated_total_tokens: int = 0
    estimated_cost_usd: float | None = None
    context_utilization_pct: float = 0.0
    breakdown: CostEstimateBreakdown = CostEstimateBreakdown()


@router.get("/estimate", response_model=CostEstimateResponse)
@limiter.limit("30/minute")
async def estimate_cost(
    request: Request,
    project_id: str = Query(...),
    connection_id: str = Query(None),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")

    from sqlalchemy import func, select

    from app.config import settings as app_settings
    from app.knowledge.custom_rules import CustomRulesEngine
    from app.models.token_usage import TokenUsage

    rules_engine = CustomRulesEngine()

    schema_tokens = 0
    if connection_id:
        try:
            from app.services.db_index_service import DbIndexService

            svc = DbIndexService()
            entries = await svc.get_index(db, connection_id)
            table_map = svc.build_table_map(entries)
            schema_tokens = _estimate_tokens(table_map)
        except Exception:
            logger.debug("Cost estimate: schema lookup failed", exc_info=True)

    from app.api.deps import validate_safe_id

    validate_safe_id(project_id, "project_id")

    rules_text = ""
    try:
        file_rules = rules_engine.load_rules(
            project_rules_dir=f"{app_settings.custom_rules_dir}/{project_id}",
        )
        db_rules = await rules_engine.load_db_rules(project_id=project_id)
        rules_text = rules_engine.rules_to_context(file_rules + db_rules)
    except Exception:
        logger.debug("Cost estimate: rules loading failed", exc_info=True)
    rules_tokens = _estimate_tokens(rules_text)

    learnings_tokens = 0
    if connection_id:
        try:
            from app.services.agent_learning_service import AgentLearningService

            learn_svc = AgentLearningService()
            learnings = await learn_svc.get_learnings(
                db, connection_id, min_confidence=0.6, active_only=True
            )
            if learnings:
                top = sorted(
                    learnings,
                    key=lambda lrn: (lrn.times_confirmed, lrn.confidence),
                    reverse=True,
                )[:15]
                text = "\n".join(f"- [{lrn.category}] {lrn.subject}: {lrn.lesson}" for lrn in top)
                learnings_tokens = _estimate_tokens(text)
        except Exception:
            logger.debug("Cost estimate: learnings lookup failed", exc_info=True)

    overview_tokens = 0
    try:
        from app.models.project_cache import ProjectCache

        result = await db.execute(
            select(ProjectCache.overview_text).where(ProjectCache.project_id == project_id)
        )
        overview = result.scalar_one_or_none()
        if isinstance(overview, str) and overview:
            overview_tokens = _estimate_tokens(overview)
    except Exception:
        logger.debug("Cost estimate: overview lookup failed", exc_info=True)

    max_budget = app_settings.max_history_tokens
    used_context = schema_tokens + rules_tokens + learnings_tokens + overview_tokens
    history_remaining = max(0, max_budget - used_context)

    total_prompt = used_context + history_remaining

    avg_completion = 500
    try:
        cutoff = datetime.now(UTC) - timedelta(days=30)
        stmt = select(
            func.avg(TokenUsage.completion_tokens).label("avg_comp"),
        ).where(
            TokenUsage.user_id == user["user_id"],
            TokenUsage.created_at >= cutoff,
            TokenUsage.completion_tokens > 0,
        )
        row = (await db.execute(stmt)).one()
        if row.avg_comp:
            avg_completion = int(row.avg_comp)
    except Exception:
        logger.debug("Cost estimate: avg completion lookup failed", exc_info=True)

    total_tokens = total_prompt + avg_completion
    utilization = round((used_context / max_budget * 100) if max_budget > 0 else 0, 1)

    project = await _project_svc.get(db, project_id)
    model = (project.agent_llm_model if project else None) or None
    cost = _estimate_cost(model, total_prompt, avg_completion)

    return CostEstimateResponse(
        estimated_prompt_tokens=total_prompt,
        estimated_completion_tokens=avg_completion,
        estimated_total_tokens=total_tokens,
        estimated_cost_usd=cost,
        context_utilization_pct=utilization,
        breakdown=CostEstimateBreakdown(
            schema_context=schema_tokens,
            rules=rules_tokens,
            learnings=learnings_tokens,
            overview=overview_tokens,
            history_budget_remaining=history_remaining,
        ),
    )


class ChatSearchResult(BaseModel):
    message_id: str
    session_id: str
    session_title: str
    content_snippet: str
    sql_query: str | None = None
    created_at: str
    role: str


@router.get("/search", response_model=list[ChatSearchResult])
@limiter.limit("30/minute")
async def search_messages(
    request: Request,
    project_id: str = Query(...),
    q: str = Query(..., min_length=1, max_length=500),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")

    from sqlalchemy import and_, or_, select

    from app.models.chat_session import ChatMessage as ChatMessageModel
    from app.models.chat_session import ChatSession

    term = f"%{q}%"
    stmt = (
        select(
            ChatMessageModel.id,
            ChatMessageModel.session_id,
            ChatSession.title,
            ChatMessageModel.content,
            ChatMessageModel.metadata_json,
            ChatMessageModel.created_at,
            ChatMessageModel.role,
        )
        .join(ChatSession, ChatMessageModel.session_id == ChatSession.id)
        .where(
            and_(
                ChatSession.project_id == project_id,
                ChatSession.user_id == user["user_id"],
                or_(
                    ChatMessageModel.content.ilike(term),
                    ChatMessageModel.metadata_json.ilike(term),
                ),
            ),
        )
        .order_by(ChatMessageModel.created_at.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()

    results: list[ChatSearchResult] = []
    for row in rows:
        content = row.content or ""
        snippet = _build_snippet(content, q, 200)

        sql_query = None
        if row.metadata_json:
            try:
                meta = json.loads(row.metadata_json)
                sql_query = meta.get("query")
            except Exception:
                logger.debug("Failed to parse message metadata", exc_info=True)

        results.append(
            ChatSearchResult(
                message_id=row.id,
                session_id=row.session_id,
                session_title=row.title or "Untitled",
                content_snippet=snippet,
                sql_query=sql_query,
                created_at=row.created_at.isoformat() if row.created_at else "",
                role=row.role,
            )
        )
    return results


def _build_snippet(text: str, query: str, max_len: int = 200) -> str:
    lower = text.lower()
    idx = lower.find(query.lower())
    if idx == -1:
        return text[:max_len] + ("..." if len(text) > max_len else "")
    start = max(0, idx - max_len // 3)
    end = min(len(text), idx + len(query) + max_len * 2 // 3)
    snippet = text[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return snippet


class QuerySuggestion(BaseModel):
    text: str
    source: str
    table: str | None = None


@router.get("/suggestions", response_model=list[QuerySuggestion])
@limiter.limit("30/minute")
async def get_suggestions(
    request: Request,
    project_id: str = Query(...),
    connection_id: str = Query(...),
    limit: int = Query(5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")
    suggestions = await _suggestion_engine.get_suggestions(
        db,
        user_id=user["user_id"],
        project_id=project_id,
        connection_id=connection_id,
        limit=limit,
    )
    return [QuerySuggestion(**s) for s in suggestions]


class ChatRequest(BaseModel):
    session_id: str | None = None
    project_id: str
    connection_id: str | None = None
    message: str = Field(max_length=20000)
    preferred_provider: str | None = None
    model: str | None = None
    pipeline_action: Literal["continue", "modify", "retry"] | None = None
    pipeline_run_id: str | None = None
    modification: str | None = Field(None, max_length=5000)


class WsChatMessage(BaseModel):
    """Validated WebSocket chat message."""

    message: str = Field(min_length=1, max_length=20000)
    preferred_provider: str | None = Field(None, max_length=50)
    model: str | None = Field(None, max_length=100)


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
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    title: str
    connection_id: str | None = None
    created_at: datetime | None = None


@router.post("/sessions", response_model=SessionResponse)
@limiter.limit("10/minute")
async def create_session(
    request: Request,
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
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")
    return await _chat_svc.list_sessions(
        db,
        project_id,
        user_id=user["user_id"],
        skip=skip,
        limit=limit,
    )


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
@limiter.limit("30/minute")
async def update_session(
    request: Request,
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
@limiter.limit("10/minute")
async def generate_session_title(
    request: Request,
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
@limiter.limit("10/minute")
async def delete_session(
    request: Request,
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
@limiter.limit("30/minute")
async def submit_feedback(
    request: Request,
    body: FeedbackRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Record user feedback (thumbs up/down) on an assistant message."""
    from sqlalchemy import select
    from sqlalchemy.orm import joinedload

    from app.models.chat_session import ChatMessage as ChatMessageModel

    result = await db.execute(
        select(ChatMessageModel)
        .options(joinedload(ChatMessageModel.session))
        .where(ChatMessageModel.id == body.message_id)
    )
    msg = result.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    if msg.role != "assistant":
        raise HTTPException(status_code=400, detail="Can only rate assistant messages")

    if msg.session and msg.session.project_id:
        await _membership_svc.require_role(
            db,
            msg.session.project_id,
            user["user_id"],
            "viewer",
        )

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
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")

    from sqlalchemy import and_, case, func, select

    from app.models.chat_session import ChatMessage as ChatMessageModel
    from app.models.chat_session import ChatSession

    stmt = (
        select(
            func.count().label("total_rated"),
            func.sum(case((ChatMessageModel.user_rating == 1, 1), else_=0)).label("positive"),
            func.sum(case((ChatMessageModel.user_rating == -1, 1), else_=0)).label("negative"),
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
    limit: int = Query(default=500, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _require_session_owner(db, session_id, user["user_id"])

    from sqlalchemy import select as sa_select

    from app.models.chat_session import ChatMessage as ChatMessageModel

    stmt = (
        sa_select(ChatMessageModel)
        .where(ChatMessageModel.session_id == session_id)
        .order_by(ChatMessageModel.created_at)
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    msgs = result.scalars().all()
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
        for m in msgs
    ]


_RAW_RESULT_ROW_CAP = 500


def _has_rules_changed(tool_call_log: list[dict] | None) -> bool:
    """Return True if any tool call in the log modified rules."""
    if not tool_call_log:
        return False
    return any(tc.get("tool") in ("manage_custom_rules", "manage_rules") for tc in tool_call_log)


def _build_structured_error(exc: Exception) -> dict:
    """Build a structured error payload for SSE error events."""
    if isinstance(exc, LLMError):
        return {
            "error": str(exc),
            "error_type": type(exc).__name__,
            "is_retryable": exc.is_retryable,
            "user_message": exc.user_message,
        }
    return {
        "error": str(exc),
        "error_type": "internal",
        "is_retryable": True,
        "user_message": "An unexpected error occurred. Please try again.",
    }


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
        "rows": [[serialize_value(v) for v in row] for row in (rows or [])[:_RAW_RESULT_ROW_CAP]],
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
        body.project_id[:8],
        session_id[:8],
        (body.connection_id or "none")[:8],
    )

    project = await _project_svc.get(db, body.project_id)
    agent_provider = body.preferred_provider or (project.agent_llm_provider if project else None)
    agent_model = body.model or (project.agent_llm_model if project else None)
    sql_provider = (project.sql_llm_provider if project else None) or agent_provider
    sql_model = (project.sql_llm_model if project else None) or agent_model

    extra: dict = {"session_id": session_id}
    if body.pipeline_action:
        extra["pipeline_action"] = body.pipeline_action
    if body.pipeline_run_id:
        extra["pipeline_run_id"] = body.pipeline_run_id
    if body.modification:
        extra["modification"] = body.modification

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
        extra=extra,
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

    tool_calls_str = json.dumps(result.tool_call_log, default=str) if result.tool_call_log else None

    ask_usage = result.token_usage or {}
    ask_cost = _estimate_cost(
        result.llm_model, ask_usage.get("prompt_tokens", 0), ask_usage.get("completion_tokens", 0)
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
                result.llm_model, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
            ),
        )
    except Exception:
        logger.warning("Failed to record token usage", exc_info=True)

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

    from app.config import settings as app_settings

    limit_err = await agent_limiter.acquire(user["user_id"])
    if limit_err:
        raise HTTPException(status_code=429, detail=limit_err)

    stream_timeout_seconds = app_settings.stream_timeout_seconds

    async def _generate():
        result_holder: list = []
        queue = tracker.subscribe()
        released = False

        stream_extra: dict = {"session_id": session_id}
        if body.pipeline_action:
            stream_extra["pipeline_action"] = body.pipeline_action
        if body.pipeline_run_id:
            stream_extra["pipeline_run_id"] = body.pipeline_run_id
        if body.modification:
            stream_extra["modification"] = body.modification

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
            )
            result_holder.append(res)

        task = asyncio.create_task(_process())

        try:
            wf_id = None
            safety = app_settings.stream_safety_margin_seconds
            loop_deadline = time.monotonic() + stream_timeout_seconds + safety
            while not task.done() or not queue.empty():
                if time.monotonic() > loop_deadline:
                    logger.warning("SSE event loop exceeded safety timeout, breaking")
                    break
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

                pipeline_events = frozenset(
                    {
                        "plan",
                        "stage_start",
                        "stage_result",
                        "stage_validation",
                        "stage_complete",
                        "checkpoint",
                        "stage_retry",
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

            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=stream_timeout_seconds)
            except TimeoutError:
                task.cancel()
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
            except Exception as exc:
                error_payload = _build_structured_error(exc)
                yield f"event: error\ndata: {json.dumps(error_payload, default=str)}\n\n"
                return
            result = result_holder[0] if result_holder else None
            if not result:
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

            from app.models.base import async_session_factory as _stream_session_factory

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
                    },
                    tool_calls_json=tool_calls_str,
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
                "token_usage": s_enriched_usage,
                "response_type": result.response_type,
                "assistant_message_id": assistant_msg.id,
                "user_message_id": user_message_id,
                "rules_changed": _has_rules_changed(result.tool_call_log),
                "insights": result.insights or [],
                "suggested_followups": result.suggested_followups or [],
            }
            yield f"event: result\ndata: {json.dumps(final, default=str)}\n\n"
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
            tracker.unsubscribe(queue)
            if not released:
                released = True
                await agent_limiter.release(user["user_id"])

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

    from sqlalchemy import or_, select

    from app.core.workflow_tracker import tracker
    from app.models.base import async_session_factory
    from app.models.project import Project
    from app.models.project_member import ProjectMember
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

            async with async_session_factory() as db:
                await _chat_svc.add_message(db, session_id, "user", message)
                history = await _chat_svc.get_history_as_messages(db, session_id)

            queue = tracker.subscribe()
            relay_task = asyncio.create_task(_relay_events(queue))

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
                        },
                        tool_calls_json=ws_tool_calls_str,
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
                        "suggested_followups": result.suggested_followups or [],
                    }
                )
            finally:
                if not relay_task.done():
                    relay_task.cancel()
                    try:
                        await relay_task
                    except (asyncio.CancelledError, Exception):
                        pass
                tracker.unsubscribe(queue)
                await agent_limiter.release(user_id)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for project %s", project_id)
    except Exception as e:
        logger.exception("WebSocket error")
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            logger.debug("Failed to send error over WebSocket", exc_info=True)


class ExplainSqlRequest(BaseModel):
    sql: str = Field(max_length=20000)
    db_type: str | None = None
    project_id: str


class ExplainSqlResponse(BaseModel):
    explanation: str
    complexity: str


@router.post("/explain-sql", response_model=ExplainSqlResponse)
@limiter.limit("30/minute")
async def explain_sql(
    request: Request,
    body: ExplainSqlRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, body.project_id, user["user_id"], "viewer")

    complexity = _compute_sql_complexity(body.sql)
    cache_key = hashlib.sha256(body.sql.strip().encode()).hexdigest()

    async with _SQL_EXPLAIN_CACHE_LOCK:
        if cache_key in _SQL_EXPLAIN_CACHE:
            _SQL_EXPLAIN_CACHE.move_to_end(cache_key)
            return _SQL_EXPLAIN_CACHE[cache_key]

    project = await _project_svc.get(db, body.project_id)
    provider = (project.agent_llm_provider if project else None) or None
    model = (project.agent_llm_model if project else None) or None

    from app.llm.base import Message as LLMMessage
    from app.llm.router import LLMRouter

    db_hint = f" (Database: {body.db_type})" if body.db_type else ""
    llm_router = LLMRouter()
    try:
        resp = await llm_router.complete(
            messages=[
                LLMMessage(
                    role="system",
                    content=(
                        "Explain this SQL query in plain English. "
                        "For each clause, explain what it does and why. "
                        "Be concise." + db_hint
                    ),
                ),
                LLMMessage(role="user", content=body.sql),
            ],
            max_tokens=1024,
            temperature=0.2,
            preferred_provider=provider,
            model=model,
        )
        explanation = resp.content.strip()
    except Exception as exc:
        logger.warning("SQL explanation LLM call failed: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to generate explanation") from exc

    result = {"explanation": explanation, "complexity": complexity}

    async with _SQL_EXPLAIN_CACHE_LOCK:
        _SQL_EXPLAIN_CACHE[cache_key] = result
        if len(_SQL_EXPLAIN_CACHE) > _SQL_EXPLAIN_CACHE_MAX:
            _SQL_EXPLAIN_CACHE.popitem(last=False)

    return result


class SummarizeRequest(BaseModel):
    message_id: str
    project_id: str


class SummarizeResponse(BaseModel):
    summary: str


@router.post("/summarize", response_model=SummarizeResponse)
@limiter.limit("20/minute")
async def summarize_message(
    request: Request,
    body: SummarizeRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, body.project_id, user["user_id"], "viewer")

    from sqlalchemy import select
    from sqlalchemy.orm import joinedload

    from app.models.chat_session import ChatMessage as ChatMessageModel

    result = await db.execute(
        select(ChatMessageModel)
        .options(joinedload(ChatMessageModel.session))
        .where(ChatMessageModel.id == body.message_id)
    )
    msg = result.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    if msg.role != "assistant":
        raise HTTPException(status_code=400, detail="Can only summarize assistant messages")

    if msg.session and msg.session.project_id != body.project_id:
        raise HTTPException(status_code=403, detail="Message does not belong to this project")

    question = ""
    answer = msg.content or ""
    data_preview = ""

    if msg.metadata_json:
        try:
            meta = json.loads(msg.metadata_json)
            question = meta.get("question", "")
            raw = meta.get("raw_result")
            if raw and isinstance(raw, dict):
                cols = raw.get("columns", [])
                rows = raw.get("rows", [])[:20]
                if cols and rows:
                    header = " | ".join(str(c) for c in cols)
                    lines = [header]
                    for row in rows:
                        lines.append(" | ".join(str(v) for v in row))
                    data_preview = "\n".join(lines)
        except Exception:
            logger.debug("Failed to build data preview for summary", exc_info=True)

    from app.llm.base import Message as LLMMessage
    from app.llm.router import LLMRouter

    project = await _project_svc.get(db, body.project_id)
    provider = (project.agent_llm_provider if project else None) or None
    model = (project.agent_llm_model if project else None) or None

    prompt_parts = [
        "Write a one-paragraph executive summary of these query results "
        "suitable for sharing in Slack or email. Be specific with numbers.",
    ]
    if question:
        prompt_parts.append(f"\nQuestion: {question}")
    if answer:
        prompt_parts.append(f"\nAnswer: {answer[:2000]}")
    if data_preview:
        prompt_parts.append(f"\nData:\n{data_preview[:3000]}")

    llm_router = LLMRouter()
    try:
        resp = await llm_router.complete(
            messages=[
                LLMMessage(role="system", content="\n".join(prompt_parts)),
                LLMMessage(role="user", content="Summarize."),
            ],
            max_tokens=512,
            temperature=0.3,
            preferred_provider=provider,
            model=model,
        )
        summary = resp.content.strip()
    except Exception as exc:
        logger.warning("Summarize LLM call failed: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to generate summary") from exc

    return {"summary": summary}
