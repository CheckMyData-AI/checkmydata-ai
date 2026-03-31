import json

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.base import Message
from app.models.chat_session import ChatMessage, ChatSession

WELCOME_MESSAGE = (
    "Hello! I'm your data assistant for this project.\n"
    "\n"
    "Here's what I can do:\n"
    "- **Query your database** in natural language — just ask a question "
    "and I'll generate, validate, and run the SQL for you\n"
    "- **Analyze your codebase** — I understand your project's code "
    "structure, ORM models, and business logic\n"
    "- **Visualize results** — tables, charts (bar, line, pie, scatter), "
    "with export to XLSX/CSV/JSON\n"
    "- **Learn and improve** — I remember patterns, conventions, and your "
    "corrections to get better over time\n"
    "- **Validate data** — I can check for anomalies, verify results "
    "against benchmarks, and investigate suspicious data\n"
    "\n"
    "Feel free to communicate with me in any language you're comfortable "
    "with — I understand and respond in multiple languages.\n"
    "\n"
    "To get started, try asking something like:\n"
    '- "How many users registered this month?"\n'
    '- "Show me the top 10 products by revenue"\n'
    '- "What tables are in my database?"'
)


class ChatService:
    async def create_session(
        self,
        session: AsyncSession,
        project_id: str,
        title: str = "New Chat",
        user_id: str | None = None,
        connection_id: str | None = None,
    ) -> ChatSession:
        chat = ChatSession(
            project_id=project_id,
            title=title,
            user_id=user_id,
            connection_id=connection_id,
        )
        session.add(chat)
        await session.commit()
        await session.refresh(chat)
        return chat

    async def get_session(self, session: AsyncSession, session_id: str) -> ChatSession | None:
        result = await session.execute(select(ChatSession).where(ChatSession.id == session_id))
        return result.scalar_one_or_none()

    async def list_sessions(
        self,
        session: AsyncSession,
        project_id: str,
        user_id: str | None = None,
        skip: int = 0,
        limit: int = 2000,
    ) -> list[ChatSession]:
        stmt = select(ChatSession).where(ChatSession.project_id == project_id)
        if user_id:
            stmt = stmt.where((ChatSession.user_id == user_id) | (ChatSession.user_id.is_(None)))
        stmt = stmt.order_by(ChatSession.created_at.desc()).offset(skip).limit(limit)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def add_message(
        self,
        session: AsyncSession,
        session_id: str,
        role: str,
        content: str,
        metadata: dict | None = None,
        tool_calls_json: str | None = None,
    ) -> ChatMessage:
        msg = ChatMessage(
            session_id=session_id,
            role=role,
            content=content,
            metadata_json=json.dumps(metadata, default=str) if metadata else None,
            tool_calls_json=tool_calls_json,
        )
        session.add(msg)
        await session.commit()
        await session.refresh(msg)
        return msg

    async def get_history_as_messages(
        self, session: AsyncSession, session_id: str, limit: int = 20
    ) -> list[Message]:
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(limit)
        )
        rows = await session.execute(stmt)
        recent = list(reversed(rows.scalars().all()))
        if not recent:
            return []
        result: list[Message] = []
        for m in recent:
            content = m.content
            if m.role == "assistant" and m.metadata_json:
                try:
                    meta = json.loads(m.metadata_json)
                except (json.JSONDecodeError, TypeError):
                    meta = {}
                context_parts: list[str] = []
                if meta.get("viz_type"):
                    context_parts.append(f"viz: {meta['viz_type']}")
                row_count = meta.get("row_count")
                if row_count is not None:
                    context_parts.append(f"{row_count} rows")
                raw = meta.get("raw_result")
                if raw and raw.get("columns"):
                    context_parts.append(f"columns: {', '.join(raw['columns'])}")
                if context_parts:
                    content += (
                        "\n\n[Previous result (completed): " + " | ".join(context_parts) + "]"
                    )
            result.append(Message(role=m.role, content=content))
        return result

    async def update_session_title(
        self,
        session: AsyncSession,
        session_id: str,
        title: str,
    ) -> ChatSession | None:
        chat = await self.get_session(session, session_id)
        if not chat:
            return None
        chat.title = title
        await session.commit()
        await session.refresh(chat)
        return chat

    async def delete_session(self, session: AsyncSession, session_id: str) -> bool:
        chat = await self.get_session(session, session_id)
        if not chat:
            return False
        await session.delete(chat)
        await session.commit()
        return True

    async def ensure_welcome_session(
        self,
        session: AsyncSession,
        project_id: str,
        user_id: str,
        connection_id: str | None = None,
    ) -> tuple[ChatSession, bool]:
        """Return the user's first chat session, creating one with welcome message if needed."""
        count_stmt = (
            select(func.count())
            .select_from(ChatSession)
            .where(
                ChatSession.project_id == project_id,
                (ChatSession.user_id == user_id) | (ChatSession.user_id.is_(None)),
            )
        )
        total = (await session.execute(count_stmt)).scalar_one()
        if total > 0:
            first = await self.list_sessions(session, project_id, user_id=user_id, limit=1)
            return first[0], False

        chat = await self.create_session(
            session,
            project_id,
            title="Welcome",
            user_id=user_id,
            connection_id=connection_id,
        )
        await self.add_message(
            session,
            chat.id,
            role="assistant",
            content=WELCOME_MESSAGE,
            metadata={"response_type": "text", "is_welcome": True},
        )
        return chat, True
