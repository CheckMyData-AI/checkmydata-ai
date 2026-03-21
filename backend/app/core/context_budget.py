"""Context Window Budget Manager.

Allocates token budgets across system prompt, chat history, schema,
rules, and tool results so total context stays within model limits.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

CHARS_PER_TOKEN = 4


def _estimate(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


@dataclass
class BudgetAllocation:
    system_prompt: str
    chat_history_tokens: int
    schema_text: str
    rules_text: str
    learnings_text: str
    overview_text: str


class ContextBudgetManager:
    """Priority-based token budget allocator.

    Priority order (highest to lowest):
    1. System prompt (fixed, never truncated)
    2. Chat history (dynamic, trimmed by HistoryTrimmer)
    3. Schema / table map (capped)
    4. Rules (capped)
    5. Learnings (capped)
    6. Project overview (fills remaining)
    """

    def __init__(self, total_budget: int = 16000) -> None:
        self._total = total_budget

    def allocate(
        self,
        system_prompt: str,
        schema_text: str = "",
        rules_text: str = "",
        learnings_text: str = "",
        overview_text: str = "",
    ) -> BudgetAllocation:
        sys_tokens = _estimate(system_prompt)
        remaining = max(0, self._total - sys_tokens)

        history_budget = min(remaining, int(self._total * 0.30))
        remaining -= history_budget

        schema_budget = min(remaining, int(self._total * 0.25))
        schema_text = self._truncate(schema_text, schema_budget)
        remaining -= _estimate(schema_text)

        rules_budget = min(remaining, int(self._total * 0.10))
        rules_text = self._truncate(rules_text, rules_budget)
        remaining -= _estimate(rules_text)

        learnings_budget = min(remaining, int(self._total * 0.08))
        learnings_text = self._truncate(learnings_text, learnings_budget)
        remaining -= _estimate(learnings_text)

        overview_text = self._truncate(overview_text, remaining)

        return BudgetAllocation(
            system_prompt=system_prompt,
            chat_history_tokens=history_budget,
            schema_text=schema_text,
            rules_text=rules_text,
            learnings_text=learnings_text,
            overview_text=overview_text,
        )

    @staticmethod
    def _truncate(text: str, budget_tokens: int) -> str:
        if not text:
            return text
        max_chars = budget_tokens * CHARS_PER_TOKEN
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n... (truncated to fit context budget)"
