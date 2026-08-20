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
                        fmt = (
                            "yaml"
                            if fp.suffix in {".yaml", ".yml"}
                            else ("markdown" if fp.suffix == ".md" else "text")
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

        logger.debug("Loaded %d custom rules", len(rules))
        return rules

    async def load_db_rules(
        self,
        project_id: str | None = None,
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

    def rules_to_context(
        self,
        rules: list[CustomRule],
        *,
        max_chars: int | None = None,
    ) -> str:
        """Format rules as context for the LLM prompt, within a character budget.

        DB-sourced rules include their ID so the agent can reference them for
        update/delete via the ``manage_custom_rules`` tool.

        F-RULE-03. This had no cap, and the size is not bounded by anything the code
        controls: rules come from files an operator drops in ``rules/`` and from rows a
        user adds through ``manage_custom_rules``. Two of five callers had invented their
        own caps — 2000 chars in the orchestrator, 3000 in the SQL agent, unrelated magic
        numbers — and three had none at all.

        Two things are deliberate about how it truncates:

        * **Whole rules, never half of one.** Cutting mid-rule hands the model a truncated
          instruction it may still follow, which is worse than not sending it. The old
          per-caller code sliced the string.
        * **The notice carries a count.** ``"... (truncated)"`` says something was cut
          without saying what, so the agent cannot tell the user its answer may ignore
          rules they wrote. "N of M omitted" is the difference between a degradation the
          consumer can report and one it cannot see — `vision.md` §7, not formatting.

        The budget lives here rather than at the call sites so an unbounded caller is
        impossible rather than unlikely.
        """
        if not rules:
            return ""

        budget = settings.rules_context_max_chars if max_chars is None else max_chars
        header = "## Custom Rules & Business Logic\n"
        parts = [header]
        used = len(header)
        included = 0

        cut: str | None = None
        for rule in rules:
            if rule.file_path.startswith("db:"):
                heading = f"### {rule.name}  (id: {rule.file_path[3:]})"
            else:
                heading = f"### {rule.name}"
            block = f"{heading}\n{rule.content}\n"
            # +1 for the join's newline between blocks.
            if budget > 0 and used + len(block) + 1 > budget:
                if included:
                    break
                # One rule alone larger than the whole budget. Every option is bad and
                # they are not equally bad: keeping it whole blows the prompt the budget
                # exists to protect, dropping it silently loses business logic the user
                # wrote, and cutting it hands the model half an instruction. Cutting and
                # SAYING SO is the only one the agent can report — the same rule as
                # everywhere else here, that a degradation the consumer cannot see is the
                # dangerous kind. A budget too small for one rule is a configuration
                # problem, and the notice is what makes it visible.
                room = max(0, budget - len(heading) - 1)
                parts.append(heading)
                parts.append(rule.content[:room])
                parts.append("")
                cut = rule.name
                included += 1
                used = budget
                continue
            parts.append(heading)
            parts.append(rule.content)
            parts.append("")
            used += len(block) + 1
            included += 1

        omitted = len(rules) - included
        if cut:
            parts.append(
                f"[rule '{cut}' was cut short to fit the context budget — it is longer "
                "than the whole budget, so raise RULES_CONTEXT_MAX_CHARS or split it.]"
            )
        if omitted:
            parts.append(
                f"[{omitted} of {len(rules)} rules omitted to fit the context budget — "
                "answers may not reflect them. Ask about a specific rule to see it.]"
            )

        return "\n".join(parts)
