"""REST routes for backup management (admin-only).

Access control: all endpoints require the caller's email to be listed in
``settings.admin_emails`` (env var ``ADMIN_EMAILS``). Non-admin authenticated
users receive ``403 Forbidden``.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin
from app.config import settings
from app.core.backup_manager import BackupManager
from app.core.rate_limit import limiter
from app.models.backup_record import BackupRecord


class BackupTriggerResponse(BaseModel):
    ok: bool = True
    timestamp: str
    size_bytes: int
    errors: list[str] = []


class BackupListResponse(BaseModel):
    backups: list[dict[str, Any]]


class BackupHistoryRecord(BaseModel):
    id: str
    created_at: str | None = None
    reason: str
    status: str
    size_bytes: int | None = None
    error_message: str | None = None


class BackupHistoryResponse(BaseModel):
    records: list[BackupHistoryRecord]

logger = logging.getLogger(__name__)

router = APIRouter()
_mgr = BackupManager()


@router.post("/trigger", response_model=BackupTriggerResponse)
@limiter.limit("3/minute")
async def trigger_backup(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
):
    """Trigger a manual backup. Admin-only."""
    if not settings.backup_enabled:
        raise HTTPException(status_code=400, detail="Backups are disabled")

    try:
        manifest = await _mgr.run_backup("manual")

        record = BackupRecord(
            reason="manual",
            status="success",
            size_bytes=manifest.get("total_size_bytes", 0),
            manifest_json=manifest,
            backup_path=manifest.get("backup_path"),
        )
        db.add(record)
        await db.commit()

        return {
            "ok": True,
            "timestamp": manifest["timestamp"],
            "size_bytes": manifest.get("total_size_bytes", 0),
            "errors": manifest.get("errors", []),
        }
    except Exception as e:
        record = BackupRecord(
            reason="manual",
            status="failed",
            error_message=str(e),
        )
        db.add(record)
        await db.commit()
        logger.error("Backup failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500, detail="Backup failed. Check server logs for details."
        ) from e


@router.get("/list", response_model=BackupListResponse)
async def list_backups(
    user: dict = Depends(require_admin),
):
    """List available backups from disk. Admin-only."""
    backups = await _mgr.list_backups()
    return {"backups": backups}


@router.get("/history", response_model=BackupHistoryResponse)
async def backup_history(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
):
    """List backup records from the database. Admin-only."""
    result = await db.execute(
        select(BackupRecord).order_by(BackupRecord.created_at.desc()).limit(50)
    )
    records = result.scalars().all()
    return {
        "records": [
            {
                "id": r.id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "reason": r.reason,
                "status": r.status,
                "size_bytes": r.size_bytes,
                "error_message": r.error_message,
            }
            for r in records
        ]
    }
