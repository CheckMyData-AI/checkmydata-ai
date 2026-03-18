import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.llm.base import Message
from app.models.chat_session import ChatMessage, ChatSession


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
        result = await session.execute(
            select(ChatSession)
            .where(ChatSession.id == session_id)
            .options(selectinload(ChatSession.messages))
        )
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
        chat = await self.get_session(session, session_id)
        if not chat or not chat.messages:
            return []

        recent = chat.messages[-limit:]
        result: list[Message] = []
        for m in recent:
            content = m.content
            if m.role == "assistant" and m.metadata_json:
                try:
                    meta = json.loads(m.metadata_json)
                except (json.JSONDecodeError, TypeError):
                    meta = {}
                context_parts: list[str] = []
                if meta.get("query"):
                    context_parts.append(f"SQL Query: {meta['query']}")
                if meta.get("viz_type"):
                    context_parts.append(f"Visualization: {meta['viz_type']}")
                row_count = meta.get("row_count")
                if row_count is not None:
                    context_parts.append(f"Rows: {row_count}")
                raw = meta.get("raw_result")
                if raw and raw.get("columns"):
                    context_parts.append(f"Columns: {', '.join(raw['columns'])}")
                    sample = raw.get("rows", [])[:3]
                    if sample:
                        context_parts.append(f"Sample data: {sample}")
                if context_parts:
                    content += "\n\n[Context: " + " | ".join(context_parts) + "]"
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
