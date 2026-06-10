"""Utility chat endpoints: cost estimation, search, suggestions, explain, summarize.

Extracted from the ``chat.py`` god-file (T-ARCH-1). These endpoints are
self-contained read/LLM-helper routes that don't touch the agent pipeline.
"""

import asyncio
import hashlib
import json
import logging
from collections import OrderedDict
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.context_budget import CHARS_PER_TOKEN
from app.core.rate_limit import limiter
from app.core.workflow_tracker import tracker
from app.services.membership_service import MembershipService
from app.services.project_service import ProjectService
from app.services.suggestion_engine import SuggestionEngine

logger = logging.getLogger(__name__)

router = APIRouter()
_project_svc = ProjectService()
_membership_svc = MembershipService()
_suggestion_engine = SuggestionEngine()

_SQL_EXPLAIN_CACHE: OrderedDict[str, dict] = OrderedDict()
_SQL_EXPLAIN_CACHE_LOCK = asyncio.Lock()


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


def _build_snippet(text: str, query: str, max_len: int = 200) -> str:
    """Thin wrapper — see :mod:`chat_response_builder`."""
    from app.services.chat_response_builder import build_search_snippet

    return build_search_snippet(text, query, max_len=max_len)


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
