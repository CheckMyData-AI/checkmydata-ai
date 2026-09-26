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


def _outcome(meta_json: str | None) -> tuple[str | None, dict | None]:
    """What the run reported about itself, beside its lifecycle ``status``.

    ``status`` is the IndexingRun lifecycle (`running`, `completed`, `failed`…); a
    completed daily sync may still be *partial*, and only ``meta_json`` says so
    (`success|partial|failed|skipped` for a daily sync, `ok|partial|failed` for a
    collection). Unreadable metadata is reported as unknown — None — never guessed.
    """
    import json

    try:
        meta = json.loads(meta_json or "{}")
    except ValueError:
        return None, None
    if not isinstance(meta, dict):
        return None, None
    outcome = meta.get("status")
    steps = meta.get("steps")
    return (
        outcome if isinstance(outcome, str) else None,
        steps if isinstance(steps, dict) else None,
    )


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
            outcome, steps = _outcome(r.meta_json)
            # The row contract is pinned by a fixture both suites read (B-28):
            # frontend/src/__tests__/fixtures/sync-history-run.json.
            out.append(
                {
                    "id": r.id,
                    "kind": r.kind,
                    "connection_id": r.connection_id,
                    "status": r.status,
                    "outcome": outcome,
                    "trigger": r.trigger,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                    "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                    "duration_seconds": duration,
                    "error": r.error,
                    "progress_pct": r.progress_pct,
                    "steps": steps,
                }
            )
        return out
