import logging
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dashboard import Dashboard

logger = logging.getLogger(__name__)


class DashboardService:
    async def create(self, session: AsyncSession, **kwargs) -> Dashboard:
        dashboard = Dashboard(**kwargs)
        session.add(dashboard)
        await session.commit()
        await session.refresh(dashboard)
        return dashboard

    async def get(self, session: AsyncSession, dashboard_id: str) -> Dashboard | None:
        result = await session.execute(
            select(Dashboard).where(Dashboard.id == dashboard_id),
        )
        return result.scalar_one_or_none()

    async def list_for_project(
        self,
        session: AsyncSession,
        project_id: str,
        user_id: str,
    ) -> list[Dashboard]:
        stmt = (
            select(Dashboard)
            .where(
                Dashboard.project_id == project_id,
                or_(
                    Dashboard.creator_id == user_id,
                    Dashboard.is_shared == True,  # noqa: E712
                ),
            )
            .order_by(Dashboard.updated_at.desc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    ALLOWED_UPDATE_FIELDS = {"title", "layout_json", "cards_json", "is_shared"}

    async def update(
        self,
        session: AsyncSession,
        dashboard_id: str,
        **kwargs,
    ) -> Dashboard | None:
        dashboard = await self.get(session, dashboard_id)
        if not dashboard:
            return None
        for key, value in kwargs.items():
            if key in self.ALLOWED_UPDATE_FIELDS:
                setattr(dashboard, key, value)
        dashboard.updated_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(dashboard)
        return dashboard

    async def delete(self, session: AsyncSession, dashboard_id: str) -> bool:
        dashboard = await self.get(session, dashboard_id)
        if not dashboard:
            return False
        await session.delete(dashboard)
        await session.commit()
        return True
