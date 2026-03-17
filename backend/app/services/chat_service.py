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
    ) -> ChatSession:
        chat = ChatSession(project_id=project_id, title=title, user_id=user_id)
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
    ) -> list[ChatSession]:
        stmt = select(ChatSession).where(ChatSession.project_id == project_id)
        if user_id:
            stmt = stmt.where((ChatSession.user_id == user_id) | (ChatSession.user_id.is_(None)))
        stmt = stmt.order_by(ChatSession.created_at.desc())
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def add_message(
        self,
        session: AsyncSession,
        session_id: str,
        role: str,
        content: str,
        metadata: dict | None = None,
    ) -> ChatMessage:
        msg = ChatMessage(
            session_id=session_id,
            role=role,
            content=content,
            metadata_json=json.dumps(metadata) if metadata else None,
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
        return [Message(role=m.role, content=m.content) for m in recent]

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
