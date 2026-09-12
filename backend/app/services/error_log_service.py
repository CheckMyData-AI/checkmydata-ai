"""Dedup'd error catalog writer (runs + queries planes)."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.error_log import ErrorLog
from app.models.indexing_run import IndexingRun
from app.models.request_trace import RequestTrace

_DIGITS = re.compile(r"\d+")
_WS = re.compile(r"\s+")


def _skeleton(message: str | None) -> str:
    if not message:
        return ""
    s = _DIGITS.sub("#", message)
    s = _WS.sub(" ", s).strip().lower()
    return s[:200]


def _signature(source: str, kind: str, message: str | None) -> str:
    raw = f"{source}|{kind}|{_skeleton(message)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


class ErrorLogService:
    async def upsert(
        self,
        db: AsyncSession,
        *,
        project_id: str | None,
        source: str,
        kind: str,
        message: str | None,
        failure_kind: str | None = None,
        sample_ref: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> ErrorLog:
        sig = _signature(source, kind, message)
        now = datetime.now(UTC)

        async def _merge(into: ErrorLog) -> ErrorLog:
            into.occurrences += 1
            into.last_seen_at = now
            into.message = message or into.message
            into.sample_ref = sample_ref or into.sample_ref
            into.failure_kind = failure_kind or into.failure_kind
            await db.commit()
            return into

        existing = await self._find(db, project_id, sig)
        if existing is not None:
            return await _merge(existing)
        row = ErrorLog(
            project_id=project_id,
            signature=sig,
            source=source,
            kind=kind,
            failure_kind=failure_kind,
            message=message or "",
            sample_ref=sample_ref,
            first_seen_at=now,
            last_seen_at=now,
            meta_json=json.dumps(meta or {}),
        )
        db.add(row)
        try:
            await db.commit()
        except IntegrityError:
            # DATA-08: read-then-write races the unique index. The loser used to
            # surface a 500 — an error while recording an error — where the outcome
            # the caller asked for is available by re-reading the winner's row. The
            # rollback is mandatory: the session is poisoned otherwise, the same
            # shape `RunCoordinator.start` already uses for this table's sibling.
            await db.rollback()
            winner = await self._find(db, project_id, sig)
            if winner is None:
                raise
            return await _merge(winner)
        return row

    @staticmethod
    async def _find(db: AsyncSession, project_id: str | None, sig: str) -> ErrorLog | None:
        """The row this signature already occupies, if any.

        Matched on `coalesce(project_id, '')` so it finds the same row the unique
        index does. A bare `project_id == None` in SQL is `NULL = NULL`, which is
        never true — the exact asymmetry that made the dedup rule a no-op for
        system-scoped errors in the first place.
        """
        return (
            await db.execute(
                select(ErrorLog).where(
                    func.coalesce(ErrorLog.project_id, "") == (project_id or ""),
                    ErrorLog.signature == sig,
                )
            )
        ).scalar_one_or_none()

    async def upsert_from_run(self, db: AsyncSession, run: IndexingRun) -> ErrorLog:
        return await self.upsert(
            db,
            project_id=run.project_id,
            source="run",
            kind=run.kind,
            message=run.error,
            failure_kind=run.failure_kind,
            sample_ref=run.id,
            meta={"connection_id": run.connection_id},
        )

    async def upsert_validation_failure(
        self,
        db: AsyncSession,
        *,
        project_id: str | None,
        kind: str,
        message: str | None,
        sample_ref: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> ErrorLog:
        """Catalog a data/answer validation failure (``kind`` ∈ data_gate|answer)."""
        return await self.upsert(
            db,
            project_id=project_id,
            source="span",
            kind=kind,
            message=message,
            failure_kind="data_missing",
            sample_ref=sample_ref,
            meta=meta,
        )

    async def upsert_from_trace(self, db: AsyncSession, trace: RequestTrace) -> ErrorLog:
        return await self.upsert(
            db,
            project_id=trace.project_id,
            source="query",
            kind="chat",
            message=trace.error_message,
            failure_kind=getattr(trace, "failure_kind", None),
            sample_ref=trace.id,
            meta={"user_id": trace.user_id, "workflow_id": trace.workflow_id},
        )
