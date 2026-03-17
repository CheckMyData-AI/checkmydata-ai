"""Records which RAG chunks were used in a query and whether it succeeded."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import and_, func, select

from app.models.rag_feedback import RAGFeedback

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class RAGFeedbackService:
    async def record(
        self,
        session: AsyncSession,
        project_id: str,
        rag_sources: list[dict],
        query_succeeded: bool,
        question_snippet: str = "",
        commit_sha: str | None = None,
    ) -> None:
        for src in rag_sources:
            entry = RAGFeedback(
                project_id=project_id,
                chunk_id=src.get("chunk_id", ""),
                source_path=src.get("source_path", ""),
                doc_type=src.get("doc_type", ""),
                distance=src.get("distance"),
                query_succeeded=query_succeeded,
                question_snippet=question_snippet[:200],
                commit_sha=commit_sha or src.get("commit_sha"),
            )
            session.add(entry)
        if rag_sources:
            await session.commit()

    async def get_stats(
        self,
        session: AsyncSession,
        project_id: str,
    ) -> list[dict]:
        """Return per-source_path success rate for the project."""
        stmt = (
            select(
                RAGFeedback.source_path,
                func.count().label("total"),
                func.sum(RAGFeedback.query_succeeded.cast(sa.Integer)).label("successes"),
            )
            .where(and_(RAGFeedback.project_id == project_id))
            .group_by(RAGFeedback.source_path)
            .order_by(func.count().desc())
        )
        result = await session.execute(stmt)
        rows = result.all()
        return [
            {
                "source_path": row.source_path,
                "total": row.total,
                "successes": row.successes or 0,
            }
            for row in rows
        ]
