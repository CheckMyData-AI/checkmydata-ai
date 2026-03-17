from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.custom_rule import CustomRule


class RuleService:
    async def create(
        self,
        session: AsyncSession,
        **kwargs,
    ) -> CustomRule:
        rule = CustomRule(**kwargs)
        session.add(rule)
        await session.commit()
        await session.refresh(rule)
        return rule

    async def get(
        self,
        session: AsyncSession,
        rule_id: str,
    ) -> CustomRule | None:
        result = await session.execute(
            select(CustomRule).where(CustomRule.id == rule_id),
        )
        return result.scalar_one_or_none()

    async def list_all(
        self,
        session: AsyncSession,
        project_id: str | None = None,
    ) -> list[CustomRule]:
        stmt = select(CustomRule).order_by(CustomRule.created_at.desc())
        if project_id:
            stmt = stmt.where(
                (CustomRule.project_id == project_id) | (CustomRule.project_id.is_(None)),
            )
        else:
            stmt = stmt.where(CustomRule.project_id.is_(None))
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def update(
        self,
        session: AsyncSession,
        rule_id: str,
        **kwargs,
    ) -> CustomRule | None:
        rule = await self.get(session, rule_id)
        if not rule:
            return None
        for key, value in kwargs.items():
            if hasattr(rule, key) and key not in ("id", "created_at"):
                setattr(rule, key, value)
        rule.updated_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(rule)
        return rule

    async def delete(
        self,
        session: AsyncSession,
        rule_id: str,
    ) -> bool:
        rule = await self.get(session, rule_id)
        if not rule:
            return False
        await session.delete(rule)
        await session.commit()
        return True
