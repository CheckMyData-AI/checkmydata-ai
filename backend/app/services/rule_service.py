import logging
from datetime import UTC, datetime
from typing import Any

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

    async def validate_rules_against_schema(
        self,
        session: AsyncSession,
        project_id: str,
        known_tables: set[str],
    ) -> list[dict]:
        """Check rules for references to tables that no longer exist.

        Extracts identifiers from rule content that structurally resemble
        table names (contain underscores or match known table naming
        patterns) and flags any that are **not** in *known_tables*.

        Returns a list of ``{"rule_id", "rule_name", "missing_tables"}`` dicts.
        """
        import re

        if not known_tables:
            return []
        known_lower = {t.lower() for t in known_tables}
        identifier_re = re.compile(r"\b([a-z][a-z0-9_]*[a-z0-9])\b")
        rules = await self.list_all(session, project_id=project_id)
        issues: list[dict] = []
        for rule in rules:
            content_lower = (rule.content or "").lower()
            if not content_lower:
                continue
            identifiers = set(identifier_re.findall(content_lower))
            has_known_ref = bool(identifiers & known_lower)
            if not has_known_ref:
                continue
            candidates = identifiers - known_lower
            missing = [w for w in candidates if "_" in w and len(w) >= 4]
            if missing:
                issues.append(
                    {
                        "rule_id": str(rule.id),
                        "rule_name": rule.name,
                        "missing_tables": sorted(missing),
                    }
                )
        return issues

    async def ensure_default_rule(
        self,
        session: AsyncSession,
        project_id: str,
        *,
        connection_id: str | None = None,
        llm_router: Any = None,
    ) -> CustomRule | None:
        """Create the default business-metrics rule for a project if not yet initialized.

        Returns the created rule, or None if the project was already initialized.
        Does NOT commit — caller is responsible for committing the transaction.

        When ``llm_router`` and ``connection_id`` are provided, the rule
        content is generated *schema-aware* via the LLM (T10). Falls back
        to the static template on any failure.
        """
        from app.models.project import Project
        from app.services.default_rule_template import (
            DEFAULT_RULE_NAME,
            generate_default_rule_content,
            get_default_rule_content,
        )

        project = await session.get(Project, project_id)
        if not project or project.default_rule_initialized:
            return None

        content: str
        if llm_router is not None and connection_id:
            content = await generate_default_rule_content(
                session, connection_id, llm_router
            )
        else:
            content = get_default_rule_content()

        rule = CustomRule(
            project_id=project_id,
            name=DEFAULT_RULE_NAME,
            content=content,
            format="markdown",
            is_default=True,
        )
        session.add(rule)
        project.default_rule_initialized = True
        logger.info("Created default rule for project %s", project_id[:8])
        return rule
