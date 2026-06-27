"""Feedback endpoints + learning credit/contradiction helpers.

Extracted from the ``chat.py`` god-file (T-ARCH-1). The transports in
``chat.py`` import :func:`credit_validated_learnings` and
:func:`maybe_auto_investigate` from here.
"""

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.rate_limit import limiter
from app.services.membership_service import MembershipService

logger = logging.getLogger(__name__)

router = APIRouter()
_membership_svc = MembershipService()


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
    Gated by ``orchestrator_auto_investigate_enabled``.
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
        from app.services.sync_budget import resolve_owner_user_id
        from app.services.usage_service import UsageService

        # The auto-investigation is system-driven (no human in the loop), so its
        # LLM spend / concurrency / verdict notification are attributed to the
        # project owner — the same owner-attribution the code↔DB sync pipeline
        # uses for its background LLM work.
        async with async_session_factory() as budget_session:
            owner_user_id = await resolve_owner_user_id(budget_session, project_id)
            # Budget gate (vision §7 #5 — graceful degradation): if the owner is
            # already over budget, do NOT spawn an unbilled, unbounded agent run.
            # Owner unknown ⇒ degrade to unenforced rather than block.
            if owner_user_id:
                budget_error = await UsageService().check_token_budget(
                    budget_session, owner_user_id
                )
                if budget_error:
                    logger.info(
                        "R5-7: skipping auto-investigation — owner over budget (project=%s): %s",
                        project_id,
                        budget_error,
                    )
                    return

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
                user_id=owner_user_id,
                trigger_message_id=message_id,
                session_id=session_id,
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
