"""History of daily_sync runs (replaces the legacy KnowledgeSyncRun audit table)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.indexing_run import IndexingRun


def _aware(dt: datetime) -> datetime:
    """Normalise to UTC-aware (SQLite reads timestamps back naive)."""
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


class SyncHistoryService:
    async def list_for_project(
        self, session: AsyncSession, project_id: str, *, limit: int = 30
    ) -> list[dict]:
        stmt = (
            select(IndexingRun)
            .where(IndexingRun.project_id == project_id, IndexingRun.kind == "daily_sync")
            .order_by(IndexingRun.created_at.desc())
            .limit(limit)
        )
        rows = (await session.execute(stmt)).scalars().all()
        out: list[dict] = []
        for r in rows:
            duration = None
            if r.started_at and r.finished_at:
                duration = (_aware(r.finished_at) - _aware(r.started_at)).total_seconds()
            out.append(
                {
                    "id": r.id,
                    "kind": r.kind,
                    "status": r.status,
                    "trigger": r.trigger,
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                    "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                    "duration_seconds": duration,
                    "error": r.error,
                    "progress_pct": r.progress_pct,
                }
            )
        return out
