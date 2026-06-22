"""Dedup'd error catalog writer (runs + queries planes)."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.error_log import ErrorLog
from app.models.indexing_run import IndexingRun

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
        existing = (
            await db.execute(
                select(ErrorLog).where(ErrorLog.project_id == project_id, ErrorLog.signature == sig)
            )
        ).scalar_one_or_none()
        now = datetime.now(UTC)
        if existing is not None:
            existing.occurrences += 1
            existing.last_seen_at = now
            existing.message = message or existing.message
            existing.sample_ref = sample_ref or existing.sample_ref
            existing.failure_kind = failure_kind or existing.failure_kind
            await db.commit()
            return existing
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
        await db.commit()
        return row

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
