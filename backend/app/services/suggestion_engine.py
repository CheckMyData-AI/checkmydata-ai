"""AI-first query suggestion engine with template fallback.

When an :class:`LLMRouter` is wired, :meth:`get_suggestions` lets the LLM
compose schema-aware prompts based on recent user history, grounded in
the project's DB index. The template-based fallback below preserves
fully offline behaviour (tests, self-hosted deployments without API
keys).
"""

from __future__ import annotations

import json
import logging
import random
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.models.chat_session import ChatMessage, ChatSession
from app.models.db_index import DbIndex

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.llm.router import LLMRouter

logger = logging.getLogger(__name__)


_SUGGESTIONS_SYSTEM_PROMPT = """You generate query-starter suggestions for
a database assistant.

Inputs you receive:
  - ``tables``: list of {table, relevance, notable_columns}
  - ``recent_questions``: up to 10 recent user questions, newest first

Rules:
  - Return ONLY a JSON array of {text, source: "schema"|"history"}.
  - Generate up to ``limit`` suggestions.
  - Every ``text`` is a short (< 100 char) natural-language question a
    user would type; never SQL.
  - Prefer novel angles on the data (trends, anomalies, top-N, joins).
  - Reuse table / column names verbatim from the schema.
  - Never repeat a question already in ``recent_questions``.
"""

TABLE_TEMPLATES = [
    "How many records are in {table}?",
    "Show me the latest 10 rows from {table}",
    "What is the daily count of {table} over the last month?",
    "Show me the distribution of {column} in {table}",
    "What are the top 10 {table} by {column}?",
    "Show me {table} records created in the last 30 days",
    "Summarize the key metrics from {table}",
    "Are there any duplicate rows in {table}?",
]

FOLLOWUP_TEMPLATES_QUERY = [
    "Show this as a pie chart",
    "Break this down by month",
    "Compare with the previous period",
    "Show only the top 5 results",
    "Export this data as a table",
    "What is the trend over time?",
]

FOLLOWUP_TEMPLATES_AGGREGATE = [
    "Show the percentage breakdown",
    "What is the average instead of the count?",
    "Group this by a different dimension",
]


