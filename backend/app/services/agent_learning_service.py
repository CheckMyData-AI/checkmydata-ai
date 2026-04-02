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
        "pipeline_pattern",
        "data_quality_hint",
        "replan_recovery",
    }
)

CATEGORY_LABELS = {
    "table_preference": "Table Preferences",
    "column_usage": "Column Usage",
    "data_format": "Data Formats",
    "query_pattern": "Query Patterns",
    "schema_gotcha": "Schema Gotchas",
    "performance_hint": "Performance Hints",
    "pipeline_pattern": "Pipeline Patterns",
    "data_quality_hint": "Data Quality Hints",
    "replan_recovery": "Replan Recoveries",
}

SIMILARITY_THRESHOLD = 0.75

MIN_LESSON_LENGTH = 15
MAX_LESSON_LENGTH = 500

SUBJECT_BLOCKLIST = frozenset(
    {
        "columns",
        "tables",
        "information_schema",
        "pg_catalog",
        "pg_stat",
        "unknown",
        "schema",
        "dual",
        "sysdiagrams",
        "sys",
    }
)


def _non_ascii_ratio(text: str) -> float:
    """Return the fraction of characters that are non-ASCII (outside printable ASCII range)."""
    if not text:
        return 0.0
    non_ascii = sum(1 for c in text if ord(c) > 127)
    return non_ascii / len(text)


def validate_learning_quality(subject: str, lesson: str) -> str | None:
    """Return an error message if the learning fails quality checks, else None."""
    if subject.lower() in SUBJECT_BLOCKLIST:
        return f"Subject '{subject}' is in the blocklist"
    if len(lesson.strip()) < MIN_LESSON_LENGTH:
        return f"Lesson too short ({len(lesson.strip())} chars, min {MIN_LESSON_LENGTH})"
    if _non_ascii_ratio(lesson) > 0.5:
        return "Lesson text is mostly non-ASCII (likely raw user question in non-English)"
    return None


