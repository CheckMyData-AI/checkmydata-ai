"""Extracts lessons from query validation outcomes.

Heuristic extractors fire after every validation loop at zero LLM cost.
The ``LLMAnalyzer`` can be triggered for deeper cross-query pattern
extraction when the heuristics alone are insufficient.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.core.query_validation import QueryAttempt, QueryErrorType
from app.services.agent_learning_service import SUBJECT_BLOCKLIST

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.llm.router import LLMRouter

logger = logging.getLogger(__name__)

_llm_analysis_timestamps: dict[str, datetime] = {}


@dataclass
class ExtractedLesson:
    category: str
    subject: str
    lesson: str
    confidence: float = 0.6
    source_query: str | None = None
    source_error: str | None = None


_TABLE_RE = re.compile(
    r'\b(?:FROM|JOIN|INTO|UPDATE)\s+["`]?(?:\w+["`]?\s*\.\s*)?["`]?(\w+)["`]?',
    re.IGNORECASE,
)


def _extract_tables(sql: str) -> list[str]:
    return [m.group(1).lower() for m in _TABLE_RE.finditer(sql)]


def _is_valid_subject(subject: str) -> bool:
    """Return False for SQL keywords, metadata tables, and placeholder subjects."""
    return subject.lower() not in SUBJECT_BLOCKLIST


async def _load_sync_warnings_for_dedup(
    session: AsyncSession, connection_id: str
) -> dict[str, str]:
    """Load sync conversion_warnings keyed by table name (lowercase)."""
    try:
        from app.services.code_db_sync_service import CodeDbSyncService

        svc = CodeDbSyncService()
        entries = await svc.get_sync(session, connection_id)
        return {
            e.table_name.lower(): (e.conversion_warnings or "").lower()
            for e in entries
            if e.conversion_warnings
        }
    except Exception:
        logger.debug("Failed to load sync warnings for connection %s", connection_id, exc_info=True)
        return {}


def _is_covered_by_sync(lesson: ExtractedLesson, sync_warnings: dict[str, str]) -> bool:
    """Return True if a sync conversion_warning already covers this lesson."""
    if lesson.category not in ("data_format", "schema_gotcha"):
        return False

    subject_lower = lesson.subject.lower()
    warning = sync_warnings.get(subject_lower, "")
    if not warning:
        return False

    lesson_lower = lesson.lesson.lower()
    if lesson.category == "data_format":
        if "cent" in lesson_lower and ("cent" in warning or "/ 100" in warning):
            return True
        if "1000" in lesson_lower and ("1000" in warning or "minor unit" in warning):
            return True
        if "::text" in lesson_lower and "text" in warning:
            return True

    if lesson.category == "schema_gotcha":
        if "deleted_at" in lesson_lower and "delet" in warning:
            return True
        if "is_deleted" in lesson_lower and "delet" in warning:
            return True
        if "schema prefix" in lesson_lower and "schema" in warning:
            return True

    return False


class LearningAnalyzer:
    """Analyzes validation loop results and extracts lessons.

    Policy (T06): LLM-first. The ``learning_analyzer_mode`` setting gates
    behaviour:

    - ``"llm_first"`` (default) — ``LLMAnalyzer`` runs first; the legacy
      ``_detect_*`` regex extractors only run when the LLM returned
      nothing (e.g. quota exhausted, cooldown, parsing failure).
    - ``"hybrid"`` — the old behaviour: heuristics first, LLM fallback.
    - ``"heuristic"`` — LLM disabled entirely (emergencies / tests).

    ``llm_router`` can be injected for tests; default is a shared
    ``LLMRouter`` singleton to avoid spawning a fresh HTTP client per
    analysis call.
    """

    # Shared router instance. The module-level singleton prevents repeated
    # ``httpx.AsyncClient`` creation in the hot path (one per attempt batch).
    _shared_llm_router: LLMRouter | None = None

    def __init__(self, llm_router: LLMRouter | None = None) -> None:
        self._llm_router = llm_router  # overrides shared for tests / wiring

    @classmethod
    def _get_shared_router(cls) -> LLMRouter:
        if cls._shared_llm_router is None:
            from app.llm.router import LLMRouter

            cls._shared_llm_router = LLMRouter()
        return cls._shared_llm_router

    async def analyze(
        self,
        session: AsyncSession,
        connection_id: str,
        question: str,
        attempts: list[QueryAttempt],
        success: bool,
    ) -> list[ExtractedLesson]:
        if not connection_id or not attempts:
            return []

        from app.config import settings as _settings

        mode = (_settings.learning_analyzer_mode or "hybrid").lower()
        lessons: list[ExtractedLesson] = []

        if mode == "llm_first":
            lessons = await self._llm_extract(connection_id, attempts)
            if not lessons:
                lessons = self._heuristic_extract(attempts, question)
        else:
            lessons = self._heuristic_extract(attempts, question)
            if mode == "hybrid" and not lessons and len(attempts) >= 2:
                lessons = await self._llm_extract(connection_id, attempts)

        if not lessons:
            return []

        sync_warnings = await _load_sync_warnings_for_dedup(session, connection_id)

        from app.services.agent_learning_service import AgentLearningService

        svc = AgentLearningService()
        stored: list[ExtractedLesson] = []
        for lesson in lessons:
            if _is_covered_by_sync(lesson, sync_warnings):
                logger.debug("Skipping learning (covered by sync): %s", lesson.lesson)
                continue
            try:
                await svc.create_learning(
                    session,
                    connection_id=connection_id,
                    category=lesson.category,
                    subject=lesson.subject,
                    lesson=lesson.lesson,
                    confidence=lesson.confidence,
                    source_query=lesson.source_query,
                    source_error=lesson.source_error,
                )
                stored.append(lesson)
            except Exception:
                logger.debug("Failed to store learning: %s", lesson.lesson, exc_info=True)

        if stored:
            await session.commit()
            logger.info("Extracted %d learnings for connection %s", len(stored), connection_id)

        return stored

    async def analyze_negative_feedback(
        self,
        session: AsyncSession,
        connection_id: str,
        query: str | None,
        question: str | None,
        error_detail: str | None = None,
    ) -> list[ExtractedLesson]:
        """Extract lessons from user thumbs-down feedback."""
        if not connection_id or not query:
            return []

        lessons: list[ExtractedLesson] = []
        tables = _extract_tables(query)
        subject = tables[0] if tables else "unknown"

        if not _is_valid_subject(subject):
            return []

        if error_detail:
            lessons.append(
                ExtractedLesson(
                    category="query_pattern",
                    subject=subject,
                    lesson=f"User flagged incorrect results for query on {subject}. "
                    f"Detail: {error_detail[:300]}",
                    confidence=0.7,
                    source_query=query,
                    source_error="user_negative_feedback",
                )
            )

        if not lessons:
            return []

        from app.services.agent_learning_service import AgentLearningService

        svc = AgentLearningService()
        for lesson in lessons:
            try:
                await svc.create_learning(
                    session,
                    connection_id=connection_id,
                    category=lesson.category,
                    subject=lesson.subject,
                    lesson=lesson.lesson,
                    confidence=lesson.confidence,
                    source_query=lesson.source_query,
                    source_error=lesson.source_error,
                )
            except Exception:
                logger.debug("Failed to store feedback learning", exc_info=True)

        await session.commit()
        return lessons

    # ------------------------------------------------------------------
    # Mode dispatchers
    # ------------------------------------------------------------------

    def _heuristic_extract(
        self,
        attempts: list[QueryAttempt],
        question: str,
    ) -> list[ExtractedLesson]:
        """Run all legacy ``_detect_*`` extractors on the attempt sequence."""
        lessons: list[ExtractedLesson] = []
        if len(attempts) > 1:
            lessons.extend(self._detect_table_preference(attempts, question))
            lessons.extend(self._detect_column_correction(attempts))
            lessons.extend(self._detect_format_discovery(attempts))
            lessons.extend(self._detect_schema_gotcha(attempts))
        lessons.extend(self._detect_performance_hint(attempts))
        return lessons

    async def _llm_extract(
        self,
        connection_id: str,
        attempts: list[QueryAttempt],
    ) -> list[ExtractedLesson]:
        """Delegate to :class:`LLMAnalyzer` (cooldown-aware) and return its lessons.

        Failures and cooldown skips return an empty list so the caller can
        gracefully fall back to heuristics.
        """
        if len(attempts) < 2:
            return []
        try:
            router = self._llm_router or self._get_shared_router()
            llm_analyzer = LLMAnalyzer(router=router)
            if not llm_analyzer.should_run(connection_id):
                return []
            from app.models.base import async_session_factory

            async with async_session_factory() as llm_session:
                return await llm_analyzer.analyze(llm_session, connection_id, attempts)
        except Exception:
            logger.debug("LLM-based extraction failed; falling back to heuristics", exc_info=True)
            return []

    # ------------------------------------------------------------------
    # Heuristic extractors
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_table_preference(
        attempts: list[QueryAttempt],
        question: str,
    ) -> list[ExtractedLesson]:
        """Detect when a failed attempt used table A and the fix used table B."""
        lessons: list[ExtractedLesson] = []

        for i in range(len(attempts) - 1):
            failed = attempts[i]
            next_attempt = attempts[i + 1]

            if not failed.error:
                continue
            if failed.error.error_type not in (
                QueryErrorType.TABLE_NOT_FOUND,
                QueryErrorType.EMPTY_RESULT,
                QueryErrorType.COLUMN_NOT_FOUND,
            ):
                continue

            failed_tables = set(_extract_tables(failed.query))
            next_tables = set(_extract_tables(next_attempt.query))

            removed = failed_tables - next_tables
            added = next_tables - failed_tables

            if removed and added:
                is_success = next_attempt.results is not None and next_attempt.error is None
                if is_success or (i + 2 < len(attempts) and attempts[-1].error is None):
                    for old_t in removed:
                        for new_t in added:
                            if not _is_valid_subject(new_t):
                                continue
                            lessons.append(
                                ExtractedLesson(
                                    category="table_preference",
                                    subject=new_t,
                                    lesson=(
                                        f"Use `{new_t}` instead of `{old_t}` "
                                        f"for queries of this type"
                                    ),
                                    confidence=0.65,
                                    source_query=next_attempt.query,
                                    source_error=failed.error.message if failed.error else None,
                                )
                            )

        return lessons

    @staticmethod
    def _detect_column_correction(
        attempts: list[QueryAttempt],
    ) -> list[ExtractedLesson]:
        """Detect column_not_found errors where repair changed the column name."""
        lessons: list[ExtractedLesson] = []

        for i in range(len(attempts) - 1):
            failed = attempts[i]
            next_attempt = attempts[i + 1]

            if not failed.error:
                continue
            if failed.error.error_type != QueryErrorType.COLUMN_NOT_FOUND:
                continue

            wrong_col_match = re.search(
                r"column\s+['\"`]?(\w+)['\"`]?", failed.error.message, re.IGNORECASE
            )
            if not wrong_col_match:
                continue
            wrong_col = wrong_col_match.group(1)

            if wrong_col.lower() in next_attempt.query.lower():
                continue

            suggested = failed.error.suggested_columns
            tables = _extract_tables(failed.query)
            subject = tables[0] if tables else "unknown"

            if not _is_valid_subject(subject):
                continue

            if suggested:
                correct_col = suggested[0]
                lessons.append(
                    ExtractedLesson(
                        category="column_usage",
                        subject=subject,
                        lesson=(
                            f"Column `{wrong_col}` does not exist on `{subject}`. "
                            f"Use `{correct_col}` instead."
                        ),
                        confidence=0.7,
                        source_query=failed.query,
                        source_error=failed.error.message,
                    )
                )

        return lessons

    @staticmethod
    def _detect_format_discovery(
        attempts: list[QueryAttempt],
    ) -> list[ExtractedLesson]:
        """Detect data format corrections (e.g., dividing by 100 for cents)."""
        lessons: list[ExtractedLesson] = []

        if len(attempts) < 2:
            return lessons

        for i in range(len(attempts) - 1):
            failed_q = attempts[i].query.lower()
            fixed_q = attempts[i + 1].query.lower()

            tables = _extract_tables(attempts[i + 1].query)
            subject = tables[0] if tables else "unknown"

            if not _is_valid_subject(subject):
                continue

            if "/ 100" in fixed_q and "/ 100" not in failed_q:
                col_match = re.search(r"(\w+)\s*/\s*100", fixed_q)
                col_name = col_match.group(1) if col_match else "amount"
                lessons.append(
                    ExtractedLesson(
                        category="data_format",
                        subject=subject,
                        lesson=(
                            f"Column `{col_name}` on `{subject}` stores values in "
                            f"cents (integer). Divide by 100 for dollar amounts."
                        ),
                        confidence=0.7,
                        source_query=attempts[i + 1].query,
                    )
                )

            if "/ 1000" in fixed_q and "/ 1000" not in failed_q:
                col_match = re.search(r"(\w+)\s*/\s*1000", fixed_q)
                col_name = col_match.group(1) if col_match else "amount"
                lessons.append(
                    ExtractedLesson(
                        category="data_format",
                        subject=subject,
                        lesson=(
                            f"Column `{col_name}` on `{subject}` stores values in "
                            f"minor units. Divide by 1000 for display values."
                        ),
                        confidence=0.65,
                        source_query=attempts[i + 1].query,
                    )
                )

            if "::text" in fixed_q and "::text" not in failed_q:
                lessons.append(
                    ExtractedLesson(
                        category="data_format",
                        subject=subject,
                        lesson=(
                            f"Some columns on `{subject}` require explicit "
                            f"::text cast for string operations."
                        ),
                        confidence=0.55,
                        source_query=attempts[i + 1].query,
                    )
                )

        return lessons

    @staticmethod
    def _detect_schema_gotcha(
        attempts: list[QueryAttempt],
    ) -> list[ExtractedLesson]:
        """Detect pre-validation gotchas like soft-delete patterns."""
        lessons: list[ExtractedLesson] = []

        for i in range(len(attempts) - 1):
            failed = attempts[i]
            next_attempt = attempts[i + 1]

            if not failed.error:
                continue

            failed_q = failed.query.lower()
            fixed_q = next_attempt.query.lower()
            tables = _extract_tables(next_attempt.query)
            subject = tables[0] if tables else "unknown"

            if not _is_valid_subject(subject):
                continue

            if "deleted_at is null" in fixed_q and "deleted_at" not in failed_q:
                lessons.append(
                    ExtractedLesson(
                        category="schema_gotcha",
                        subject=subject,
                        lesson=(
                            f"Table `{subject}` uses soft-delete pattern. "
                            f"Always filter with `WHERE deleted_at IS NULL` for active records."
                        ),
                        confidence=0.75,
                        source_query=next_attempt.query,
                        source_error=failed.error.message,
                    )
                )

            if "is_deleted" in fixed_q and "is_deleted" not in failed_q:
                lessons.append(
                    ExtractedLesson(
                        category="schema_gotcha",
                        subject=subject,
                        lesson=(
                            f"Table `{subject}` has `is_deleted` flag. "
                            f"Filter with `WHERE is_deleted = 0` for active records."
                        ),
                        confidence=0.7,
                        source_query=next_attempt.query,
                        source_error=failed.error.message,
                    )
                )

            if (
                failed.error.error_type == QueryErrorType.SYNTAX_ERROR
                and "schema" in failed.error.message.lower()
            ):
                schema_match = re.search(r"(\w+)\.(\w+)", fixed_q)
                if schema_match and "." not in failed_q.split("from")[-1].split("join")[0][:50]:
                    schema_name = schema_match.group(1)
                    lessons.append(
                        ExtractedLesson(
                            category="schema_gotcha",
                            subject=subject,
                            lesson=(
                                f"Tables in this database require schema prefix "
                                f"`{schema_name}`. Use `{schema_name}.{subject}` format."
                            ),
                            confidence=0.8,
                            source_query=next_attempt.query,
                            source_error=failed.error.message,
                        )
                    )

        return lessons

    @staticmethod
    def _detect_performance_hint(
        attempts: list[QueryAttempt],
    ) -> list[ExtractedLesson]:
        """Detect timeout errors resolved by adding filters or limits."""
        lessons: list[ExtractedLesson] = []

        for i, attempt in enumerate(attempts):
            if not attempt.error:
                continue
            if attempt.error.error_type != QueryErrorType.TIMEOUT:
                continue

            if i + 1 >= len(attempts):
                continue

            next_attempt = attempts[i + 1]
            if next_attempt.error and next_attempt.error.error_type == QueryErrorType.TIMEOUT:
                continue

            tables = _extract_tables(attempt.query)
            subject = tables[0] if tables else "unknown"

            if not _is_valid_subject(subject):
                continue

            fixed_q = next_attempt.query.lower()
            failed_q = attempt.query.lower()

            hints: list[str] = []
            if "limit" in fixed_q and "limit" not in failed_q:
                hints.append("add LIMIT clause")
            if re.search(r"where.*(?:date|created|updated)", fixed_q) and not re.search(
                r"where.*(?:date|created|updated)", failed_q
            ):
                hints.append("filter by date range")

            if hints:
                advice = " and ".join(hints)
                lessons.append(
                    ExtractedLesson(
                        category="performance_hint",
                        subject=subject,
                        lesson=(
                            f"Table `{subject}` can timeout on unfiltered queries. "
                            f"Always {advice} to avoid timeouts."
                        ),
                        confidence=0.7,
                        source_query=next_attempt.query,
                        source_error=attempt.error.message,
                    )
                )

        return lessons


# ======================================================================
# LLM-based Analyzer (deeper cross-query pattern extraction)
# ======================================================================

_LLM_EXTRACTION_PROMPT = """\
You are a database expert analyzing a series of SQL query attempts against the same database.
Your goal is to extract reusable lessons that will help future query generation.

