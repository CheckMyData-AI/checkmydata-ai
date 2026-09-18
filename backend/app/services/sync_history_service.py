"""History of a project's scheduled background runs.

Replaces the legacy KnowledgeSyncRun audit table. Two kinds are listed: the nightly
knowledge sync, and — since PRJ-10 — each analytics connection's collection, which used
to run nightly against a third-party API and appear in no history at all: the only
record was a log line on the worker and the per-period journal, neither of which a
project's owner can open.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.indexing_run import IndexingRun

#: Run kinds this history answers for, newest-first across both.
HISTORY_KINDS: tuple[str, ...] = ("daily_sync", "analytics_collect")


def _aware(dt: datetime) -> datetime:
    """Normalise to UTC-aware (SQLite reads timestamps back naive)."""
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


class SyncHistoryService:
    async def list_for_project(
        self, session: AsyncSession, project_id: str, *, limit: int = 30
    ) -> list[dict]:
        stmt = (
            select(IndexingRun)
            .where(
                IndexingRun.project_id == project_id,
                IndexingRun.kind.in_(HISTORY_KINDS),
            )
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
                    "connection_id": r.connection_id,
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
