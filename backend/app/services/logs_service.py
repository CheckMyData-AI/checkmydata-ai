"""Query service for request traces and spans (owner-only logs screen)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.request_trace import RequestTrace
from app.models.user import User

logger = logging.getLogger(__name__)


class LogsService:

    async def get_users(
        self,
        db: AsyncSession,
        project_id: str,
        days: int = 30,
    ) -> list[dict[str, Any]]:
        cutoff = datetime.now(UTC) - timedelta(days=days)
        stmt = (
            select(
                RequestTrace.user_id,
                User.display_name,
                User.email,
                User.picture_url,
                func.count(RequestTrace.id).label("request_count"),
                func.max(RequestTrace.created_at).label("last_request_at"),
            )
            .join(User, User.id == RequestTrace.user_id)
            .where(
                RequestTrace.project_id == project_id,
                RequestTrace.created_at >= cutoff,
            )
            .group_by(
                RequestTrace.user_id,
                User.display_name,
                User.email,
                User.picture_url,
            )
            .order_by(func.count(RequestTrace.id).desc())
        )
        rows = (await db.execute(stmt)).all()
        return [
            {
                "user_id": r.user_id,
                "display_name": r.display_name or "",
                "email": r.email or "",
                "picture_url": r.picture_url,
                "request_count": r.request_count,
                "last_request_at": r.last_request_at.isoformat() if r.last_request_at else None,
            }
            for r in rows
        ]

    async def list_requests(
        self,
        db: AsyncSession,
        project_id: str,
        *,
        user_id: str | None = None,
        status: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        base = select(RequestTrace).where(RequestTrace.project_id == project_id)
        count_base = select(func.count(RequestTrace.id)).where(
            RequestTrace.project_id == project_id
        )

        if user_id:
            base = base.where(RequestTrace.user_id == user_id)
            count_base = count_base.where(RequestTrace.user_id == user_id)
        if status:
            base = base.where(RequestTrace.status == status)
            count_base = count_base.where(RequestTrace.status == status)
        if date_from:
            base = base.where(RequestTrace.created_at >= date_from)
            count_base = count_base.where(RequestTrace.created_at >= date_from)
        if date_to:
            base = base.where(RequestTrace.created_at <= date_to)
            count_base = count_base.where(RequestTrace.created_at <= date_to)

        total = (await db.execute(count_base)).scalar_one()

        offset = (page - 1) * page_size
        stmt = (
            base.order_by(RequestTrace.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        rows = (await db.execute(stmt)).scalars().all()

        items = []
        for t in rows:
            items.append({
                "id": t.id,
                "user_id": t.user_id,
                "session_id": t.session_id,
                "workflow_id": t.workflow_id,
                "question": t.question,
                "response_type": t.response_type,
                "status": t.status,
                "error_message": t.error_message,
                "total_duration_ms": t.total_duration_ms,
                "total_llm_calls": t.total_llm_calls,
                "total_db_queries": t.total_db_queries,
                "total_tokens": t.total_tokens,
                "estimated_cost_usd": t.estimated_cost_usd,
                "llm_provider": t.llm_provider,
                "llm_model": t.llm_model,
                "steps_used": t.steps_used,
                "steps_total": t.steps_total,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            })

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def get_trace_detail(
        self,
        db: AsyncSession,
        project_id: str,
        trace_id: str,
    ) -> dict[str, Any] | None:
        stmt = (
            select(RequestTrace)
            .options(selectinload(RequestTrace.spans))
            .where(
                RequestTrace.id == trace_id,
                RequestTrace.project_id == project_id,
            )
        )
        trace = (await db.execute(stmt)).scalar_one_or_none()
        if trace is None:
            return None

        spans = []
        for s in trace.spans:
            spans.append({
                "id": s.id,
                "parent_span_id": s.parent_span_id,
                "span_type": s.span_type,
                "name": s.name,
                "status": s.status,
                "detail": s.detail,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "ended_at": s.ended_at.isoformat() if s.ended_at else None,
                "duration_ms": s.duration_ms,
                "input_preview": s.input_preview,
                "output_preview": s.output_preview,
                "token_usage_json": s.token_usage_json,
                "metadata_json": s.metadata_json,
                "order_index": s.order_index,
            })

        return {
            "trace": {
                "id": trace.id,
                "project_id": trace.project_id,
                "user_id": trace.user_id,
                "session_id": trace.session_id,
                "message_id": trace.message_id,
                "assistant_message_id": trace.assistant_message_id,
                "workflow_id": trace.workflow_id,
                "question": trace.question,
                "response_type": trace.response_type,
                "status": trace.status,
                "error_message": trace.error_message,
                "total_duration_ms": trace.total_duration_ms,
                "total_llm_calls": trace.total_llm_calls,
                "total_db_queries": trace.total_db_queries,
                "total_tokens": trace.total_tokens,
                "estimated_cost_usd": trace.estimated_cost_usd,
                "llm_provider": trace.llm_provider,
                "llm_model": trace.llm_model,
                "steps_used": trace.steps_used,
                "steps_total": trace.steps_total,
                "created_at": trace.created_at.isoformat() if trace.created_at else None,
            },
            "spans": spans,
        }

    async def get_summary(
        self,
        db: AsyncSession,
        project_id: str,
        days: int = 7,
    ) -> dict[str, Any]:
        cutoff = datetime.now(UTC) - timedelta(days=days)
        base_filter = [
            RequestTrace.project_id == project_id,
            RequestTrace.created_at >= cutoff,
        ]

        stmt = select(
            func.count(RequestTrace.id).label("total_requests"),
            func.sum(case((RequestTrace.status == "completed", 1), else_=0)).label(
                "successful"
            ),
            func.sum(case((RequestTrace.status == "failed", 1), else_=0)).label(
                "failed"
            ),
            func.coalesce(func.sum(RequestTrace.total_llm_calls), 0).label(
                "total_llm_calls"
            ),
            func.coalesce(func.sum(RequestTrace.total_db_queries), 0).label(
                "total_db_queries"
            ),
            func.avg(RequestTrace.total_duration_ms).label("avg_duration_ms"),
            func.coalesce(func.sum(RequestTrace.total_tokens), 0).label(
                "total_tokens"
            ),
            func.sum(RequestTrace.estimated_cost_usd).label("total_cost_usd"),
        ).where(*base_filter)
        row = (await db.execute(stmt)).one()

        by_status_stmt = (
            select(
                RequestTrace.status,
                func.count(RequestTrace.id).label("cnt"),
            )
            .where(*base_filter)
            .group_by(RequestTrace.status)
        )
        by_status = {
            r.status: r.cnt for r in (await db.execute(by_status_stmt)).all()
        }

        by_type_stmt = (
            select(
                RequestTrace.response_type,
                func.count(RequestTrace.id).label("cnt"),
            )
            .where(*base_filter)
            .group_by(RequestTrace.response_type)
        )
        by_type = {
            r.response_type: r.cnt for r in (await db.execute(by_type_stmt)).all()
        }

        return {
            "total_requests": row.total_requests or 0,
            "successful": row.successful or 0,
            "failed": row.failed or 0,
            "total_llm_calls": int(row.total_llm_calls or 0),
            "total_db_queries": int(row.total_db_queries or 0),
            "avg_duration_ms": round(float(row.avg_duration_ms or 0), 1),
            "total_tokens": int(row.total_tokens or 0),
            "total_cost_usd": round(float(row.total_cost_usd or 0), 6),
            "by_status": by_status,
            "by_type": by_type,
        }
