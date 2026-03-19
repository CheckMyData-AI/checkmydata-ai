"""CRUD, deduplication, confidence management, and prompt compilation for agent learnings."""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, select, update

from app.models.agent_learning import AgentLearning, AgentLearningSummary, _lesson_hash

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

VALID_CATEGORIES = frozenset(
    {
        "table_preference",
        "column_usage",
        "data_format",
        "query_pattern",
        "schema_gotcha",
        "performance_hint",
    }
)

CATEGORY_LABELS = {
    "table_preference": "Table Preferences",
    "column_usage": "Column Usage",
    "data_format": "Data Formats",
    "query_pattern": "Query Patterns",
    "schema_gotcha": "Schema Gotchas",
    "performance_hint": "Performance Hints",
}

SIMILARITY_THRESHOLD = 0.75


class AgentLearningService:
    """Manages the lifecycle of per-connection agent learnings."""

    # ------------------------------------------------------------------
    # Create / Upsert
    # ------------------------------------------------------------------

    async def create_learning(
        self,
        session: AsyncSession,
        connection_id: str,
        category: str,
        subject: str,
        lesson: str,
        confidence: float = 0.6,
        source_query: str | None = None,
        source_error: str | None = None,
    ) -> AgentLearning:
        if category not in VALID_CATEGORIES:
            raise ValueError(f"Invalid category: {category}")

        lhash = _lesson_hash(lesson)

        existing = await session.execute(
            select(AgentLearning).where(
                AgentLearning.connection_id == connection_id,
                AgentLearning.category == category,
                AgentLearning.subject == subject,
                AgentLearning.lesson_hash == lhash,
            )
        )
        entry = existing.scalar_one_or_none()

        if entry:
            entry.times_confirmed += 1
            entry.confidence = min(1.0, entry.confidence + 0.1)
            entry.is_active = True
            entry.updated_at = datetime.now(UTC)
            await session.flush()
            return entry

        similar = await self.find_similar(session, connection_id, category, subject, lesson)
        if similar:
            similar.times_confirmed += 1
            similar.confidence = min(1.0, similar.confidence + 0.1)
            if len(lesson) > len(similar.lesson):
                similar.lesson = lesson
                similar.lesson_hash = lhash
            similar.is_active = True
            similar.updated_at = datetime.now(UTC)
            await session.flush()
            return similar

        entry = AgentLearning(
            connection_id=connection_id,
            category=category,
            subject=subject,
            lesson=lesson,
            lesson_hash=lhash,
            confidence=confidence,
            source_query=source_query[:2000] if source_query else None,
            source_error=source_error[:1000] if source_error else None,
        )
        session.add(entry)
        await session.flush()
        await self._invalidate_summary(session, connection_id)
        return entry

    # ------------------------------------------------------------------
    # Find similar (fuzzy dedup)
    # ------------------------------------------------------------------

    async def find_similar(
        self,
        session: AsyncSession,
        connection_id: str,
        category: str,
        subject: str,
        lesson_text: str,
    ) -> AgentLearning | None:
        result = await session.execute(
            select(AgentLearning).where(
                AgentLearning.connection_id == connection_id,
                AgentLearning.category == category,
                AgentLearning.subject == subject,
                AgentLearning.is_active.is_(True),
            )
        )
        candidates = result.scalars().all()

        lesson_lower = lesson_text.strip().lower()
        best_match: AgentLearning | None = None
        best_ratio = 0.0

        for c in candidates:
            ratio = SequenceMatcher(None, c.lesson.strip().lower(), lesson_lower).ratio()
            if ratio >= SIMILARITY_THRESHOLD and ratio > best_ratio:
                best_ratio = ratio
                best_match = c

        return best_match

    # ------------------------------------------------------------------
    # Confirm / Apply / Deactivate
    # ------------------------------------------------------------------

    async def confirm_learning(
        self,
        session: AsyncSession,
        learning_id: str,
    ) -> AgentLearning | None:
        entry = await session.get(AgentLearning, learning_id)
        if not entry:
            return None
        entry.times_confirmed += 1
        entry.confidence = min(1.0, entry.confidence + 0.1)
        entry.updated_at = datetime.now(UTC)
        await session.flush()
        return entry

    async def apply_learning(
        self,
        session: AsyncSession,
        learning_id: str,
    ) -> None:
        await session.execute(
            update(AgentLearning)
            .where(AgentLearning.id == learning_id)
            .values(times_applied=AgentLearning.times_applied + 1)
        )

    async def deactivate_learning(
        self,
        session: AsyncSession,
        learning_id: str,
    ) -> AgentLearning | None:
        entry = await session.get(AgentLearning, learning_id)
        if not entry:
            return None
        entry.is_active = False
        entry.updated_at = datetime.now(UTC)
        await session.flush()
        await self._invalidate_summary(session, entry.connection_id)
        return entry

    async def contradict_learning(
        self,
        session: AsyncSession,
        learning_id: str,
    ) -> AgentLearning | None:
        entry = await session.get(AgentLearning, learning_id)
        if not entry:
            return None
        entry.confidence = max(0.0, entry.confidence - 0.3)
        if entry.confidence < 0.1:
            entry.is_active = False
        entry.updated_at = datetime.now(UTC)
        await session.flush()
        return entry

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    async def get_learnings(
        self,
        session: AsyncSession,
        connection_id: str,
        min_confidence: float = 0.3,
        active_only: bool = True,
    ) -> list[AgentLearning]:
        stmt = select(AgentLearning).where(
            AgentLearning.connection_id == connection_id,
            AgentLearning.confidence >= min_confidence,
        )
        if active_only:
            stmt = stmt.where(AgentLearning.is_active.is_(True))
        stmt = stmt.order_by(
            AgentLearning.confidence.desc(),
            AgentLearning.times_confirmed.desc(),
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_learnings_for_table(
        self,
        session: AsyncSession,
        connection_id: str,
        table_name: str,
    ) -> list[AgentLearning]:
        tbl_lower = table_name.lower()
        result = await session.execute(
            select(AgentLearning).where(
                AgentLearning.connection_id == connection_id,
                AgentLearning.is_active.is_(True),
                AgentLearning.confidence >= 0.3,
            )
        )
        all_learnings = result.scalars().all()
        return [
            lrn
            for lrn in all_learnings
            if tbl_lower in lrn.subject.lower() or tbl_lower in lrn.lesson.lower()
        ]

    async def get_learning_by_id(
        self,
        session: AsyncSession,
        learning_id: str,
    ) -> AgentLearning | None:
        return await session.get(AgentLearning, learning_id)

    async def has_learnings(
        self,
        session: AsyncSession,
        connection_id: str,
    ) -> bool:
        result = await session.execute(
            select(AgentLearning.id)
            .where(
                AgentLearning.connection_id == connection_id,
                AgentLearning.is_active.is_(True),
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def count_learnings(
        self,
        session: AsyncSession,
        connection_id: str,
    ) -> int:
        result = await session.execute(
            select(func.count(AgentLearning.id)).where(
                AgentLearning.connection_id == connection_id,
                AgentLearning.is_active.is_(True),
            )
        )
        return result.scalar_one()

    # ------------------------------------------------------------------
    # Update / Delete
    # ------------------------------------------------------------------

    async def update_learning(
        self,
        session: AsyncSession,
        learning_id: str,
        **kwargs: str | float | bool,
    ) -> AgentLearning | None:
        entry = await session.get(AgentLearning, learning_id)
        if not entry:
            return None
        for key, value in kwargs.items():
            if key == "lesson" and isinstance(value, str):
                setattr(entry, "lesson", value)
                entry.lesson_hash = _lesson_hash(value)
            elif hasattr(entry, key) and key not in ("id", "connection_id", "created_at"):
                setattr(entry, key, value)
        entry.updated_at = datetime.now(UTC)
        await session.flush()
        await self._invalidate_summary(session, entry.connection_id)
        return entry

    async def delete_learning(
        self,
        session: AsyncSession,
        learning_id: str,
    ) -> bool:
        entry = await session.get(AgentLearning, learning_id)
        if not entry:
            return False
        connection_id = entry.connection_id
        await session.delete(entry)
        await session.flush()
        await self._invalidate_summary(session, connection_id)
        return True

    async def delete_all(
        self,
        session: AsyncSession,
        connection_id: str,
    ) -> int:
        result = await session.execute(
            select(AgentLearning).where(AgentLearning.connection_id == connection_id)
        )
        entries = result.scalars().all()
        count = len(entries)
        if count:
            await session.execute(
                delete(AgentLearning).where(AgentLearning.connection_id == connection_id)
            )
            await session.execute(
                delete(AgentLearningSummary).where(
                    AgentLearningSummary.connection_id == connection_id
                )
            )
            await session.flush()
        return count

    # ------------------------------------------------------------------
    # Prompt compilation
    # ------------------------------------------------------------------

    async def compile_prompt(
        self,
        session: AsyncSession,
        connection_id: str,
    ) -> str:
        learnings = await self.get_learnings(
            session, connection_id, min_confidence=0.5, active_only=True
        )
        if not learnings:
            return ""

        by_category: dict[str, list[AgentLearning]] = {}
        for lrn in learnings:
            by_category.setdefault(lrn.category, []).append(lrn)

        parts: list[str] = ["AGENT LEARNINGS (from previous interactions with this database):\n"]

        for cat in [
            "table_preference",
            "column_usage",
            "data_format",
            "query_pattern",
            "schema_gotcha",
            "performance_hint",
        ]:
            items = by_category.get(cat)
            if not items:
                continue
            label = CATEGORY_LABELS.get(cat, cat)
            parts.append(f"### {label}")
            for lrn in items[:10]:
                conf_pct = int(lrn.confidence * 100)
                confirmed = f", {lrn.times_confirmed}x confirmed" if lrn.times_confirmed > 1 else ""
                parts.append(f"- {lrn.lesson} [{conf_pct}% confidence{confirmed}]")
            parts.append("")

        prompt = "\n".join(parts)

        category_counts = Counter(lrn.category for lrn in learnings)

        summary_result = await session.execute(
            select(AgentLearningSummary).where(AgentLearningSummary.connection_id == connection_id)
        )
        summary = summary_result.scalar_one_or_none()

        if summary:
            summary.total_lessons = len(learnings)
            summary.lessons_by_category_json = json.dumps(dict(category_counts))
            summary.compiled_prompt = prompt
            summary.last_compiled_at = datetime.now(UTC)
        else:
            summary = AgentLearningSummary(
                connection_id=connection_id,
                total_lessons=len(learnings),
                lessons_by_category_json=json.dumps(dict(category_counts)),
                compiled_prompt=prompt,
                last_compiled_at=datetime.now(UTC),
            )
            session.add(summary)

        await session.flush()
        return prompt

    async def get_or_compile_summary(
        self,
        session: AsyncSession,
        connection_id: str,
    ) -> str:
        result = await session.execute(
            select(AgentLearningSummary).where(AgentLearningSummary.connection_id == connection_id)
        )
        summary = result.scalar_one_or_none()

        if summary and summary.compiled_prompt:
            return summary.compiled_prompt

        return await self.compile_prompt(session, connection_id)

    async def get_summary(
        self,
        session: AsyncSession,
        connection_id: str,
    ) -> AgentLearningSummary | None:
        result = await session.execute(
            select(AgentLearningSummary).where(AgentLearningSummary.connection_id == connection_id)
        )
        return result.scalar_one_or_none()

    async def get_status(
        self,
        session: AsyncSession,
        connection_id: str,
    ) -> dict:
        count = await self.count_learnings(session, connection_id)
        summary = await self.get_summary(session, connection_id)

        cat_counts: dict[str, int] = {}
        if count > 0:
            result = await session.execute(
                select(AgentLearning.category, func.count(AgentLearning.id))
                .where(
                    AgentLearning.connection_id == connection_id,
                    AgentLearning.is_active.is_(True),
                )
                .group_by(AgentLearning.category)
            )
            for cat, cnt in result.all():
                cat_counts[cat] = cnt

        return {
            "has_learnings": count > 0,
            "total_active": count,
            "categories": cat_counts,
            "last_compiled_at": (
                summary.last_compiled_at.isoformat()
                if summary and summary.last_compiled_at
                else None
            ),
        }

    # ------------------------------------------------------------------
    # Confidence Decay
    # ------------------------------------------------------------------

    async def decay_stale_learnings(self, session: AsyncSession) -> int:
        """Reduce confidence of stale learnings and deactivate very low ones.

        Called periodically (e.g. daily).  Learnings not updated in >30 days
        lose 0.02 confidence.  Those below 0.2 for >30 days are deactivated.
        Returns the number of affected rows.
        """
        from datetime import timedelta

        cutoff = datetime.now(UTC) - timedelta(days=30)

        stale_result = await session.execute(
            select(AgentLearning).where(
                AgentLearning.is_active.is_(True),
                AgentLearning.updated_at < cutoff,
            )
        )
        stale = stale_result.scalars().all()
        if not stale:
            return 0

        affected_connections: set[str] = set()
        affected = 0

        for lrn in stale:
            lrn.confidence = max(0.0, round(lrn.confidence - 0.02, 4))
            affected += 1
            affected_connections.add(lrn.connection_id)

            if lrn.confidence < 0.2:
                lrn.is_active = False

        await session.flush()

        for conn_id in affected_connections:
            await self._invalidate_summary(session, conn_id)

        return affected

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _invalidate_summary(
        self,
        session: AsyncSession,
        connection_id: str,
    ) -> None:
        result = await session.execute(
            select(AgentLearningSummary).where(AgentLearningSummary.connection_id == connection_id)
        )
        summary = result.scalar_one_or_none()
        if summary:
            summary.compiled_prompt = ""
            summary.last_compiled_at = datetime.now(UTC)
            await session.flush()