class SuggestionEngine:
    def __init__(self, llm_router: LLMRouter | None = None) -> None:
        self._llm_router = llm_router

    async def llm_suggestions(
        self,
        db: AsyncSession,
        user_id: str,
        project_id: str,
        connection_id: str,
        limit: int = 5,
    ) -> list[dict]:
        """Ask the LLM for suggestions, grounded in db_index + recent chat.

        Returns ``[]`` when no LLM router is wired or on any error so the
        caller can fall back to the template engine.
        """
        if self._llm_router is None:
            return []

        from app.llm.base import Message

        index_rows = await db.execute(
            select(DbIndex)
            .where(
                DbIndex.connection_id == connection_id,
                DbIndex.is_active.is_(True),
                DbIndex.relevance_score >= 3,
            )
            .order_by(DbIndex.relevance_score.desc())
            .limit(15)
        )
        tables: list[dict[str, Any]] = []
        for entry in index_rows.scalars().all():
            notable = self._pick_interesting_column(entry)
            tables.append(
                {
                    "table": entry.table_name,
                    "relevance": entry.relevance_score,
                    "notable_columns": [notable] if notable else [],
                }
            )

        hist_rows = (
            await db.execute(
                select(ChatMessage.content)
                .join(ChatSession, ChatMessage.session_id == ChatSession.id)
                .where(
                    ChatSession.project_id == project_id,
                    ChatSession.user_id == user_id,
                    ChatMessage.role == "user",
                )
                .order_by(ChatMessage.created_at.desc())
                .limit(10)
            )
        ).all()
        recent_questions = [r[0] for r in hist_rows if r[0]]

        payload = json.dumps(
            {
                "tables": tables,
                "recent_questions": recent_questions,
                "limit": limit,
            },
            default=str,
        )

        try:
            resp = await self._llm_router.complete(
                messages=[
                    Message(role="system", content=_SUGGESTIONS_SYSTEM_PROMPT),
                    Message(role="user", content=payload),
                ],
                temperature=0.4,
                max_tokens=500,
            )
        except Exception:
            logger.debug("LLM suggestions call failed", exc_info=True)
            return []

        if not resp or not resp.content:
            return []

        raw = resp.content.strip()
        if raw.startswith("```"):
            import re

            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)

        try:
            parsed = json.loads(raw)
        except Exception:
            logger.debug("LLM suggestion JSON parse failed")
            return []

        if not isinstance(parsed, list):
            return []

        cleaned: list[dict] = []
        seen: set[str] = set()
        for item in parsed:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "")).strip()
            if not text or text.lower() in seen:
                continue
            seen.add(text.lower())
            cleaned.append(
                {
                    "text": text[:200],
                    "source": (
                        "history" if str(item.get("source")) == "history" else "schema"
                    ),
                }
            )
            if len(cleaned) >= limit:
                break
        return cleaned

    async def schema_based_suggestions(
        self,
        db: AsyncSession,
        connection_id: str,
        limit: int = 5,
    ) -> list[dict]:
        result = await db.execute(
            select(DbIndex)
            .where(
                DbIndex.connection_id == connection_id,
                DbIndex.is_active.is_(True),
                DbIndex.relevance_score >= 3,
            )
            .order_by(DbIndex.relevance_score.desc(), DbIndex.row_count.desc())
            .limit(20)
        )
        entries = list(result.scalars().all())
        if not entries:
            return []

        suggestions: list[dict] = []
        used_texts: set[str] = set()

        for entry in entries:
            column = self._pick_interesting_column(entry)
            candidates = list(TABLE_TEMPLATES)
            random.shuffle(candidates)

            for template in candidates:
                if len(suggestions) >= limit:
                    break
                if "{column}" in template and not column:
                    continue
                text = template.format(table=entry.table_name, column=column or "")
                if text in used_texts:
                    continue
                used_texts.add(text)
                suggestions.append(
                    {
                        "text": text,
                        "source": "schema",
                        "table": entry.table_name,
                    }
                )
                break

            if len(suggestions) >= limit:
                break

        return suggestions[:limit]

    async def history_based_suggestions(
        self,
        db: AsyncSession,
        user_id: str,
        project_id: str,
        limit: int = 3,
    ) -> list[dict]:
        stmt = (
            select(ChatMessage.content, ChatMessage.metadata_json)
            .join(ChatSession, ChatMessage.session_id == ChatSession.id)
            .where(
                ChatSession.project_id == project_id,
                ChatSession.user_id == user_id,
                ChatMessage.role == "assistant",
                ChatMessage.metadata_json.isnot(None),
            )
            .order_by(ChatMessage.created_at.desc())
            .limit(50)
        )
        rows = (await db.execute(stmt)).all()

        suggestions: list[dict] = []
        seen: set[str] = set()

        for content, meta_json in rows:
            if len(suggestions) >= limit:
                break
            if not meta_json:
                continue
            try:
                meta = json.loads(meta_json)
            except (json.JSONDecodeError, TypeError):
                continue

            query = meta.get("query")
            question = meta.get("question", "")
            if not query or meta.get("error"):
                continue
            if not question or len(question) < 10:
                continue

            variation = self._make_variation(question)
            if variation in seen:
                continue
            seen.add(variation)
            suggestions.append(
                {
                    "text": variation,
                    "source": "history",
                }
            )

        return suggestions[:limit]

    async def get_suggestions(
        self,
        db: AsyncSession,
        user_id: str,
        project_id: str,
        connection_id: str,
        limit: int = 5,
    ) -> list[dict]:
        if self._llm_router is not None:
            llm = await self.llm_suggestions(
                db, user_id, project_id, connection_id, limit
            )
            if llm:
                return llm

        history_limit = min(2, limit)
        schema_limit = limit - history_limit + 2

        history = await self.history_based_suggestions(db, user_id, project_id, history_limit)
        schema = await self.schema_based_suggestions(db, connection_id, schema_limit)

        seen: set[str] = set()
        merged: list[dict] = []
        for s in history + schema:
            text_lower = s["text"].lower().strip()
            if text_lower not in seen:
                seen.add(text_lower)
                merged.append(s)

        return merged[:limit]

    @staticmethod
    def generate_followups(
        query: str,
        columns: list[str],
        row_count: int,
    ) -> list[str]:
        followups: list[str] = []

        has_aggregate = any(
            kw in query.lower() for kw in ("count(", "sum(", "avg(", "group by", "having")
        )

        pool = list(FOLLOWUP_TEMPLATES_QUERY)
        if has_aggregate:
            pool.extend(FOLLOWUP_TEMPLATES_AGGREGATE)

        if row_count > 1 and len(columns) >= 2:
            pool.append(f"Sort by {columns[-1]} in descending order")

        random.shuffle(pool)
        seen: set[str] = set()
        for text in pool:
            if len(followups) >= 3:
                break
            low = text.lower()
            if low not in seen:
                seen.add(low)
                followups.append(text)

        return followups

    @staticmethod
    def _pick_interesting_column(entry: DbIndex) -> str | None:
        if entry.column_distinct_values_json and entry.column_distinct_values_json != "{}":
            try:
                distinct = json.loads(entry.column_distinct_values_json)
                candidates = [
                    col
                    for col, vals in distinct.items()
                    if isinstance(vals, list) and 2 <= len(vals) <= 50
                ]
                if candidates:
                    return candidates[0]
            except (json.JSONDecodeError, TypeError):
                pass

        if entry.column_notes_json and entry.column_notes_json != "{}":
            try:
                notes = json.loads(entry.column_notes_json)
                if notes:
                    return next(iter(notes))
            except (json.JSONDecodeError, TypeError):
                pass

        return None

    @staticmethod
    def _make_variation(question: str) -> str:
        q = question.strip()
        if q.endswith("?"):
            q = q[:-1].strip()
        prefixes = [
            "Show me ",
            "Tell me ",
            "What is ",
            "What are ",
            "How many ",
            "List ",
            "Get ",
            "Find ",
        ]
        for prefix in prefixes:
            if q.lower().startswith(prefix.lower()):
                return q
        return q
