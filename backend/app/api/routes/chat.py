import asyncio
import hashlib
import json
import logging
import time
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

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
from app.services.chat_service import ChatService, SessionBusyError, session_processing_lock
from app.services.connection_service import ConnectionService
from app.services.membership_service import MembershipService
from app.services.project_service import ProjectService
from app.services.rag_feedback_service import RAGFeedbackService

if TYPE_CHECKING:
    from app.connectors.base import ConnectionConfig
from app.services.session_summarizer import SessionSummary, get_session_title, summarize_session
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
_SQL_EXPLAIN_CACHE_LOCK = asyncio.Lock()


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


def _compute_sql_complexity(sql: str) -> str:
    """Thin wrapper — real logic lives in :mod:`cost_estimation_service`."""
    from app.services.cost_estimation_service import compute_sql_complexity

    return compute_sql_complexity(sql)


def _estimate_cost(model: str | None, prompt_tokens: int, completion_tokens: int) -> float | None:
    """Thin wrapper — see :mod:`cost_estimation_service`."""
    from app.services.cost_estimation_service import estimate_cost

    return estimate_cost(model, prompt_tokens, completion_tokens)


def _estimate_tokens(text: str) -> int:
    """Thin wrapper — see :mod:`cost_estimation_service`."""
    from app.services.cost_estimation_service import estimate_tokens

    return estimate_tokens(text, chars_per_token=CHARS_PER_TOKEN)


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
    rotation_imminent: bool = False
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
                # R4-4: canonical ranking (matches prompt compilation + context loader).
                top = sorted(
                    learnings,
                    key=AgentLearningService.priority_score,
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

    static_context = schema_tokens + rules_tokens + learnings_tokens + overview_tokens
    history_budget = app_settings.max_history_tokens
    history_remaining = history_budget

    total_prompt = static_context + history_remaining

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
    combined_budget = static_context + history_budget
    utilization = round((static_context / combined_budget * 100) if combined_budget > 0 else 0, 1)

    project = await _project_svc.get(db, project_id)
    model = (project.agent_llm_model if project else None) or None
    cost = _estimate_cost(model, total_prompt, avg_completion)

    rotation_threshold = app_settings.session_rotation_threshold_pct
    rotation_imminent = (
        app_settings.session_rotation_enabled and utilization >= rotation_threshold - 5
    )

    return CostEstimateResponse(
        estimated_prompt_tokens=total_prompt,
        estimated_completion_tokens=avg_completion,
        estimated_total_tokens=total_tokens,
        estimated_cost_usd=cost,
        context_utilization_pct=utilization,
        rotation_imminent=rotation_imminent,
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

    escaped_q = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    term = f"%{escaped_q}%"
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
    """Thin wrapper — see :mod:`chat_response_builder`."""
    from app.services.chat_response_builder import build_search_snippet

    return build_search_snippet(text, query, max_len=max_len)


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
    steps_used: int = 0
    steps_total: int = 0
    continuation_context: str | None = None
    clarification_data: dict | None = None
    sql_results: list[dict] | None = None


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
    status: str = "idle"
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


class EnsureWelcomeRequest(BaseModel):
    project_id: str
    connection_id: str | None = None


class EnsureWelcomeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    title: str
    connection_id: str | None = None
    created_at: datetime | None = None
    created: bool = False


@router.post("/sessions/ensure-welcome", response_model=EnsureWelcomeResponse)
@limiter.limit("10/minute")
async def ensure_welcome_session(
    request: Request,
    body: EnsureWelcomeRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, body.project_id, user["user_id"], "viewer")
    session, created = await _chat_svc.ensure_welcome_session(
        db,
        body.project_id,
        user_id=user["user_id"],
        connection_id=body.connection_id,
    )
    return EnsureWelcomeResponse(
        id=session.id,
        project_id=session.project_id,
        title=session.title,
        connection_id=session.connection_id,
        created_at=session.created_at,
        created=created,
    )


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
    title: str = Field(..., min_length=1, max_length=255)


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

    await _require_session_owner(db, session_id, user["user_id"])

    from sqlalchemy import select as sa_select

    from app.models.chat_session import ChatMessage as ChatMessageModel

    msg_result = await db.execute(
        sa_select(ChatMessageModel.content)
        .where(
            ChatMessageModel.session_id == session_id,
            ChatMessageModel.role == "user",
        )
        .order_by(ChatMessageModel.created_at)
        .limit(1)
    )
    first_user = msg_result.scalar_one_or_none()
    if not first_user:
        raise HTTPException(status_code=400, detail="No user messages in session")

    session_obj = await _chat_svc.get_session(db, session_id)
    _gt_project_id = session_obj.project_id if session_obj else ""
    wf_id = await tracker.begin(
        "generate_title",
        context={"project_id": _gt_project_id, "user_id": user["user_id"]},
    )
    _gt_error: str | None = None
    try:
        router = LLMRouter()
        async with tracker.step(
            wf_id, "generate_title:llm_call", "Generate session title", span_type="llm_call"
        ):
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
        _gt_error = "LLM call failed, used fallback title"
    finally:
        trace_svc = getattr(request.app.state, "trace_persistence_service", None)
        if trace_svc:
            try:
                await trace_svc.finalize_trace(
                    wf_id,
                    project_id=_gt_project_id,
                    user_id=user["user_id"],
                    question=f"[generate-title] {first_user[:100]}",
                    response_type="generate_title",
                    status="failed" if _gt_error else "completed",
                    error_message=_gt_error,
                )
            except Exception:
                logger.warning("Failed to finalize generate-title trace", exc_info=True)

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

    if msg.user_rating == -1 and msg.metadata_json:
        try:
            import json as _json

            from app.knowledge.learning_analyzer import LearningAnalyzer
            from app.models.base import async_session_factory

            meta = _json.loads(msg.metadata_json)
            query = meta.get("query")
            question = meta.get("question", "")
            exposed_ids_raw = meta.get("exposed_learning_ids") or []
            exposed_ids = [str(x) for x in exposed_ids_raw if isinstance(x, (str, int))]
            session_row = msg.session
            connection_id = getattr(session_row, "connection_id", None) if session_row else None

            if exposed_ids and connection_id:
                async with async_session_factory() as learn_session:
                    await contradict_exposed_learnings_on_negative_feedback(
                        learn_session,
                        connection_id=connection_id,
                        exposed_learning_ids=exposed_ids,
                    )

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

    elif msg.user_rating == 1 and msg.metadata_json:
        try:
            import json as _json

            from app.models.base import async_session_factory

            meta = _json.loads(msg.metadata_json)
            # Re-audit fix: if this message was already auto-credited at
            # validation time, do NOT credit again. apply_learning is not
            # idempotent, so a second pass would double-bump times_applied.
            if not (isinstance(meta, dict) and meta.get("learning_credited_at_validation")):
                exposed_ids_raw = meta.get("exposed_learning_ids") or []
                exposed_ids = [str(x) for x in exposed_ids_raw if isinstance(x, (str, int))]
                session_row = msg.session
                connection_id = getattr(session_row, "connection_id", None) if session_row else None
                if exposed_ids and connection_id:
                    async with async_session_factory() as learn_session:
                        await apply_exposed_learnings_on_positive_feedback(
                            learn_session,
                            connection_id=connection_id,
                            exposed_learning_ids=exposed_ids,
                        )
        except Exception:
            logger.debug("Positive-feedback learning application failed", exc_info=True)

    return {"ok": True, "message_id": body.message_id, "rating": msg.user_rating}


async def apply_exposed_learnings_on_positive_feedback(
    session: AsyncSession,
    *,
    connection_id: str,
    exposed_learning_ids: list[str],
) -> int:
    """Credit learnings that produced a thumbs-up answer as *applied*.

    Symmetric counterpart to
    :func:`contradict_exposed_learnings_on_negative_feedback`. A positive user
    rating is the strongest available "the LLM provably used these lessons and
    they were correct" signal, so we bump ``times_applied`` for every learning
    that was exposed for that message. This is what keeps ``times_applied``
    (and the decay-score / ranking derived from it) a live signal in
    production rather than dead code.

    Returns the number of learnings credited.
    """
    if not exposed_learning_ids or not connection_id:
        return 0

    from sqlalchemy import select as _select

    from app.models.agent_learning import AgentLearning as _AgentLearning
    from app.services.agent_learning_service import AgentLearningService

    try:
        rows = await session.execute(
            _select(_AgentLearning).where(
                _AgentLearning.id.in_(exposed_learning_ids),
                _AgentLearning.connection_id == connection_id,
                _AgentLearning.is_active.is_(True),
            )
        )
        candidates = list(rows.scalars().all())
        svc = AgentLearningService()
        applied = 0
        for lrn in candidates:
            await svc.apply_learning(session, lrn.id)
            applied += 1
        if applied:
            # times_applied feeds _priority_score, so refresh the cached prompt.
            await svc._invalidate_summary(session, connection_id)
        await session.commit()
        return applied
    except Exception:
        logger.debug("Positive-feedback application pass failed (non-critical)", exc_info=True)
        return 0


async def _message_learning_credited(session: AsyncSession, message_id: str) -> bool:
    """True if *message_id* was already credited for its exposed learnings."""
    import json as _json

    from sqlalchemy import select as _select

    from app.models.chat_session import ChatMessage as _ChatMessage

    row = await session.execute(
        _select(_ChatMessage.metadata_json).where(_ChatMessage.id == message_id)
    )
    raw = row.scalar_one_or_none()
    if not raw:
        return False
    try:
        meta = _json.loads(raw)
    except (TypeError, ValueError):
        return False
    return bool(isinstance(meta, dict) and meta.get("learning_credited_at_validation"))


async def _mark_message_learning_credited(session: AsyncSession, message_id: str) -> None:
    """Persist the idempotency flag so the thumbs-up path won't re-credit."""
    import json as _json

    from sqlalchemy import select as _select

    from app.models.chat_session import ChatMessage as _ChatMessage

    row = await session.execute(_select(_ChatMessage).where(_ChatMessage.id == message_id))
    msg = row.scalar_one_or_none()
    if msg is None:
        return
    try:
        meta = _json.loads(msg.metadata_json) if msg.metadata_json else {}
        if not isinstance(meta, dict):
            meta = {}
    except (TypeError, ValueError):
        meta = {}
    meta["learning_credited_at_validation"] = True
    msg.metadata_json = _json.dumps(meta, default=str)
    await session.commit()


async def credit_validated_learnings(
    result: object,
    connection_id: str | None,
    *,
    message_id: str | None = None,
) -> None:
    """R4-2: credit exposed learnings on a *validated, successful* result.

    A user thumbs-up is a rare signal, so ``times_applied`` (and the decay /
    ranking score derived from it) was effectively dead in production. A
    result that completed without error and carried exposed learnings is the
    strongest *automatic* "the LLM provably used these lessons and produced a
    valid answer" signal available. Crediting here keeps ``times_applied``
    live; the R4-3 exposure penalty balances inflation (a learning that is
    exposed but never lands on a successful answer still de-ranks).

    Re-audit fixes:
    * Idempotent per ``message_id`` — once a message is credited at validation
      time a flag is persisted, so the thumbs-up path (and any duplicate
      finalize, e.g. stream + background) cannot double-bump ``times_applied``
      (``apply_learning`` is not idempotent).
    * A result the orchestrator flagged ``suspicious_result`` is never credited
      — that would reward learnings behind a likely-wrong answer.

    Best-effort and isolated in its own session — never blocks or fails the
    chat response.
    """
    from app.config import settings as _settings

    if not _settings.learning_apply_on_validation_enabled:
        return
    if getattr(result, "error", None):
        return
    if getattr(result, "suspicious_result", False):
        return
    exposed_raw = getattr(result, "exposed_learning_ids", None) or []
    exposed_ids = [str(x) for x in exposed_raw if isinstance(x, (str, int))]
    if not exposed_ids or not connection_id:
        return
    try:
        from app.models.base import async_session_factory

        async with async_session_factory() as learn_session:
            if message_id is not None and await _message_learning_credited(
                learn_session, message_id
            ):
                return
            await apply_exposed_learnings_on_positive_feedback(
                learn_session,
                connection_id=connection_id,
                exposed_learning_ids=exposed_ids,
            )
            if message_id is not None:
                await _mark_message_learning_credited(learn_session, message_id)
    except Exception:
        logger.debug("Validation-time learning credit failed (non-critical)", exc_info=True)


async def maybe_auto_investigate(
    result: object,
    *,
    project_id: str | None,
    connection_id: str | None,
    session_id: str | None,
    message_id: str | None,
) -> None:
    """R5-7: auto-route a suspicious SQL result to the investigation agent.

    The investigation ("Wrong Data") subsystem was previously reachable only
    via an explicit user thumbs-down. When the orchestrator's result gate
    exhausts its correction budget and the result still looks wrong, the
    response is flagged ``suspicious_result``; this kicks off a background
    investigation automatically so the root cause is surfaced without waiting
    for the user to complain.

    Best-effort and fully isolated — never blocks or fails the chat response.
    Gated by ``orchestrator_auto_investigate_enabled`` (default off).
    """
    from app.config import settings as _settings

    if not _settings.orchestrator_auto_investigate_enabled:
        return
    if not getattr(result, "suspicious_result", False):
        return
    if not (connection_id and project_id and session_id and message_id):
        return

    original_query = getattr(result, "query", None) or ""
    reason = getattr(result, "suspicious_reason", None) or "Result failed automated quality checks."
    qr = getattr(result, "results", None)
    try:
        result_summary = (
            json.dumps(
                {
                    "row_count": getattr(qr, "row_count", None) if qr else None,
                    "error": getattr(qr, "error", None) if qr else None,
                }
            )[:2000]
            if qr
            else "{}"
        )
    except (TypeError, ValueError):
        result_summary = "{}"

    try:
        from app.api.routes.data_investigations import _run_investigation_background
        from app.models.base import async_session_factory
        from app.services.investigation_service import InvestigationService

        inv_svc = InvestigationService()
        async with async_session_factory() as inv_session:
            investigation = await inv_svc.create_investigation(
                inv_session,
                connection_id=connection_id,
                session_id=session_id,
                trigger_message_id=message_id,
                original_query=original_query,
                original_result_summary=result_summary,
                user_complaint_type="auto_suspicious",
                user_complaint_detail=reason,
            )
            await inv_session.commit()
            investigation_id = investigation.id

        def _on_task_done(t: asyncio.Task[None]) -> None:
            if t.cancelled():
                return
            exc = t.exception()
            if exc:
                logger.warning(
                    "Auto-investigation %s failed: %s", investigation_id, exc, exc_info=True
                )

        task = asyncio.create_task(
            _run_investigation_background(
                investigation_id=investigation_id,
                project_id=project_id,
                connection_id=connection_id,
                original_query=original_query,
                original_result_summary=result_summary,
                user_complaint_type="auto_suspicious",
                user_complaint_detail=reason,
                user_expected_value="",
                problematic_column="",
            )
        )
        task.add_done_callback(_on_task_done)
        logger.info(
            "R5-7: auto-routed suspicious result to investigation %s (session=%s)",
            investigation_id,
            session_id,
        )
    except Exception:
        logger.debug("Auto-investigation routing failed (non-critical)", exc_info=True)


async def contradict_exposed_learnings_on_negative_feedback(
    session: AsyncSession,
    *,
    connection_id: str,
    exposed_learning_ids: list[str],
    cap: int = 3,
) -> int:
    """V4 — vision §7 #6: user feedback overrides prior learnings.

    On thumbs-down for a query, contradict up to ``cap`` of the learnings
    that were exposed to the LLM for that query, ranked by
    ``confidence × max(1, times_applied)`` so the most-influential lessons
    are contradicted first. The cap (default 3) prevents a single bad answer
    from nuking an entire connection's learning corpus.

    Returns the number of learnings actually contradicted.
    """
    if not exposed_learning_ids or not connection_id:
        return 0

    from sqlalchemy import select as _select

    from app.models.agent_learning import AgentLearning as _AgentLearning
    from app.services.agent_learning_service import AgentLearningService

    try:
        rows = await session.execute(
            _select(_AgentLearning).where(
                _AgentLearning.id.in_(exposed_learning_ids),
                _AgentLearning.connection_id == connection_id,
                _AgentLearning.is_active.is_(True),
            )
        )
        candidates = list(rows.scalars().all())
        candidates.sort(
            key=lambda lrn: lrn.confidence * max(1, lrn.times_applied),
            reverse=True,
        )
        svc = AgentLearningService()
        contradicted = 0
        for lrn in candidates[:cap]:
            await svc.contradict_learning(session, lrn.id)
            contradicted += 1
        await session.commit()
        return contradicted
    except Exception:
        logger.debug("V4 contradiction pass failed (non-critical)", exc_info=True)
        return 0


@router.get("/analytics/feedback/{project_id}")
async def get_feedback_analytics(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Return aggregated feedback stats for a project."""
    await _membership_svc.require_role(db, project_id, user["user_id"], "owner")

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

    try:
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
            max_steps=max_steps,
        )
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
        try:
            await _session_lock_cm.__aexit__(type(agent_exc), agent_exc, None)
        except Exception:
            logger.debug("Session lock release failed", exc_info=True)
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
                result.llm_model, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
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
                    total_duration_ms=result.results.execution_time_ms if result.results else None,
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
    try:
        await _session_lock_cm.__aexit__(None, None, None)
    except Exception:
        logger.debug("Session lock release failed", exc_info=True)
    return response


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
        queue = await tracker.subscribe()
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
                asyncio.create_task(
                    _background_finalize(
                        bg_task=task,
                        bg_session_id=session_id,
                        bg_body=body,
                        bg_user_message_id=user_message_id,
                        bg_user_id=user["user_id"],
                        bg_request_app=request.app,
                    )
                )
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

            async with async_session_factory() as db:
                ws_user_msg = await _chat_svc.add_message(db, session_id, "user", message)
                ws_user_message_id = ws_user_msg.id
                history = await _chat_svc.get_history_as_messages(db, session_id)

            queue = await tracker.subscribe()
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
                    # R5-5: the HTTP/stream paths thread session_id through ``extra``
                    # so session-scoped features (pipeline state, continuation,
                    # session notes) work; the WS path silently omitted it.
                    extra={"session_id": session_id},
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
    _es_wf_id = await tracker.begin(
        "explain_sql",
        context={"project_id": body.project_id, "user_id": user["user_id"]},
    )
    _es_error: str | None = None
    try:
        async with tracker.step(
            _es_wf_id, "explain_sql:llm_call", "Explain SQL", span_type="llm_call"
        ):
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
        _es_error = str(exc)
        logger.warning("SQL explanation LLM call failed: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to generate explanation") from exc
    finally:
        trace_svc = getattr(request.app.state, "trace_persistence_service", None)
        if trace_svc:
            try:
                await trace_svc.finalize_trace(
                    _es_wf_id,
                    project_id=body.project_id,
                    user_id=user["user_id"],
                    question=f"[explain-sql] {body.sql[:100]}",
                    response_type="explain_sql",
                    status="failed" if _es_error else "completed",
                    error_message=_es_error,
                )
            except Exception:
                logger.warning("Failed to finalize explain-sql trace", exc_info=True)

    result = {"explanation": explanation, "complexity": complexity}

    async with _SQL_EXPLAIN_CACHE_LOCK:
        from app.config import settings as _settings

        _SQL_EXPLAIN_CACHE[cache_key] = result
        while len(_SQL_EXPLAIN_CACHE) > _settings.chat_sql_explain_cache_max:
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
    _sm_wf_id = await tracker.begin(
        "summarize",
        context={"project_id": body.project_id, "user_id": user["user_id"]},
    )
    _sm_error: str | None = None
    try:
        async with tracker.step(
            _sm_wf_id, "summarize:llm_call", "Summarize message", span_type="llm_call"
        ):
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
        _sm_error = str(exc)
        logger.warning("Summarize LLM call failed: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to generate summary") from exc
    finally:
        trace_svc = getattr(request.app.state, "trace_persistence_service", None)
        if trace_svc:
            try:
                await trace_svc.finalize_trace(
                    _sm_wf_id,
                    project_id=body.project_id,
                    user_id=user["user_id"],
                    question=f"[summarize] {question[:100]}",
                    response_type="summarize",
                    status="failed" if _sm_error else "completed",
                    error_message=_sm_error,
                )
            except Exception:
                logger.warning("Failed to finalize summarize trace", exc_info=True)

    return {"summary": summary}