For each lesson, output a JSON array of objects with these fields:
- "category": one of "table_preference", "column_usage", "data_format", \
"query_pattern", "schema_gotcha", "performance_hint", "pipeline_pattern", \
"data_quality_hint", "replan_recovery"
- "subject": the main table or column the lesson is about (must be a real \
table/column name, NOT a SQL keyword like "columns" or "tables")
- "lesson": a clear, actionable sentence in English (max 200 chars)
- "confidence": a float between 0.5 and 0.9

Only output lessons that are clearly supported by the evidence. Do NOT guess.
The "subject" must be an actual database object name, not a generic term.
The "lesson" must be in English, even if the user question was in another language.
If there are no lessons, output an empty array: []

Respond with ONLY the JSON array, no markdown fences, no explanation.
"""


class LLMAnalyzer:
    """Batch LLM-based analysis for complex cross-query pattern extraction.

    Triggered less frequently than heuristic extractors to control cost:
    - Max one analysis per connection per hour
    - Only when there are 3+ query attempts in a session, or on negative feedback
    """

    COOLDOWN_SECONDS = 3600

    def __init__(self, router: LLMRouter | None = None) -> None:
        self._router = router

    @classmethod
    def should_run(cls, connection_id: str) -> bool:
        last = _llm_analysis_timestamps.get(connection_id)
        if last is None:
            return True
        elapsed = (datetime.now(UTC) - last).total_seconds()
        return elapsed >= cls.COOLDOWN_SECONDS

    @classmethod
    def _mark_run(cls, connection_id: str) -> None:
        _llm_analysis_timestamps[connection_id] = datetime.now(UTC)

    async def analyze(
        self,
        session: AsyncSession,
        connection_id: str,
        attempts: list[QueryAttempt],
    ) -> list[ExtractedLesson]:
        """Run LLM analysis on a batch of query attempts and store results."""
        if not connection_id or len(attempts) < 3:
            return []

        if not self.should_run(connection_id):
            logger.debug("LLM analyzer cooldown active for %s, skipping", connection_id)
            return []

        self._mark_run(connection_id)

        from app.llm.base import Message

        attempts_text = self._format_attempts(attempts)

        llm = self._router or LearningAnalyzer._get_shared_router()
        messages = [
            Message(role="system", content=_LLM_EXTRACTION_PROMPT),
            Message(role="user", content=attempts_text),
        ]

        try:
            response = await llm.complete(messages=messages, temperature=0.0, max_tokens=2048)
            raw = response.content.strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```(?:json)?\s*", "", raw)
                raw = re.sub(r"\s*```$", "", raw)
            parsed = json.loads(raw)
        except Exception:
            logger.warning("LLM analyzer failed to parse response", exc_info=True)
            return []

        if not isinstance(parsed, list):
            return []

        valid_categories = {
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

        lessons: list[ExtractedLesson] = []
        for item in parsed:
            cat = item.get("category", "")
            if cat not in valid_categories:
                continue
            subject = item.get("subject", "")
            lesson_text = item.get("lesson", "")
            conf = item.get("confidence", 0.7)
            if not subject or not lesson_text:
                continue
            conf = max(0.5, min(0.9, float(conf)))
            lessons.append(
                ExtractedLesson(
                    category=cat,
                    subject=subject[:255],
                    lesson=lesson_text[:500],
                    confidence=conf,
                )
            )

        if not lessons:
            return []

        from app.services.agent_learning_service import AgentLearningService

        svc = AgentLearningService()
        stored: list[ExtractedLesson] = []
        for lesson in lessons:
            try:
                await svc.create_learning(
                    session,
                    connection_id=connection_id,
                    category=lesson.category,
                    subject=lesson.subject,
                    lesson=lesson.lesson,
                    confidence=lesson.confidence,
                    source_query=None,
                    source_error="llm_analysis",
                )
                stored.append(lesson)
            except Exception:
                logger.debug("Failed to store LLM-extracted learning", exc_info=True)

        if stored:
            await session.commit()
            logger.info(
                "LLM analyzer extracted %d learnings for connection %s",
                len(stored),
                connection_id,
            )

        return stored

    @staticmethod
    def _format_attempts(attempts: list[QueryAttempt]) -> str:
        parts: list[str] = []
        for i, a in enumerate(attempts, 1):
            status = "SUCCESS" if (a.results and not a.error) else "FAILED"
            error_msg = a.error.message[:300] if a.error else "none"
            row_count = a.results.row_count if a.results else 0
            parts.append(
                f"Attempt {i} ({status}):\n"
                f"  SQL: {a.query[:500]}\n"
                f"  Error: {error_msg}\n"
                f"  Rows returned: {row_count}"
            )
        return "\n\n".join(parts)
