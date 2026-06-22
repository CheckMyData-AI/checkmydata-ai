"""Retention sweeps for the run-event journal and the error catalog."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.error_log import ErrorLog
from app.models.indexing_run import IndexingRunEvent

logger = logging.getLogger(__name__)


class TelemetryRetention:
    async def sweep(
        self,
        db: AsyncSession,
        *,
        ttl_days: int,
        max_per_run: int,
        error_ttl_days: int,
    ) -> dict[str, int]:
        ev_cutoff = datetime.now(UTC) - timedelta(days=ttl_days)
        ev_res: CursorResult = await db.execute(  # type: ignore[assignment]
            delete(IndexingRunEvent).where(IndexingRunEvent.ts < ev_cutoff)
        )

        # Per-run cap: trim the oldest overflow events for runs above the cap.
        run_ids = (await db.execute(select(IndexingRunEvent.run_id).distinct())).scalars().all()
        capped = 0
        for run_id in run_ids:
            ids = (
                (
                    await db.execute(
                        select(IndexingRunEvent.id)
                        .where(IndexingRunEvent.run_id == run_id)
                        .order_by(IndexingRunEvent.ts.desc())
                    )
                )
                .scalars()
                .all()
            )
            overflow = ids[max_per_run:]
            if overflow:
                await db.execute(delete(IndexingRunEvent).where(IndexingRunEvent.id.in_(overflow)))
                capped += len(overflow)

        err_cutoff = datetime.now(UTC) - timedelta(days=error_ttl_days)
        err_res: CursorResult = await db.execute(  # type: ignore[assignment]
            delete(ErrorLog).where(ErrorLog.last_seen_at < err_cutoff)
        )
        await db.flush()

        out = {
            "events_deleted": max(0, int(ev_res.rowcount or 0)) + capped,
            "errors_deleted": max(0, int(err_res.rowcount or 0)),
        }
        if any(out.values()):
            logger.info(
                "Telemetry retention: events=%d errors=%d",
                out["events_deleted"],
                out["errors_deleted"],
            )
        return out
