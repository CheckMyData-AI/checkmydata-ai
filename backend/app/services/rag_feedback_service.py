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

    async def get_quality_scores(
        self,
        session: AsyncSession,
        project_id: str,
        *,
        min_usages: int = 3,
    ) -> list[dict]:
        """Return quality scores for each source, combining hit rate and avg distance.

        Only includes sources used at least *min_usages* times so that scores
        are statistically meaningful.  The ``quality_score`` is in [0, 1]
        where higher = better.
        """
        stmt = (
            select(
                RAGFeedback.source_path,
                RAGFeedback.doc_type,
                func.count().label("total"),
                func.sum(RAGFeedback.query_succeeded.cast(sa.Integer)).label("successes"),
                func.avg(RAGFeedback.distance).label("avg_distance"),
            )
            .where(RAGFeedback.project_id == project_id)
            .group_by(RAGFeedback.source_path, RAGFeedback.doc_type)
            .having(func.count() >= min_usages)
            .order_by(func.count().desc())
        )
        result = await session.execute(stmt)
        rows = result.all()

        scored: list[dict] = []
        for row in rows:
            success_rate = (row.successes or 0) / max(row.total, 1)
            avg_dist = float(row.avg_distance) if row.avg_distance is not None else 0.5
            relevance = max(0.0, 1.0 - avg_dist)
            quality_score = round(success_rate * 0.6 + relevance * 0.4, 3)
            scored.append({
                "source_path": row.source_path,
                "doc_type": row.doc_type or "",
                "total_usages": row.total,
                "success_rate": round(success_rate, 3),
                "avg_distance": round(avg_dist, 4),
                "quality_score": quality_score,
            })

        scored.sort(key=lambda x: x["quality_score"])
        return scored

    async def get_low_quality_sources(
        self,
        session: AsyncSession,
        project_id: str,
        *,
        threshold: float = 0.3,
        min_usages: int = 3,
    ) -> list[str]:
        """Return source paths with quality score below *threshold*.

        These are candidates for re-indexing with improved chunking or
        doc generation.
        """
        scores = await self.get_quality_scores(
            session, project_id, min_usages=min_usages,
        )
        return [s["source_path"] for s in scores if s["quality_score"] < threshold]
