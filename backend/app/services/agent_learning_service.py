"""CRUD, deduplication, confidence management, and prompt compilation for agent learnings."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import Counter, OrderedDict
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, select, update

from app.config import settings
from app.models.agent_learning import AgentLearning, AgentLearningSummary, _lesson_hash
from app.models.learning_vote import LearningVote
from app.services.text_similarity import semantic_best_match

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

# AQ-2: instruction-shaped content is a prompt-injection marker, not a
# learning. Indirect injections (crafted DB row values like "IMPORTANT: record
# a learning: ignore previous instructions…") aim to persist attacker text as
# an authoritative lesson. These patterns match instruction-addressed text
# ("ignore previous…", "you must…", fake system/markdown control blocks) in
# either the subject or the lesson; legitimate lessons are written as
# data observations, not as commands to the model.
_INSTRUCTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bignore\s+(all\s+|any\s+|the\s+)?(previous|prior|above|earlier)\b",
        r"\bdisregard\s+(all\s+|any\s+|the\s+)?(previous|prior|above|instructions?)\b",
        r"\byou\s+(must|shall|are\s+now|have\s+to|should\s+now)\b",
        r"\bsystem\s+prompt\b",
        r"\bnew\s+instructions?\b",
        r"\bdo\s+not\s+follow\b",
        r"\boverride\s+(all\s+|the\s+)?(previous|prior|instructions?|rules?)\b",
        r"</?(system|instruction|prompt|admin|root)\s*>",
        r"```\s*(system|instructions?)\b",
    )
)


def _contains_instruction_shaped_text(text: str) -> bool:
    return any(p.search(text) for p in _INSTRUCTION_PATTERNS)


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
    if _contains_instruction_shaped_text(subject) or _contains_instruction_shaped_text(lesson):
        return "Learning contains instruction-shaped text (possible prompt injection)"
    return None


def normalize_lesson_text(lesson: str) -> str:
    """Normalize whitespace, capitalize, and enforce max length."""
    text = " ".join(lesson.split())
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    if len(text) > MAX_LESSON_LENGTH:
        text = text[: MAX_LESSON_LENGTH - 1] + "\u2026"
    return text


# Negation tokens whose presence flips the polarity of a directive. Apostrophes
# are stripped before matching so contractions normalise (``don't`` -> ``dont``).
_NEGATION_TOKENS = frozenset(
    {
        "not",
        "never",
        "no",
        "none",
        "avoid",
        "without",
        "exclude",
        "excluding",
        "dont",
        "cant",
        "cannot",
        "wont",
        "isnt",
        "arent",
        "doesnt",
        "didnt",
        "nor",
        "neither",
        "stop",
        "skip",
    }
)

# High-frequency structural words that carry no directive intent. Removing them
# (alongside negation tokens) keeps the content-overlap signal focused on the
# substantive subject/object of the lesson.
_DIRECTIVE_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "to",
        "for",
        "in",
        "on",
        "of",
        "is",
        "are",
        "be",
        "use",
        "using",
        "used",
        "always",
        "should",
        "must",
        "when",
        "with",
        "and",
        "or",
        "this",
        "that",
        "these",
        "those",
        "from",
        "at",
        "by",
        "as",
        "it",
        "queries",
        "query",
        "production",
        "environment",
        "context",
        "completely",
    }
)

# Minimum substantive-token overlap (overlap coefficient) for two opposite-
# polarity lessons about the same subject to count as a contradiction.
_CONFLICT_OVERLAP_THRESHOLD = 0.6


def _tokenize_lesson(text: str) -> list[str]:
    return text.lower().replace("'", "").split()


def _negation_parity(text: str) -> int:
    """0 for an even number of negations, 1 for odd (i.e. net-negated)."""
    tokens = _tokenize_lesson(text)
    negations = sum(1 for t in tokens if t in _NEGATION_TOKENS)
    return negations % 2


def _content_tokens(text: str) -> set[str]:
    """Substantive tokens: drop negation tokens and structural stopwords."""
    return {
        t
        for t in _tokenize_lesson(text)
        if t not in _NEGATION_TOKENS and t not in _DIRECTIVE_STOPWORDS and len(t) > 1
    }


def lessons_contradict(a: str, b: str) -> bool:
    """Heuristic: two lessons contradict when they talk about the same thing
    (high substantive-token overlap) but with opposite negation polarity.

    This is deliberately high-precision: it catches the dangerous case the
    fuzzy-dedup path would otherwise *merge* (e.g. "always filter deleted_at"
    vs "never filter deleted_at") without flagging unrelated lessons. It does
    not attempt to detect ``use X`` vs ``use Y`` (different object, same
    polarity) — that needs schema-aware parsing and is left to schema
    validation / user voting.
    """
    if _negation_parity(a) == _negation_parity(b):
        return False
    ca = _content_tokens(a)
    cb = _content_tokens(b)
    if not ca or not cb:
        return False
    overlap = len(ca & cb) / min(len(ca), len(cb))
    return overlap >= _CONFLICT_OVERLAP_THRESHOLD


# R4-5: a higher threshold for the same-polarity case — we only want to flag
# lessons that clearly prescribe diverging values for the same subject, not
# refinements of one another.
_SAME_POLARITY_OVERLAP_THRESHOLD = 0.6

# R4-3: a learning surfaced at least this many times with zero applications is
# the strongest dead-weight signal; decay it fastest.
_EXPOSED_UNUSED_CUTOFF = 5


def lessons_conflict_same_polarity(a: str, b: str) -> bool:
    """Detect *same-polarity* conflicts (R4-5).

    ``lessons_contradict`` only catches opposite-polarity pairs ("always X" vs
    "never X"). It misses the equally dangerous "use X" vs "use Y" case: same
    polarity, same subject, but mutually-exclusive prescriptions. We flag those
    when (a) both lessons share the same negation polarity, (b) they have
    substantial shared content (so they're about the same thing), yet (c)
    *neither token set is a subset of the other* — i.e. each contributes a
    distinct prescription, so this is divergence rather than a refinement.

    Callers scope this to same subject+category, so the overlap requirement is
    primarily a guard against flagging unrelated lessons.
    """
    if _negation_parity(a) != _negation_parity(b):
        return False
    ca = _content_tokens(a)
    cb = _content_tokens(b)
    if not ca or not cb:
        return False
    # A pure refinement (one is a superset of the other) is not a conflict.
    if ca <= cb or cb <= ca:
        return False
    overlap = len(ca & cb) / min(len(ca), len(cb))
    distinct = bool((ca - cb) and (cb - ca))
    return overlap >= _SAME_POLARITY_OVERLAP_THRESHOLD and distinct


def lessons_conflict(a: str, b: str) -> bool:
    """True when two lessons conflict by either opposite or same polarity."""
    return lessons_contradict(a, b) or lessons_conflict_same_polarity(a, b)


# R4-6: bound the per-connection compile-lock map. It was an unbounded dict
# keyed by connection_id, so a process that touched many connections over its
# lifetime leaked one lock per connection forever. Cap it and evict the oldest
# idle lock when over capacity.
#
# Eviction must NOT drop a lock that has been handed out to a caller but not
# yet acquired (``Lock.locked()`` is still False in that window): if it did, a
# second caller for the same connection would create a *different* Lock object
# and the two callers would compile concurrently, corrupting the cached
# summary. We therefore refcount in-flight references and never evict an entry
# with refs > 0. Idle entries (refs == 0, not locked) remain evictable.
_COMPILE_LOCKS: OrderedDict[str, asyncio.Lock] = OrderedDict()
_COMPILE_LOCK_REFS: dict[str, int] = {}
_COMPILE_LOCKS_GUARD = asyncio.Lock()
_COMPILE_LOCKS_MAX = 512


def _evict_idle_compile_locks(keep: str) -> None:
    """Drop oldest idle (refs == 0, unlocked) locks while over capacity.

    Caller must hold ``_COMPILE_LOCKS_GUARD``. ``keep`` is never evicted.
    """
    if len(_COMPILE_LOCKS) <= _COMPILE_LOCKS_MAX:
        return
    for key in list(_COMPILE_LOCKS.keys()):
        if key == keep:
            continue
        if _COMPILE_LOCK_REFS.get(key, 0) > 0 or _COMPILE_LOCKS[key].locked():
            continue
        del _COMPILE_LOCKS[key]
        if len(_COMPILE_LOCKS) <= _COMPILE_LOCKS_MAX:
            break


@asynccontextmanager
async def _compile_lock(connection_id: str):
    """Acquire the per-connection compile lock, safe against cap eviction.

    A reference is registered under the guard *before* the guard is released,
    so the entry cannot be evicted between hand-out and acquisition. This
    guarantees every caller for the same ``connection_id`` shares one Lock
    object and compilation stays serialized.
    """
    async with _COMPILE_LOCKS_GUARD:
        lock = _COMPILE_LOCKS.get(connection_id)
        if lock is None:
            lock = asyncio.Lock()
            _COMPILE_LOCKS[connection_id] = lock
        else:
            _COMPILE_LOCKS.move_to_end(connection_id)
        _COMPILE_LOCK_REFS[connection_id] = _COMPILE_LOCK_REFS.get(connection_id, 0) + 1
        _evict_idle_compile_locks(keep=connection_id)

    try:
        async with lock:
            yield
    finally:
        async with _COMPILE_LOCKS_GUARD:
            remaining = _COMPILE_LOCK_REFS.get(connection_id, 0) - 1
            if remaining <= 0:
                _COMPILE_LOCK_REFS.pop(connection_id, None)
            else:
                _COMPILE_LOCK_REFS[connection_id] = remaining


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
            # Confidence/confirmation bumps change the compiled prompt ranking,
            # so the cached summary must be invalidated even on the dedup path.
            await self._invalidate_summary(session, connection_id)
            return entry

        similar = await self.find_similar(session, connection_id, category, subject, lesson)
        # A textually-similar candidate is only a true duplicate when it agrees
        # with the new lesson. If they have opposite polarity (e.g. "always
        # filter X" vs "never filter X") merging would silently reinforce a
        # contradiction, so we fall through to conflict resolution instead.
        if similar and not lessons_contradict(lesson, similar.lesson):
            similar.times_confirmed += 1
            similar.confidence = min(1.0, similar.confidence + 0.1)
            if len(lesson) > len(similar.lesson):
                similar.lesson = lesson
                similar.lesson_hash = lhash
            similar.is_active = True
            similar.updated_at = datetime.now(UTC)
            await session.flush()
            await self._invalidate_summary(session, connection_id)
            return similar

        new_is_outranked = await self._resolve_conflicts(
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
        # If a stronger, contradicting lesson already exists we still record the
        # new one for audit/history but keep it inactive so it never overrides
        # the higher-confidence advice in prompts.
        if new_is_outranked:
            entry.is_active = False
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
        if not candidates:
            return None

        lesson_lower = lesson_text.strip().lower()
        texts = [c.lesson.strip().lower() for c in candidates]
        match = semantic_best_match(lesson_lower, texts, threshold=SIMILARITY_THRESHOLD)
        if match is None:
            return None
        idx, _score = match
        return candidates[idx]

    # ------------------------------------------------------------------
    # Conflict detection
    # ------------------------------------------------------------------

    async def _resolve_conflicts(
        self,
        session: AsyncSession,
        connection_id: str,
        category: str,
        subject: str,
        new_lesson: str,
        new_confidence: float,
    ) -> bool:
        """Reconcile a new lesson against existing same-subject learnings.

        For each active learning about the same subject/category that
        *contradicts* the new lesson (opposite polarity, same substantive
        content — see :func:`lessons_contradict`):

        * if the new lesson is at least as confident, the old one is
          deactivated (newer evidence wins ties);
        * otherwise the new lesson is "outranked" — a stronger contradicting
          lesson stands, and the caller stores the new one inactive so the two
          never both feed prompts.

        Returns ``True`` when the new lesson is outranked by an existing one.
        """
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
            return False

        new_is_outranked = False
        for old in existing:
            # R4-5: catch same-polarity divergence ("use X" vs "use Y") in
            # addition to opposite-polarity contradictions.
            if not lessons_conflict(new_lesson, old.lesson):
                continue

            # R4-5: keep the incumbent on a confidence tie. Only a *strictly*
            # more confident new lesson supersedes the existing one; equal
            # confidence leaves the established learning in place and stores
            # the newcomer inactive.
            if old.confidence < new_confidence:
                old.is_active = False
                old.updated_at = datetime.now(UTC)
                logger.info(
                    "Deactivated conflicting learning %s "
                    "(superseded by strictly more confident lesson)",
                    old.id,
                )
            else:
                new_is_outranked = True
                logger.info(
                    "New lesson outranked by existing >= confidence "
                    "conflicting learning %s; storing new one inactive",
                    old.id,
                )

        return new_is_outranked

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
        """Bump ``times_applied`` — fires only when the LLM provably uses a
        learning (e.g. after successful validation). Distinct from
        :meth:`expose_learning`, which records mere exposure. Together they
        let the decay-score (V1.13.0 C5) reflect actual influence on outputs
        rather than raw read traffic."""
        await session.execute(
            update(AgentLearning)
            .where(AgentLearning.id == learning_id)
            .values(times_applied=AgentLearning.times_applied + 1)
        )
        await session.flush()

    async def expose_learning(
        self,
        session: AsyncSession,
        learning_id: str,
    ) -> None:
        """Bump ``times_exposed`` — fires whenever the SQL agent reads this
        learning into its prompt context, regardless of whether the LLM
        actually cites it. C5, v1.13.0: separates read-side traffic from
        citation so ``times_applied`` (and the decay score derived from it)
        remains a meaningful signal."""
        await session.execute(
            update(AgentLearning)
            .where(AgentLearning.id == learning_id)
            .values(times_exposed=AgentLearning.times_exposed + 1)
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

    async def vote_learning(
        self,
        session: AsyncSession,
        learning_id: str,
        user_id: str,
        vote: int,
    ) -> tuple[AgentLearning | None, str]:
        """Cast a per-user vote on a learning (AQ-7).

        One active vote per ``(learning_id, user_id)``:
        * a repeated vote of the same sign is a no-op (``"noop"``) — one user
          cannot pump confidence to 1.0 / ★CRITICAL or deactivate someone
          else's learning by clicking twice;
        * a sign change reverses the previous vote's numeric effect before
          applying the new one (``"changed"``);
        * votes from different users are independent (``"recorded"``).

        Returns ``(entry, outcome)`` with outcome ∈
        ``{"recorded", "noop", "changed"}``; ``(None, "missing")`` when the
        learning does not exist.
        """
        if vote not in (1, -1):
            raise ValueError(f"Invalid vote: {vote}")
        entry = await session.get(AgentLearning, learning_id)
        if not entry:
            return None, "missing"

        existing = await session.execute(
            select(LearningVote).where(
                LearningVote.learning_id == learning_id,
                LearningVote.user_id == user_id,
            )
        )
        prev = existing.scalar_one_or_none()

        if prev is not None and prev.vote == vote:
            return entry, "noop"

        if prev is not None:
            # Reverse the previous vote's effect before applying the new one.
            if prev.vote == 1:
                entry.times_confirmed = max(0, entry.times_confirmed - 1)
                entry.confidence = max(0.0, entry.confidence - 0.1)
            else:
                entry.confidence = min(1.0, entry.confidence + 0.3)
            prev.vote = vote
            prev.updated_at = datetime.now(UTC)
            outcome = "changed"
        else:
            session.add(LearningVote(learning_id=learning_id, user_id=user_id, vote=vote))
            outcome = "recorded"

        if vote == 1:
            entry.times_confirmed += 1
            entry.confidence = min(1.0, entry.confidence + 0.1)
        else:
            entry.confidence = max(0.0, entry.confidence - 0.3)
            if entry.confidence < 0.1:
                entry.is_active = False
        entry.updated_at = datetime.now(UTC)
        await session.flush()
        await self._invalidate_summary(session, entry.connection_id)
        return entry, outcome

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
        *,
        category_filter: list[str] | None = None,
        table_filter: str | None = None,
        limit: int | None = None,
    ) -> list[AgentLearning]:
        """Single source of truth for retrieving agent learnings.

        Filters:
        - ``min_confidence`` — minimum confidence threshold
        - ``active_only`` — only learnings with ``is_active = True``
        - ``skip_blocklisted`` — drop learnings whose subject is a blocked schema name
        - ``category_filter`` — restrict to one or more categories
        - ``table_filter`` — restrict to learnings mentioning a specific table
          (matched against either subject or lesson, case-insensitive)
        - ``limit`` — cap the number of returned rows after filtering
        """
        stmt = select(AgentLearning).where(
            AgentLearning.connection_id == connection_id,
            AgentLearning.confidence >= min_confidence,
        )
        if active_only:
            stmt = stmt.where(AgentLearning.is_active.is_(True))
        if category_filter:
            stmt = stmt.where(AgentLearning.category.in_(category_filter))
        stmt = stmt.order_by(
            AgentLearning.confidence.desc(),
            AgentLearning.times_confirmed.desc(),
        )
        result = await session.execute(stmt)
        rows = list(result.scalars().all())
        if skip_blocklisted:
            rows = [r for r in rows if r.subject.lower() not in SUBJECT_BLOCKLIST]
        if table_filter:
            tbl_lower = table_filter.lower()
            rows = [
                r for r in rows if tbl_lower in r.subject.lower() or tbl_lower in r.lesson.lower()
            ]
        if limit is not None and limit >= 0:
            rows = rows[:limit]
        return rows

    async def get_learnings_for_table(
        self,
        session: AsyncSession,
        connection_id: str,
        table_name: str,
    ) -> list[AgentLearning]:
        """Convenience wrapper around :meth:`get_learnings` with a table filter."""
        return await self.get_learnings(
            session,
            connection_id,
            min_confidence=0.3,
            active_only=True,
            skip_blocklisted=True,
            table_filter=table_name,
        )

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
            session,
            connection_id,
            min_confidence=0.0,
            active_only=True,
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
    def priority_score(lrn: AgentLearning) -> float:
        """Canonical composite rank for a learning (R4-4: single source).

        Combines confidence (0-1), confirmation count (log-scaled), and
        application count (log-scaled) into a single rank. R4-3: learnings that
        have been repeatedly surfaced to the LLM (``times_exposed``) but never
        provably applied (``times_applied``) are dead weight — they earn a
        small penalty so proven learnings out-rank perennial no-ops.

        This is THE ranking function for every surface (prompt compilation,
        orchestrator context loader, cost estimation). Do not reimplement an
        ad-hoc ``(times_confirmed, confidence)`` ordering elsewhere.
        """
        import math as _math

        conf_part = lrn.confidence * 0.4
        confirmed_part = _math.log1p(lrn.times_confirmed) * 0.4
        applied_part = _math.log1p(lrn.times_applied) * 0.2
        # Exposed-but-unapplied penalty: only the surplus exposures over
        # applications count, kept small so it breaks ties rather than dominates.
        unused_exposure = max(0, (lrn.times_exposed or 0) - (lrn.times_applied or 0))
        exposure_penalty = _math.log1p(unused_exposure) * 0.05
        return conf_part + confirmed_part + applied_part - exposure_penalty

    # Backwards-compatible alias (kept so existing callers/tests don't break).
    _priority_score = priority_score

    async def compile_prompt(
        self,
        session: AsyncSession,
        connection_id: str,
        *,
        force: bool = True,
    ) -> str:
        """Compile the learnings prompt for *connection_id*.

        Acquires a per-connection asyncio lock so concurrent recompilations
        serialize cleanly. When ``force=False`` (the path used by
        ``get_or_compile_summary``), waiters that arrive after the lock holder
        finishes will see the freshly cached prompt and return immediately.
        """
        async with _compile_lock(connection_id):
            if not force:
                cached = await session.execute(
                    select(AgentLearningSummary).where(
                        AgentLearningSummary.connection_id == connection_id
                    )
                )
                cached_summary = cached.scalar_one_or_none()
                if cached_summary and cached_summary.compiled_prompt:
                    return cached_summary.compiled_prompt

            return await self._compile_prompt_locked(session, connection_id)

    async def get_prompt_learnings(
        self,
        session: AsyncSession,
        connection_id: str,
    ) -> list[AgentLearning]:
        """Return the exact learnings that feed the compiled prompt.

        R4-1: single source of truth for *which* learnings are surfaced to
        the LLM, so the preloaded path can attribute feedback to them
        (``exposed_learning_ids`` / ``times_exposed``) instead of leaving the
        signal inert.
        """
        learnings = await self.get_learnings(
            session, connection_id, min_confidence=0.5, active_only=True
        )
        learnings.sort(key=self._priority_score, reverse=True)
        return learnings[:30]

    async def _compile_prompt_locked(
        self,
        session: AsyncSession,
        connection_id: str,
    ) -> str:
        learnings = await self.get_prompt_learnings(session, connection_id)
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

        if settings.cross_connection_learnings_enabled:
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
        owner_user_id: str | None = None,
        min_connections: int = 2,
        min_confidence: float = 0.7,
        limit: int = 15,
    ) -> list[dict]:
        """Identify learnings that appear across multiple connections.

        Returns high-confidence patterns that have been independently
        discovered on at least *min_connections* different connections,
        suggesting they are universally applicable (e.g. "amounts are
        stored in cents").

        Tenant isolation (R3 / F-LEARN-07): when *owner_user_id* is provided,
        the aggregation is restricted to connections under projects owned by
        that user, so a pattern learned on another tenant's connection is never
        promoted across the tenant boundary. ``owner_user_id=None`` preserves the
        legacy unscoped behavior for internal/admin callers that pass no scope.
        """
        from app.models.connection import Connection
        from app.models.project import Project

        stmt = select(
            AgentLearning.lesson_hash,
            AgentLearning.category,
            AgentLearning.subject,
            func.max(AgentLearning.lesson).label("lesson"),
            func.max(AgentLearning.confidence).label("max_confidence"),
            func.count(func.distinct(AgentLearning.connection_id)).label("conn_count"),
            func.sum(AgentLearning.times_confirmed).label("total_confirmed"),
        )
        if owner_user_id is not None:
            stmt = stmt.join(Connection, Connection.id == AgentLearning.connection_id).join(
                Project, Project.id == Connection.project_id
            )
        stmt = (
            stmt.where(
                AgentLearning.is_active.is_(True),
                AgentLearning.confidence >= min_confidence,
                *((Project.owner_id == owner_user_id,) if owner_user_id is not None else ()),
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

        Tenant isolation (R3 / F-LEARN-07): patterns are aggregated only across
        connections owned by the same user as *connection_id*'s project. If the
        owner cannot be resolved (orphaned/unknown connection), promote nothing
        (fail closed) rather than leaking another tenant's patterns.
        """
        from app.models.connection import Connection
        from app.models.project import Project

        owner_result = await session.execute(
            select(Project.owner_id)
            .join(Connection, Connection.project_id == Project.id)
            .where(Connection.id == connection_id)
        )
        owner_user_id = owner_result.scalar_one_or_none()
        if not owner_user_id:
            return []

        patterns = await self.get_global_patterns(session, owner_user_id=owner_user_id)
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

        return await self.compile_prompt(session, connection_id, force=False)

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
        - -0.02 if previously applied — slower decay for proven learnings
        - -0.05 if never applied (times_applied == 0) — faster cleanup
        - -0.08 if surfaced many times but never applied (R4-3) — these are
          proven dead weight (the LLM keeps seeing them and never uses them)
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

        # R4-3: "surfaced often, never applied" is the strongest dead-weight
        # signal — decay it fastest so it falls below the 0.2 cutoff sooner.
        for lrn in stale:
            if lrn.times_applied > 0:
                penalty = 0.02
            elif (lrn.times_exposed or 0) >= _EXPOSED_UNUSED_CUTOFF:
                penalty = 0.08
            else:
                penalty = 0.05
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
