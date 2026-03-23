"""REST routes for backup management (owner only)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.config import settings
from app.core.backup_manager import BackupManager
from app.core.rate_limit import limiter
from app.models.backup_record import BackupRecord

logger = logging.getLogger(__name__)

router = APIRouter()
_mgr = BackupManager()


@router.post("/trigger")
@limiter.limit("3/minute")
async def trigger_backup(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Trigger a manual backup (any authenticated user who owns a project)."""
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


@router.get("/list")
async def list_backups(
    user: dict = Depends(get_current_user),
):
    """List available backups from disk."""
    backups = await _mgr.list_backups()
    return {"backups": backups}


@router.get("/history")
async def backup_history(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """List backup records from the database."""
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
