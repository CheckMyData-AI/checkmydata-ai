import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.saved_note import SavedNote

logger = logging.getLogger(__name__)


class NoteService:
    async def create(self, session: AsyncSession, **kwargs) -> SavedNote:
        note = SavedNote(**kwargs)
        session.add(note)
        await session.commit()
        await session.refresh(note)
        return note

    async def get(self, session: AsyncSession, note_id: str) -> SavedNote | None:
        result = await session.execute(
            select(SavedNote).where(SavedNote.id == note_id),
        )
        return result.scalar_one_or_none()

    async def list_by_project(
        self,
        session: AsyncSession,
        project_id: str,
        user_id: str,
    ) -> list[SavedNote]:
        stmt = (
            select(SavedNote)
            .where(SavedNote.project_id == project_id, SavedNote.user_id == user_id)
            .order_by(SavedNote.updated_at.desc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    ALLOWED_UPDATE_FIELDS = {"title", "comment"}

    async def update(
        self,
        session: AsyncSession,
        note_id: str,
        **kwargs,
    ) -> SavedNote | None:
        note = await self.get(session, note_id)
        if not note:
            return None
        for key, value in kwargs.items():
            if key in self.ALLOWED_UPDATE_FIELDS:
                setattr(note, key, value)
        note.updated_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(note)
        return note

    async def update_result(
        self,
        session: AsyncSession,
        note_id: str,
        result_json: str | None,
    ) -> SavedNote | None:
        note = await self.get(session, note_id)
        if not note:
            return None
        note.last_result_json = result_json
        note.last_executed_at = datetime.now(UTC)
        note.updated_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(note)
        return note

    async def delete(self, session: AsyncSession, note_id: str) -> bool:
        note = await self.get(session, note_id)
        if not note:
            return False
        await session.delete(note)
        await session.commit()
        return True
