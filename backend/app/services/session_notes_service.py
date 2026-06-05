"""CRUD, dedup, and prompt compilation for agent session notes (working memory)."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, select

from app.models.session_note import VALID_NOTE_CATEGORIES, SessionNote, _note_hash
from app.services.text_similarity import semantic_best_match

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

        # R4-5: guard the fuzzy merge against opposite-polarity notes
        # ("always filter" vs "never filter") which are textually near-identical
        # — a naive similarity match would merge them and silently overwrite the
        # established fact. Mirror the learning side, which checks
        # ``not lessons_contradict`` (opposite polarity only) before merging; the
        # broader same-polarity divergence is left to ``_reconcile_contradictions``
        # so legitimate refinements ("amount"/"amounts") still merge here.
        from app.services.agent_learning_service import lessons_contradict

        similar = await self._find_similar(session, connection_id, category, subject, note)
        if similar and lessons_contradict(note, similar.note):
            similar = None
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

        # R4-5/R4-6: conflict handling. The fuzzy-dedup above only merges notes
        # that are *similar*; it does nothing about a new observation that
        # conflicts with an existing one for the same subject (e.g. "amounts are
        # stored in cents" vs "amounts are stored in dollars"). Without this,
        # both opposing facts surface in the prompt and the agent has no way to
        # tell which is current. Mirror the learning service: deactivate
        # incumbents the new note supersedes, and — when an incumbent outranks
        # the new note — store the newcomer inactive so the two never both feed
        # the prompt.
        new_is_outranked = await self._reconcile_contradictions(
            session,
            connection_id,
            category,
            subject,
            note,
            new_confidence=confidence,
            new_is_verified=is_verified,
        )

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
            is_active=not new_is_outranked,
        )
        if new_is_outranked:
            entry.deactivated_at = datetime.now(UTC)
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
            select(SessionNote)
            .where(
                SessionNote.connection_id == connection_id,
                SessionNote.category == category,
                SessionNote.subject == subject,
                SessionNote.is_active.is_(True),
            )
            .order_by(SessionNote.updated_at.desc())
            .limit(100)
        )
        candidates = result.scalars().all()
        if not candidates:
            return None
        note_lower = note_text.strip().lower()
        texts = [c.note.strip().lower() for c in candidates]
        match = semantic_best_match(note_lower, texts, threshold=SIMILARITY_THRESHOLD)
        if match is None:
            return None
        idx, _score = match
        return candidates[idx]

    async def _reconcile_contradictions(
        self,
        session: AsyncSession,
        connection_id: str,
        category: str,
        subject: str,
        note_text: str,
        *,
        new_confidence: float,
        new_is_verified: bool,
    ) -> bool:
        """R4-5/R4-6: reconcile active notes that conflict with *note_text*.

        Scopes the scan to the same connection + category + subject and reuses
        the learning service's conflict heuristic. Aligned with the learning
        side (``_reconcile_with_learnings``):

        * conflict detection uses :func:`lessons_conflict`, which catches both
          opposite-polarity contradictions ("always X" vs "never X") *and*
          same-polarity divergence ("use X" vs "use Y") — the note side
          previously only caught the former.
        * tie rule is strict: a new note supersedes an incumbent only when it is
          *strictly* stronger (a verified note outranks an unverified one;
          otherwise strictly higher confidence). A tie keeps the incumbent — so
          a verified or equally-confident incumbent is never displaced.
        * exactly one side stays active: incumbents the new note beats are
          deactivated; if any incumbent outranks the new note, the caller stores
          the new note inactive (returns ``True``). This prevents two
          contradictory notes from both feeding the prompt — the gap the old
          "penalise but still create active" path left open for verified
          incumbents.

        Returns ``True`` when the new note is outranked by an existing one.
        """
        # Lazy import: keeps this module's import graph light and avoids any
        # import-order coupling with the (heavier) learning service.
        from app.services.agent_learning_service import lessons_conflict

        result = await session.execute(
            select(SessionNote).where(
                SessionNote.connection_id == connection_id,
                SessionNote.category == category,
                SessionNote.subject == subject,
                SessionNote.is_active.is_(True),
            )
        )
        incumbents = result.scalars().all()
        if not incumbents:
            return False

        now = datetime.now(UTC)
        new_is_outranked = False
        for inc in incumbents:
            if not lessons_conflict(note_text, inc.note):
                continue
            # Strength ordering: verified beats unverified; within the same
            # verification status a *strictly* higher confidence wins. A tie
            # leaves the incumbent in place (mirrors the learning side).
            new_stronger = (new_is_verified and not inc.is_verified) or (
                new_is_verified == inc.is_verified and new_confidence > inc.confidence
            )
            if new_stronger:
                inc.is_active = False
                inc.deactivated_at = now
                inc.updated_at = now
                logger.info(
                    "session_notes: retired conflicting note %s (subject=%s) "
                    "superseded by strictly stronger note",
                    inc.id,
                    subject,
                )
            else:
                new_is_outranked = True
                logger.info(
                    "session_notes: new note outranked by conflicting note %s "
                    "(subject=%s); storing new note inactive",
                    inc.id,
                    subject,
                )
        await session.flush()
        return new_is_outranked

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
        ).limit(200)
        result = await session.execute(stmt)
        notes = list(result.scalars().all())

        if table_names:
            lower_tables = {t.lower() for t in table_names}
            filtered = [n for n in notes if self._note_mentions_table(n, lower_tables)]
            return filtered if filtered else notes[:20]

        return notes[:50]

    @staticmethod
    def _note_mentions_table(note: SessionNote, lower_tables: set[str]) -> bool:
        """R4-6: word-boundary table match instead of a naive substring scan.

        The old ``any(t in n.note.lower() ...)`` matched a table name anywhere
        inside the note text, so a table called ``users`` would spuriously pull
        in every note that happened to contain the word "users" in prose (or a
        longer identifier like ``power_users``). Matching on a word boundary
        keeps ``order_items`` from matching ``my_order_items`` while still
        catching the table name when it appears as a standalone token.
        """
        if note.subject.lower() in lower_tables:
            return True
        note_lower = note.note.lower()
        return any(re.search(rf"\b{re.escape(t)}\b", note_lower) for t in lower_tables)

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
        deactivate_below: float = 0.2,
    ) -> int:
        """Reduce confidence of unverified notes inactive for *days_threshold*+ days.

        When the post-decay confidence falls below ``deactivate_below`` the note
        is also marked inactive (``is_active = False``) and ``deactivated_at`` is
        set, so it stops surfacing in agent prompts. Mirrors the deactivation
        flow used by :class:`AgentLearningService`.
        """
        from datetime import timedelta

        from sqlalchemy import update

        cutoff = datetime.now(UTC) - timedelta(days=days_threshold)
        decay_result = await session.execute(
            update(SessionNote)
            .where(
                SessionNote.is_active.is_(True),
                SessionNote.is_verified.is_(False),
                SessionNote.updated_at < cutoff,
                SessionNote.confidence > 0.1,
            )
            .values(confidence=func.greatest(0.1, SessionNote.confidence - decay_amount))
        )
        decayed = decay_result.rowcount or 0  # type: ignore[attr-defined]

        await session.execute(
            update(SessionNote)
            .where(
                SessionNote.is_active.is_(True),
                SessionNote.is_verified.is_(False),
                SessionNote.confidence < deactivate_below,
            )
            .values(is_active=False, deactivated_at=datetime.now(UTC))
        )
        return decayed
