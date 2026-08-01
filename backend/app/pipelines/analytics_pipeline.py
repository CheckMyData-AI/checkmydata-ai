"""Pipeline plugin for analytics vendor sources (GA4, App Store, Google Play).

"Indexing" an analytics source means *collecting* it: unlike a database there
is no schema to introspect and no query language to send, so the pipeline's
``index`` step runs :class:`~app.services.analytics_collect_service.AnalyticsCollectService`
and the resulting rows in the ``ga4_*`` fact tables are the index. ``get_status``
reads the import journal — the only thing that can tell "collected as zero" from
"never collected".

One class serves every analytics vendor because the behaviour is identical; the
concrete vendor is a property of the *connection*, not of the pipeline, and the
registry maps all three source types onto this class.
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import func, select

from app.llm.base import Tool
from app.pipelines.base import (
    DataSourcePipeline,
    PipelineContext,
    PipelineResult,
    PipelineStatus,
)

logger = logging.getLogger(__name__)

#: How long after the last successful collection a source counts as stale.
#: Collection is daily, so one missed day is noise and two is a problem worth
#: surfacing in the UI.
STALE_AFTER_HOURS = 48


class AnalyticsPipeline(DataSourcePipeline):
    """Collects and reports on one analytics connection."""

    @property
    def source_type(self) -> str:
        """The pipeline family id.

        Not a single ``Connection.source_type`` on purpose: this one pipeline is
        registered for every analytics vendor, and the registry instantiates it
        with no arguments, so it cannot know which of the three it was looked up
        under. Callers that need the vendor read it off the connection.
        """
        return "analytics"

    async def index(self, source_id: str, context: PipelineContext) -> PipelineResult:
        """Run one collection pass for the connection.

        ``PipelineResult.success`` follows the outcome's own honesty rule: a
        ``partial`` run *succeeded* (rows landed) but still carries its errors,
        so a caller that only looks at the flag is never told the run was clean.
        """
        from app.services.analytics_collect_service import AnalyticsCollectService

        try:
            outcome = await AnalyticsCollectService().collect(source_id)
        except Exception as exc:
            logger.exception("Analytics index pipeline failed for %s", source_id[:8])
            return PipelineResult(success=False, error=str(exc))

        return PipelineResult(
            success=outcome.status != "failed",
            items_processed=outcome.rows_written,
            error="; ".join(outcome.errors) or None,
            metadata={
                "status": outcome.status,
                "periods_ok": outcome.periods_ok,
                "periods_empty": outcome.periods_empty,
                "workflow_id": context.workflow_id,
            },
        )

    async def sync_with_code(self, source_id: str, context: PipelineContext) -> PipelineResult:
        """No-op: a vendor report has no code to cross-reference."""
        return PipelineResult(
            success=True, metadata={"message": "No code sync for analytics sources"}
        )

    async def get_status(self, source_id: str) -> PipelineStatus:
        """Summarise the connection's journal: collected at all, and how recently."""
        from app.models.analytics_import import AnalyticsImport
        from app.models.base import async_session_factory

        try:
            async with async_session_factory() as session:
                row = (
                    await session.execute(
                        select(
                            func.count(AnalyticsImport.id),
                            func.max(AnalyticsImport.fetched_at),
                        ).where(
                            AnalyticsImport.connection_id == source_id,
                            AnalyticsImport.status.in_(("ok", "empty")),
                        )
                    )
                ).one()
        except Exception:
            logger.debug("Failed to read analytics pipeline status", exc_info=True)
            return PipelineStatus()

        collected, last_fetched_at = int(row[0] or 0), row[1]
        return PipelineStatus(
            is_indexed=collected > 0,
            # Nothing to sync, so "synced" is vacuously true — reporting False
            # would show a permanent warning for a step that does not exist.
            is_synced=True,
            is_stale=_is_stale(last_fetched_at),
            last_indexed_at=last_fetched_at.isoformat() if last_fetched_at else None,
            items_count=collected,
        )

    def get_agent_tools(self) -> list[Tool]:
        """None here — the AnalyticsAgent owns the analytics tool surface."""
        return []


def _is_stale(last_fetched_at: dt.datetime | None) -> bool:
    """True when the newest successful collection is older than the threshold."""
    if last_fetched_at is None:
        return True
    # SQLite hands back naive datetimes; treat those as UTC rather than crashing
    # on a naive/aware comparison in a status read nobody can act on.
    if last_fetched_at.tzinfo is None:
        last_fetched_at = last_fetched_at.replace(tzinfo=dt.UTC)
    return (dt.datetime.now(dt.UTC) - last_fetched_at) > dt.timedelta(hours=STALE_AFTER_HOURS)