def normalize_lesson_text(lesson: str) -> str:
    """Normalize whitespace, capitalize, and enforce max length."""
    text = " ".join(lesson.split())
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    if len(text) > MAX_LESSON_LENGTH:
        text = text[: MAX_LESSON_LENGTH - 1] + "\u2026"
    return text


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

        lesson = normalize_lesson_text(lesson)

        quality_err = validate_learning_quality(subject, lesson)
        if quality_err:
            logger.debug("Rejected learning (quality check): %s — %s", quality_err, lesson[:80])
            raise ValueError(f"Learning quality check failed: {quality_err}")

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

        await self._resolve_conflicts(
            session,
            connection_id,
            category,
            subject,
            lesson,
            confidence,
        )

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
    # Conflict detection
    # ------------------------------------------------------------------

    _CONFLICT_INDICATORS = frozenset(
        {
            "use",
            "prefer",
            "always",
            "never",
            "should",
            "instead",
            "not",
            "avoid",
            "correct",
            "wrong",
        }
    )

    async def _resolve_conflicts(
        self,
        session: AsyncSession,
        connection_id: str,
        category: str,
        subject: str,
        new_lesson: str,
        new_confidence: float,
    ) -> None:
        """Deactivate older conflicting learnings if the new one is stronger."""
        result = await session.execute(
            select(AgentLearning).where(
                AgentLearning.connection_id == connection_id,
                AgentLearning.category == category,
                AgentLearning.subject == subject,
                AgentLearning.is_active.is_(True),
            )
        )
        existing = result.scalars().all()
        if not existing:
            return

        new_lower = new_lesson.strip().lower()
        new_keywords = {w for w in new_lower.split() if w in self._CONFLICT_INDICATORS}
        if not new_keywords:
            return

        for old in existing:
            old_lower = old.lesson.strip().lower()
            similarity = SequenceMatcher(
                None,
                old_lower,
                new_lower,
            ).ratio()

            if similarity >= SIMILARITY_THRESHOLD:
                continue

            old_keywords = {w for w in old_lower.split() if w in self._CONFLICT_INDICATORS}
            shared_action_words = new_keywords & old_keywords
            if not shared_action_words:
                continue

            has_negation_flip = (
                ("not" in new_keywords) != ("not" in old_keywords)
                or ("never" in new_keywords) != ("never" in old_keywords)
                or ("avoid" in new_keywords) != ("avoid" in old_keywords)
            )

            if has_negation_flip and old.confidence <= new_confidence:
                old.is_active = False
                old.updated_at = datetime.now(UTC)
                logger.info(
                    "Deactivated conflicting learning %s "
                    "(superseded by newer, higher-confidence lesson)",
                    old.id,
                )

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
        await self._invalidate_summary(session, entry.connection_id)
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
        await self._invalidate_summary(session, entry.connection_id)
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
        skip_blocklisted: bool = True,
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
        rows = list(result.scalars().all())
        if skip_blocklisted:
            rows = [r for r in rows if r.subject.lower() not in SUBJECT_BLOCKLIST]
        return rows

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
            if lrn.subject.lower() not in SUBJECT_BLOCKLIST
            and (tbl_lower in lrn.subject.lower() or tbl_lower in lrn.lesson.lower())
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
    # Schema Validation
    # ------------------------------------------------------------------

    async def validate_learnings_against_schema(
        self,
        session: AsyncSession,
        connection_id: str,
        known_tables: set[str],
    ) -> dict:
        """Cross-check active learnings against the current DB schema.

        Deactivates learnings whose ``subject`` references a table/column that
        no longer exists in *known_tables* (case-insensitive).  Returns a
        summary dict with counts.
        """
        if not known_tables:
            return {"checked": 0, "deactivated": 0, "valid": 0}

        known_lower = {t.lower() for t in known_tables}

        learnings = await self.get_learnings(
            session, connection_id, min_confidence=0.0, active_only=True,
            skip_blocklisted=False,
        )

        deactivated = 0
        valid = 0
        for lrn in learnings:
            subject_lower = lrn.subject.lower()
            if subject_lower in known_lower or any(subject_lower in t for t in known_lower):
                valid += 1
            else:
                lrn.is_active = False
                lrn.updated_at = datetime.now(UTC)
                deactivated += 1
                logger.info(
                    "Deactivated learning %s: subject '%s' not in current schema",
                    lrn.id,
                    lrn.subject,
                )

        if deactivated:
            await session.flush()
            await self._invalidate_summary(session, connection_id)

        return {
            "checked": len(learnings),
            "deactivated": deactivated,
            "valid": valid,
        }

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

    @staticmethod
    def _priority_score(lrn: AgentLearning) -> float:
        """Composite score for ordering learnings in the prompt.

        Combines confidence (0-1), confirmation count (log-scaled),
        and application count (log-scaled) into a single rank.
        """
        import math as _math

        conf_part = lrn.confidence * 0.4
        confirmed_part = _math.log1p(lrn.times_confirmed) * 0.4
        applied_part = _math.log1p(lrn.times_applied) * 0.2
        return conf_part + confirmed_part + applied_part

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

        learnings.sort(key=self._priority_score, reverse=True)
        learnings = learnings[:30]

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
            "pipeline_pattern",
            "data_quality_hint",
            "replan_recovery",
        ]:
            items = by_category.get(cat)
            if not items:
                continue
            label = CATEGORY_LABELS.get(cat, cat)
            parts.append(f"### {label}")
            for lrn in items[:10]:
                conf_pct = int(lrn.confidence * 100)
                critical = " ★CRITICAL" if lrn.times_confirmed >= 5 else ""
                confirmed = f", {lrn.times_confirmed}x confirmed" if lrn.times_confirmed > 1 else ""
                parts.append(f"- {lrn.lesson} [{conf_pct}% confidence{confirmed}{critical}]")
            parts.append("")

        existing_hashes = {lrn.lesson_hash for lrn in learnings}

        cross_section = await self._get_cross_connection_learnings(
            session,
            connection_id,
            existing_hashes,
        )
        if cross_section:
            parts.append("### From Similar Connections (same project)")
            parts.extend(cross_section)
            parts.append("")

        global_section = await self.promote_global_patterns(
            session,
            connection_id,
            exclude_hashes=existing_hashes,
        )
        if global_section:
            parts.append("### Global Patterns (observed across multiple databases)")
            parts.extend(global_section)
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

    async def _get_cross_connection_learnings(
        self,
        session: AsyncSession,
        connection_id: str,
        exclude_hashes: set[str],
    ) -> list[str]:
        """Get transferable learnings from sibling connections in the same project."""
        from app.models.connection import Connection

        conn_result = await session.execute(
            select(Connection.project_id).where(Connection.id == connection_id)
        )
        project_id = conn_result.scalar_one_or_none()
        if not project_id:
            return []

        sibling_result = await session.execute(
            select(Connection.id).where(
                Connection.project_id == project_id,
                Connection.id != connection_id,
            )
        )
        sibling_ids = [r[0] for r in sibling_result.all()]
        if not sibling_ids:
            return []

        transferable_cats = {"schema_gotcha", "performance_hint"}
        stmt = (
            select(AgentLearning)
            .where(
                AgentLearning.connection_id.in_(sibling_ids),
                AgentLearning.category.in_(transferable_cats),
                AgentLearning.is_active.is_(True),
                AgentLearning.confidence >= 0.6,
            )
            .order_by(AgentLearning.confidence.desc())
            .limit(10)
        )
        result = await session.execute(stmt)
        siblings = result.scalars().all()

        lines: list[str] = []
        for lrn in siblings:
            if lrn.lesson_hash in exclude_hashes:
                continue
            conf_pct = int(lrn.confidence * 100)
            lines.append(f"- [from sibling] {lrn.lesson} [{conf_pct}% confidence]")
        return lines[:8]

    async def get_global_patterns(
        self,
        session: AsyncSession,
        *,
        min_connections: int = 2,
        min_confidence: float = 0.7,
        limit: int = 15,
    ) -> list[dict]:
        """Identify learnings that appear across multiple connections.

        Returns high-confidence patterns that have been independently
        discovered on at least *min_connections* different connections,
        suggesting they are universally applicable (e.g. "amounts are
        stored in cents").
        """
        stmt = (
            select(
                AgentLearning.lesson_hash,
                AgentLearning.category,
                AgentLearning.subject,
                func.max(AgentLearning.lesson).label("lesson"),
                func.max(AgentLearning.confidence).label("max_confidence"),
                func.count(func.distinct(AgentLearning.connection_id)).label("conn_count"),
                func.sum(AgentLearning.times_confirmed).label("total_confirmed"),
            )
            .where(
                AgentLearning.is_active.is_(True),
                AgentLearning.confidence >= min_confidence,
            )
            .group_by(
                AgentLearning.lesson_hash,
                AgentLearning.category,
                AgentLearning.subject,
            )
            .having(
                func.count(func.distinct(AgentLearning.connection_id)) >= min_connections,
            )
            .order_by(
                func.count(func.distinct(AgentLearning.connection_id)).desc(),
                func.max(AgentLearning.confidence).desc(),
            )
            .limit(limit)
        )
        rows = (await session.execute(stmt)).all()

        return [
            {
                "lesson_hash": r.lesson_hash,
                "category": r.category,
                "subject": r.subject,
                "lesson": r.lesson,
                "max_confidence": float(r.max_confidence),
                "connection_count": int(r.conn_count),
                "total_confirmed": int(r.total_confirmed),
            }
            for r in rows
        ]

    async def promote_global_patterns(
        self,
        session: AsyncSession,
        connection_id: str,
        exclude_hashes: set[str] | None = None,
    ) -> list[str]:
        """Format global patterns as prompt lines for a specific connection.

        Returns learnings that appear on 2+ other connections but are not
        yet present on *connection_id*.
        """
        patterns = await self.get_global_patterns(session)
        if not patterns:
            return []

        existing = await session.execute(
            select(AgentLearning.lesson_hash).where(
                AgentLearning.connection_id == connection_id,
                AgentLearning.is_active.is_(True),
            )
        )
        existing_hashes = {r[0] for r in existing.all()}
        if exclude_hashes:
            existing_hashes |= exclude_hashes

        lines: list[str] = []
        for p in patterns:
            if p["lesson_hash"] in existing_hashes:
                continue
            conf_pct = int(p["max_confidence"] * 100)
            lines.append(
                f"- [global pattern, seen on {p['connection_count']} DBs] "
                f"{p['lesson']} [{conf_pct}% confidence]"
            )
        return lines[:5]

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
        lose confidence:
        - -0.05 if never applied (times_applied == 0) — faster cleanup
        - -0.02 if previously applied — slower decay for proven learnings
        Those below 0.2 are deactivated.
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
            penalty = 0.02 if lrn.times_applied > 0 else 0.05
            lrn.confidence = max(0.0, round(lrn.confidence - penalty, 4))
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
