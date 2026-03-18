import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.custom_rule import CustomRule

logger = logging.getLogger(__name__)


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

    ALLOWED_RULE_UPDATE_FIELDS = {"name", "content", "format", "is_default"}

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
            if key in self.ALLOWED_RULE_UPDATE_FIELDS:
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

    async def ensure_default_rule(
        self,
        session: AsyncSession,
        project_id: str,
    ) -> CustomRule | None:
        """Create the default business-metrics rule for a project if not yet initialized.

        Returns the created rule, or None if the project was already initialized.
        Does NOT commit — caller is responsible for committing the transaction.
        """
        from app.models.project import Project
        from app.services.default_rule_template import (
            DEFAULT_RULE_NAME,
            get_default_rule_content,
        )

        project = await session.get(Project, project_id)
        if not project or project.default_rule_initialized:
            return None

        rule = CustomRule(
            project_id=project_id,
            name=DEFAULT_RULE_NAME,
            content=get_default_rule_content(),
            format="markdown",
            is_default=True,
        )
        session.add(rule)
        project.default_rule_initialized = True
        logger.info("Created default rule for project %s", project_id[:8])
        return rule
