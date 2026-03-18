"""Extracts lessons from query validation outcomes.

Heuristic extractors fire after every validation loop at zero LLM cost.
An optional LLM analyzer can be triggered for deeper pattern extraction.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.core.query_validation import QueryAttempt, QueryErrorType

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


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


class LearningAnalyzer:
    """Analyzes validation loop results and extracts lessons."""

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

        lessons: list[ExtractedLesson] = []

        if len(attempts) > 1:
            lessons.extend(self._detect_table_preference(attempts, question))
            lessons.extend(self._detect_column_correction(attempts))
            lessons.extend(self._detect_format_discovery(attempts))
            lessons.extend(self._detect_schema_gotcha(attempts))

        lessons.extend(self._detect_performance_hint(attempts))

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
                    source_query=lesson.source_query,
                    source_error=lesson.source_error,
                )
                stored.append(lesson)
            except Exception:
                logger.debug("Failed to store learning: %s", lesson.lesson, exc_info=True)

        if stored:
            await session.commit()
            logger.info(
                "Extracted %d learnings for connection %s", len(stored), connection_id
            )

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

        if error_detail:
            lessons.append(ExtractedLesson(
                category="query_pattern",
                subject=subject,
                lesson=f"User flagged incorrect results for query on {subject}. "
                       f"Detail: {error_detail[:300]}",
                confidence=0.7,
                source_query=query,
                source_error="user_negative_feedback",
            ))

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
                is_success = (
                    next_attempt.results is not None
                    and next_attempt.error is None
                )
                if is_success or (
                    i + 2 < len(attempts) and attempts[-1].error is None
                ):
                    for old_t in removed:
                        for new_t in added:
                            topic = question[:80] if question else "data queries"
                            lessons.append(ExtractedLesson(
                                category="table_preference",
                                subject=old_t,
                                lesson=(
                                    f"Use `{new_t}` instead of `{old_t}` "
                                    f"for {topic}"
                                ),
                                confidence=0.65,
                                source_query=next_attempt.query,
                                source_error=failed.error.message if failed.error else None,
                            ))

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

            if suggested:
                correct_col = suggested[0]
                lessons.append(ExtractedLesson(
                    category="column_usage",
                    subject=subject,
                    lesson=(
                        f"Column `{wrong_col}` does not exist on `{subject}`. "
                        f"Use `{correct_col}` instead."
                    ),
                    confidence=0.7,
                    source_query=failed.query,
                    source_error=failed.error.message,
                ))

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

            if "/ 100" in fixed_q and "/ 100" not in failed_q:
                col_match = re.search(r'(\w+)\s*/\s*100', fixed_q)
                col_name = col_match.group(1) if col_match else "amount"
                lessons.append(ExtractedLesson(
                    category="data_format",
                    subject=subject,
                    lesson=(
                        f"Column `{col_name}` on `{subject}` stores values in "
                        f"cents (integer). Divide by 100 for dollar amounts."
                    ),
                    confidence=0.7,
                    source_query=attempts[i + 1].query,
                ))

            if "/ 1000" in fixed_q and "/ 1000" not in failed_q:
                col_match = re.search(r'(\w+)\s*/\s*1000', fixed_q)
                col_name = col_match.group(1) if col_match else "amount"
                lessons.append(ExtractedLesson(
                    category="data_format",
                    subject=subject,
                    lesson=(
                        f"Column `{col_name}` on `{subject}` stores values in "
                        f"minor units. Divide by 1000 for display values."
                    ),
                    confidence=0.65,
                    source_query=attempts[i + 1].query,
                ))

            if "::text" in fixed_q and "::text" not in failed_q:
                lessons.append(ExtractedLesson(
                    category="data_format",
                    subject=subject,
                    lesson=(
                        f"Some columns on `{subject}` require explicit "
                        f"::text cast for string operations."
                    ),
                    confidence=0.55,
                    source_query=attempts[i + 1].query,
                ))

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

            if "deleted_at is null" in fixed_q and "deleted_at" not in failed_q:
                lessons.append(ExtractedLesson(
                    category="schema_gotcha",
                    subject=subject,
                    lesson=(
                        f"Table `{subject}` uses soft-delete pattern. "
                        f"Always filter with `WHERE deleted_at IS NULL` for active records."
                    ),
                    confidence=0.75,
                    source_query=next_attempt.query,
                    source_error=failed.error.message,
                ))

            if "is_deleted" in fixed_q and "is_deleted" not in failed_q:
                lessons.append(ExtractedLesson(
                    category="schema_gotcha",
                    subject=subject,
                    lesson=(
                        f"Table `{subject}` has `is_deleted` flag. "
                        f"Filter with `WHERE is_deleted = 0` for active records."
                    ),
                    confidence=0.7,
                    source_query=next_attempt.query,
                    source_error=failed.error.message,
                ))

            if (
                failed.error.error_type == QueryErrorType.SYNTAX_ERROR
                and "schema" in failed.error.message.lower()
            ):
                schema_match = re.search(r'(\w+)\.(\w+)', fixed_q)
                if schema_match and '.' not in failed_q.split('from')[-1].split('join')[0][:50]:
                    schema_name = schema_match.group(1)
                    lessons.append(ExtractedLesson(
                        category="schema_gotcha",
                        subject=subject,
                        lesson=(
                            f"Tables in this database require schema prefix "
                            f"`{schema_name}`. Use `{schema_name}.{subject}` format."
                        ),
                        confidence=0.8,
                        source_query=next_attempt.query,
                        source_error=failed.error.message,
                    ))

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
            fixed_q = next_attempt.query.lower()
            failed_q = attempt.query.lower()

            hints: list[str] = []
            if "limit" in fixed_q and "limit" not in failed_q:
                hints.append("add LIMIT clause")
            if re.search(r'where.*(?:date|created|updated)', fixed_q) and not re.search(
                r'where.*(?:date|created|updated)', failed_q
            ):
                hints.append("filter by date range")

            if hints:
                advice = " and ".join(hints)
                lessons.append(ExtractedLesson(
                    category="performance_hint",
                    subject=subject,
                    lesson=(
                        f"Table `{subject}` can timeout on unfiltered queries. "
                        f"Always {advice} to avoid timeouts."
                    ),
                    confidence=0.7,
                    source_query=next_attempt.query,
                    source_error=attempt.error.message,
                ))

        return lessons
