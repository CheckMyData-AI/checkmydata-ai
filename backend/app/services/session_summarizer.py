"""Session summarizer for automatic session rotation.

Generates a rich summary of a chat session's history that can be
injected into a new session to preserve conversational context.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.llm.base import Message
from app.models.chat_session import ChatMessage, ChatSession

logger = logging.getLogger(__name__)

CHARS_PER_TOKEN = 4


@dataclass
class SessionSummary:
    text: str
    topics: list[str] = field(default_factory=list)
    message_count: int = 0


async def summarize_session(
    db: AsyncSession,
    session_id: str,
    llm_router,
    preferred_provider: str | None = None,
    model: str | None = None,
) -> SessionSummary:
    """Build a comprehensive summary of *session_id* for session rotation."""
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
    )
    rows = await db.execute(stmt)
    messages = list(rows.scalars().all())

    if not messages:
        return SessionSummary(text="No prior conversation.", message_count=0)

    conversation_parts: list[str] = []
    sql_queries: list[str] = []
    topics: list[str] = []

    for m in messages:
        if m.role == "user":
            topic = (m.content or "")[:100].strip()
            if topic:
                topics.append(topic)
            conversation_parts.append(f"User: {(m.content or '')[:300]}")
        elif m.role == "assistant":
            conversation_parts.append(f"Assistant: {(m.content or '')[:300]}")
            if m.metadata_json:
                try:
                    meta = json.loads(m.metadata_json)
                except (json.JSONDecodeError, TypeError):
                    meta = {}
                q = meta.get("query")
                if q:
                    sql_queries.append(q)

    conversation_text = "\n".join(conversation_parts)
    max_chars = 6000
    if len(conversation_text) > max_chars:
        conversation_text = conversation_text[:max_chars] + "\n…(truncated)"

    sql_section = ""
    if sql_queries:
        sql_section = "\n\nSQL queries executed:\n" + "\n".join(
            f"- {q[:200]}" for q in sql_queries[-10:]
        )

    summary_model = settings.history_summary_model or model
    max_summary_tokens = settings.session_rotation_summary_max_tokens

    prompt_messages = [
        Message(
            role="system",
            content=(
                "You are summarizing a data analysis conversation for continuity. "
                "Create a concise summary (3-5 sentences) covering:\n"
                "1. The main questions the user asked\n"
                "2. Key SQL queries and their results\n"
                "3. Important data insights discovered\n"
                "4. Any rules or preferences established\n"
                "Be factual and specific. Include table/column names when relevant."
            ),
        ),
        Message(
            role="user",
            content=f"Conversation ({len(messages)} messages):\n{conversation_text}{sql_section}",
        ),
    ]

    try:
        resp = await llm_router.complete(
            messages=prompt_messages,
            max_tokens=max_summary_tokens,
            temperature=0.0,
            preferred_provider=preferred_provider,
            model=summary_model,
        )
        summary_text = resp.content.strip()
    except Exception:
        logger.warning("LLM summary for session rotation failed, using fallback", exc_info=True)
        summary_text = _fallback_summary(topics, sql_queries)

    unique_topics = []
    seen: set[str] = set()
    for t in topics:
        short = t[:60]
        if short.lower() not in seen:
            seen.add(short.lower())
            unique_topics.append(short)

    return SessionSummary(
        text=summary_text,
        topics=unique_topics[-10:],
        message_count=len(messages),
    )


def _fallback_summary(topics: list[str], sql_queries: list[str]) -> str:
    parts: list[str] = []
    if topics:
        user_topics = "; ".join(t[:80] for t in topics[-5:])
        parts.append(f"Topics discussed: {user_topics}")
    if sql_queries:
        parts.append(f"SQL queries executed: {len(sql_queries)}")
    return " | ".join(parts) if parts else "Previous conversation context."


async def get_session_title(db: AsyncSession, session_id: str) -> str:
    """Return the title of a session, or a default."""
    result = await db.execute(select(ChatSession.title).where(ChatSession.id == session_id))
    title = result.scalar_one_or_none()
    return title or "Chat"
