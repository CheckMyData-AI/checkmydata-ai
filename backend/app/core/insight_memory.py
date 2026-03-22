"""Insight Memory Layer — persistent store for discovered findings.

Stores insights, tracks their lifecycle (active → confirmed/dismissed/resolved),
and provides retrieval for de-duplication and context enrichment.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from app.models.insight_record import InsightRecord, TrustScore

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

VALID_INSIGHT_TYPES = frozenset(
    {
        "anomaly",
        "opportunity",
        "loss",
        "trend",
        "pattern",
        "reconciliation_mismatch",
        "data_quality",
        "observation",
    }
)

VALID_SEVERITIES = frozenset({"critical", "warning", "info", "positive"})
VALID_STATUSES = frozenset(
    {"active", "confirmed", "dismissed", "resolved", "expired", "superseded"}
)

DEDUP_SIMILARITY_THRESHOLD = 0.80


class InsightMemoryService:
    """Manages the lifecycle of insight records."""

    async def store_insight(
        self,
        session: AsyncSession,
        project_id: str,
        insight_type: str,
        title: str,
        description: str,
        *,
        connection_id: str | None = None,
        severity: str = "info",
        evidence: list[dict[str, Any]] | None = None,
        source_metrics: list[str] | None = None,
        source_query: str | None = None,
        recommended_action: str = "",
        expected_impact: str = "",
        confidence: float = 0.5,
        trust_sources: list[str] | None = None,
        trust_validation_method: str = "auto",
        data_freshness_hours: float = 0.0,
        sample_size: int = 0,
    ) -> InsightRecord:
        if insight_type not in VALID_INSIGHT_TYPES:
            raise ValueError(f"Invalid insight_type: {insight_type}")
        if severity not in VALID_SEVERITIES:
            severity = "info"

        existing = await self._find_duplicate(session, project_id, title, description)
        if existing:
            existing.times_surfaced += 1
            existing.confidence = min(1.0, existing.confidence + 0.05)
            if recommended_action and not existing.recommended_action:
                existing.recommended_action = recommended_action
            if expected_impact and not existing.expected_impact:
                existing.expected_impact = expected_impact
            await session.flush()
            return existing

        record = InsightRecord(
            project_id=project_id,
            connection_id=connection_id,
            insight_type=insight_type,
            severity=severity,
            title=title,
            description=description,
            evidence_json=json.dumps(evidence or []),
            source_metrics_json=json.dumps(source_metrics or []),
            source_query=source_query[:4000] if source_query else None,
            recommended_action=recommended_action,
            expected_impact=expected_impact,
            confidence=confidence,
        )
        session.add(record)
        await session.flush()

        trust = TrustScore(
            insight_id=record.id,
            confidence=confidence,
            data_freshness_hours=data_freshness_hours,
            sources_json=json.dumps(trust_sources or []),
            validation_method=trust_validation_method,
            sample_size=sample_size,
        )
        session.add(trust)
        await session.flush()

        return record

    async def get_insights(
        self,
        session: AsyncSession,
        project_id: str,
        *,
        connection_id: str | None = None,
        insight_type: str | None = None,
        severity: str | None = None,
        status: str = "active",
        min_confidence: float = 0.0,
        limit: int = 50,
        offset: int = 0,
    ) -> list[InsightRecord]:
        stmt = select(InsightRecord).where(InsightRecord.project_id == project_id)
        if connection_id:
            stmt = stmt.where(InsightRecord.connection_id == connection_id)
        if insight_type:
            stmt = stmt.where(InsightRecord.insight_type == insight_type)
        if severity:
            stmt = stmt.where(InsightRecord.severity == severity)
        if status:
            stmt = stmt.where(InsightRecord.status == status)
        if min_confidence > 0:
            stmt = stmt.where(InsightRecord.confidence >= min_confidence)
        stmt = stmt.order_by(
            InsightRecord.severity.desc(),
            InsightRecord.confidence.desc(),
            InsightRecord.detected_at.desc(),
        )
        stmt = stmt.offset(offset).limit(limit)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_insight_by_id(
        self,
        session: AsyncSession,
        insight_id: str,
    ) -> InsightRecord | None:
        return await session.get(InsightRecord, insight_id)

    async def get_trust_score(
        self,
        session: AsyncSession,
        insight_id: str,
    ) -> TrustScore | None:
        result = await session.execute(
            select(TrustScore).where(TrustScore.insight_id == insight_id)
        )
        return result.scalar_one_or_none()

    async def confirm_insight(
        self,
        session: AsyncSession,
        insight_id: str,
        feedback: str = "",
    ) -> InsightRecord | None:
        record = await session.get(InsightRecord, insight_id)
        if not record:
            return None
        record.status = "confirmed"
        record.user_verdict = "confirmed"
        record.user_feedback = feedback or record.user_feedback
        record.times_confirmed += 1
        record.confidence = min(1.0, record.confidence + 0.15)
        record.confirmed_at = datetime.now(UTC)
        await session.flush()
        return record

    async def dismiss_insight(
        self,
        session: AsyncSession,
        insight_id: str,
        feedback: str = "",
    ) -> InsightRecord | None:
        record = await session.get(InsightRecord, insight_id)
        if not record:
            return None
        record.status = "dismissed"
        record.user_verdict = "dismissed"
        record.user_feedback = feedback or record.user_feedback
        record.times_dismissed += 1
        record.confidence = max(0.0, record.confidence - 0.2)
        await session.flush()
        return record

    async def resolve_insight(
        self,
        session: AsyncSession,
        insight_id: str,
        feedback: str = "",
    ) -> InsightRecord | None:
        record = await session.get(InsightRecord, insight_id)
        if not record:
            return None
        record.status = "resolved"
        record.user_verdict = "resolved"
        record.user_feedback = feedback or record.user_feedback
        record.resolved_at = datetime.now(UTC)
        await session.flush()
        return record

    async def count_insights(
        self,
        session: AsyncSession,
        project_id: str,
        status: str = "active",
    ) -> int:
        stmt = select(func.count(InsightRecord.id)).where(
            InsightRecord.project_id == project_id,
        )
        if status:
            stmt = stmt.where(InsightRecord.status == status)
        result = await session.execute(stmt)
        return result.scalar_one()

    async def get_summary(
        self,
        session: AsyncSession,
        project_id: str,
    ) -> dict[str, Any]:
        """Return a summary of insights for a project."""
        type_counts = await session.execute(
            select(InsightRecord.insight_type, func.count(InsightRecord.id))
            .where(
                InsightRecord.project_id == project_id,
                InsightRecord.status == "active",
            )
            .group_by(InsightRecord.insight_type)
        )
        severity_counts = await session.execute(
            select(InsightRecord.severity, func.count(InsightRecord.id))
            .where(
                InsightRecord.project_id == project_id,
                InsightRecord.status == "active",
            )
            .group_by(InsightRecord.severity)
        )
        total = await self.count_insights(session, project_id)

        return {
            "total_active": total,
            "by_type": {t: c for t, c in type_counts.all()},
            "by_severity": {s: c for s, c in severity_counts.all()},
        }

    async def decay_stale_insights(
        self,
        session: AsyncSession,
        days_threshold: int = 30,
    ) -> int:
        """Reduce confidence of old unconfirmed insights and expire them if too low."""
        cutoff = datetime.now(UTC) - timedelta(days=days_threshold)
        result = await session.execute(
            select(InsightRecord).where(
                InsightRecord.status == "active",
                InsightRecord.user_verdict.is_(None),
                InsightRecord.updated_at < cutoff,
            )
        )
        stale = result.scalars().all()
        affected = 0
        for record in stale:
            record.confidence = max(0.0, round(record.confidence - 0.05, 4))
            affected += 1
            if record.confidence < 0.15:
                record.status = "expired"
        await session.flush()
        return affected

    async def _find_duplicate(
        self,
        session: AsyncSession,
        project_id: str,
        title: str,
        description: str,
    ) -> InsightRecord | None:
        """Check if a similar insight already exists."""
        result = await session.execute(
            select(InsightRecord)
            .where(
                InsightRecord.project_id == project_id,
                InsightRecord.status == "active",
            )
            .order_by(InsightRecord.detected_at.desc())
            .limit(100)
        )
        candidates = result.scalars().all()
        title_lower = title.strip().lower()

        for candidate in candidates:
            ratio = SequenceMatcher(None, candidate.title.strip().lower(), title_lower).ratio()
            if ratio >= DEDUP_SIMILARITY_THRESHOLD:
                return candidate
        return None
