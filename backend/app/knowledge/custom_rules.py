import logging
from dataclasses import dataclass
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class CustomRule:
    name: str
    content: str
    file_path: str
    format: str  # markdown | yaml | text


class CustomRulesEngine:
    """Loads user-defined rules from a configurable directory.

    Rules are markdown/YAML/text files that describe business logic,
    naming conventions, metric formulas, data handling instructions, etc.
    These get injected into the LLM context during query building.
    """

    def __init__(self, rules_dir: str | None = None):
        self._rules_dir = Path(rules_dir or settings.custom_rules_dir)

    def load_rules(self, project_rules_dir: str | None = None) -> list[CustomRule]:
        """Load rules from global dir and optional project-specific dir."""
        rules: list[CustomRule] = []
        dirs_to_scan = [self._rules_dir]
        if project_rules_dir:
            dirs_to_scan.append(Path(project_rules_dir))

        for rules_dir in dirs_to_scan:
            if not rules_dir.exists():
                continue
            for fp in sorted(rules_dir.iterdir()):
                if fp.is_file() and fp.suffix in {".md", ".yaml", ".yml", ".txt"}:
                    try:
                        content = fp.read_text(encoding="utf-8")
                        fmt = "yaml" if fp.suffix in {".yaml", ".yml"} else (
                            "markdown" if fp.suffix == ".md" else "text"
                        )
                        rules.append(
                            CustomRule(
                                name=fp.stem,
                                content=content,
                                file_path=str(fp),
                                format=fmt,
                            )
                        )
                    except Exception as e:
                        logger.warning("Failed to load rule %s: %s", fp, e)

        logger.info("Loaded %d custom rules", len(rules))
        return rules

    async def load_db_rules(
        self, project_id: str | None = None,
    ) -> list[CustomRule]:
        """Load rules stored in the database."""
        try:
            from app.models.base import async_session_factory
            from app.services.rule_service import RuleService

            svc = RuleService()
            async with async_session_factory() as session:
                db_rules = await svc.list_all(session, project_id=project_id)
            return [
                CustomRule(
                    name=r.name,
                    content=r.content,
                    file_path=f"db:{r.id}",
                    format=r.format,
                )
                for r in db_rules
            ]
        except Exception as e:
            logger.warning("Failed to load DB rules: %s", e)
            return []

    def rules_to_context(self, rules: list[CustomRule]) -> str:
        """Format rules as context for the LLM prompt."""
        if not rules:
            return ""

        parts = ["## Custom Rules & Business Logic\n"]
        for rule in rules:
            parts.append(f"### {rule.name}")
            parts.append(rule.content)
            parts.append("")

        return "\n".join(parts)
