"""CRUD, dedup, and prompt compilation for agent session notes (working memory)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, select

from app.models.session_note import VALID_NOTE_CATEGORIES, SessionNote, _note_hash

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.75

CATEGORY_LABELS = {
    "data_observation": "Data Observations",
    "column_mapping": "Column Mappings",
    "business_logic": "Business Logic",
    "calculation_note": "Calculation Notes",
    "user_preference": "User Preferences",
    "verified_benchmark": "Verified Benchmarks",
}


class SessionNotesService:
    """Manages persistent agent working memory per connection."""

    # ------------------------------------------------------------------
    # Create / Upsert
    # ------------------------------------------------------------------

    async def create_note(
        self,
        session: AsyncSession,
        connection_id: str,
        project_id: str,
        category: str,
        subject: str,
        note: str,
        confidence: float = 0.7,
        source_session_id: str | None = None,
        is_verified: bool = False,
    ) -> SessionNote:
        if category not in VALID_NOTE_CATEGORIES:
            raise ValueError(f"Invalid note category: {category}")

        nhash = _note_hash(note)

        existing = await session.execute(
            select(SessionNote).where(
                SessionNote.connection_id == connection_id,
                SessionNote.category == category,
                SessionNote.subject == subject,
                SessionNote.note_hash == nhash,
            )
        )
        entry = existing.scalar_one_or_none()
        if entry:
            entry.confidence = min(1.0, entry.confidence + 0.1)
            entry.is_active = True
            if is_verified:
                entry.is_verified = True
            entry.updated_at = datetime.now(UTC)
            await session.flush()
            return entry

        similar = await self._find_similar(session, connection_id, category, subject, note)
        if similar:
            similar.confidence = min(1.0, similar.confidence + 0.1)
            if len(note) > len(similar.note):
                similar.note = note
                similar.note_hash = nhash
            similar.is_active = True
            if is_verified:
                similar.is_verified = True
            similar.updated_at = datetime.now(UTC)
            await session.flush()
            return similar

        entry = SessionNote(
            connection_id=connection_id,
            project_id=project_id,
            category=category,
            subject=subject,
            note=note,
            note_hash=nhash,
            confidence=confidence,
            source_session_id=source_session_id,
            is_verified=is_verified,
        )
        session.add(entry)
        await session.flush()
        return entry

    # ------------------------------------------------------------------
    # Fuzzy dedup
    # ------------------------------------------------------------------

    async def _find_similar(
        self,
        session: AsyncSession,
        connection_id: str,
        category: str,
        subject: str,
        note_text: str,
    ) -> SessionNote | None:
        result = await session.execute(
            select(SessionNote).where(
                SessionNote.connection_id == connection_id,
                SessionNote.category == category,
                SessionNote.subject == subject,
                SessionNote.is_active.is_(True),
            )
        )
        candidates = result.scalars().all()
        note_lower = note_text.strip().lower()
        best_match: SessionNote | None = None
        best_ratio = 0.0

        for c in candidates:
            ratio = SequenceMatcher(None, c.note.strip().lower(), note_lower).ratio()
            if ratio >= SIMILARITY_THRESHOLD and ratio > best_ratio:
                best_ratio = ratio
                best_match = c

        return best_match

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    async def get_notes_for_context(
        self,
        session: AsyncSession,
        connection_id: str,
        table_names: list[str] | None = None,
        category: str | None = None,
        min_confidence: float = 0.3,
    ) -> list[SessionNote]:
        stmt = select(SessionNote).where(
            SessionNote.connection_id == connection_id,
            SessionNote.is_active.is_(True),
            SessionNote.confidence >= min_confidence,
        )
        if category:
            stmt = stmt.where(SessionNote.category == category)
        stmt = stmt.order_by(
            SessionNote.confidence.desc(),
            SessionNote.updated_at.desc(),
        )
        result = await session.execute(stmt)
        notes = list(result.scalars().all())

        if table_names:
            lower_tables = {t.lower() for t in table_names}
            filtered = [
                n
                for n in notes
                if n.subject.lower() in lower_tables
                or any(t in n.note.lower() for t in lower_tables)
            ]
            return filtered if filtered else notes[:20]

        return notes

    async def get_note_by_id(
        self,
        session: AsyncSession,
        note_id: str,
    ) -> SessionNote | None:
        return await session.get(SessionNote, note_id)

    async def count_notes(
        self,
        session: AsyncSession,
        connection_id: str,
    ) -> int:
        result = await session.execute(
            select(func.count(SessionNote.id)).where(
                SessionNote.connection_id == connection_id,
                SessionNote.is_active.is_(True),
            )
        )
        return result.scalar_one()

    # ------------------------------------------------------------------
    # Prompt compilation
    # ------------------------------------------------------------------

    async def compile_notes_prompt(
        self,
        session: AsyncSession,
        connection_id: str,
        table_names: list[str] | None = None,
    ) -> str:
        notes = await self.get_notes_for_context(
            session, connection_id, table_names=table_names, min_confidence=0.4
        )
        if not notes:
            return ""

        by_category: dict[str, list[SessionNote]] = {}
        for n in notes:
            by_category.setdefault(n.category, []).append(n)

        parts: list[str] = [
            "AGENT NOTES (observations from previous sessions with this database):\n"
        ]

        for cat in [
            "business_logic",
            "column_mapping",
            "data_observation",
            "calculation_note",
            "verified_benchmark",
            "user_preference",
        ]:
            items = by_category.get(cat)
            if not items:
                continue
            label = CATEGORY_LABELS.get(cat, cat)
            parts.append(f"### {label}")
            for n in items[:10]:
                verified = " [VERIFIED]" if n.is_verified else ""
                conf_pct = int(n.confidence * 100)
                parts.append(f"- [{n.subject}] {n.note} ({conf_pct}%{verified})")
            parts.append("")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Update / Delete
    # ------------------------------------------------------------------

    async def verify_note(
        self,
        session: AsyncSession,
        note_id: str,
    ) -> SessionNote | None:
        entry = await session.get(SessionNote, note_id)
        if not entry:
            return None
        entry.is_verified = True
        entry.confidence = min(1.0, entry.confidence + 0.15)
        entry.updated_at = datetime.now(UTC)
        await session.flush()
        return entry

    async def deactivate_note(
        self,
        session: AsyncSession,
        note_id: str,
    ) -> SessionNote | None:
        entry = await session.get(SessionNote, note_id)
        if not entry:
            return None
        entry.is_active = False
        entry.updated_at = datetime.now(UTC)
        await session.flush()
        return entry

    async def delete_all_for_connection(
        self,
        session: AsyncSession,
        connection_id: str,
    ) -> int:
        result = await session.execute(
            select(func.count(SessionNote.id)).where(SessionNote.connection_id == connection_id)
        )
        count = result.scalar_one()
        if count:
            await session.execute(
                delete(SessionNote).where(SessionNote.connection_id == connection_id)
            )
            await session.flush()
        return count

    async def decay_stale_notes(
        self,
        session: AsyncSession,
        days_threshold: int = 60,
        decay_amount: float = 0.1,
    ) -> int:
        """Reduce confidence of unverified notes inactive for *days_threshold*+ days."""
        from datetime import timedelta

        from sqlalchemy import update

        cutoff = datetime.now(UTC) - timedelta(days=days_threshold)
        result = await session.execute(
            update(SessionNote)
            .where(
                SessionNote.is_active.is_(True),
                SessionNote.is_verified.is_(False),
                SessionNote.updated_at < cutoff,
                SessionNote.confidence > 0.1,
            )
            .values(confidence=func.greatest(0.1, SessionNote.confidence - decay_amount))
        )
        return result.rowcount  # type: ignore[return-value]
