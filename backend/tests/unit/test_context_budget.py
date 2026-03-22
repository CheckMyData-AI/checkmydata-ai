from __future__ import annotations

from app.core.context_budget import (
    CHARS_PER_TOKEN,
    BudgetAllocation,
    ContextBudgetManager,
    _estimate,
)


class TestEstimate:
    def test_empty_string(self):
        assert _estimate("") == 0

    def test_short_string(self):
        assert _estimate("ab") == 1

    def test_exact_multiple(self):
        text = "a" * (CHARS_PER_TOKEN * 10)
        assert _estimate(text) == 10

    def test_rounds_down(self):
        text = "a" * (CHARS_PER_TOKEN * 3 + 1)
        assert _estimate(text) == 3


class TestBudgetAllocation:
    def test_fields(self):
        ba = BudgetAllocation(
            system_prompt="sys",
            chat_history_tokens=100,
            schema_text="schema",
            rules_text="rules",
            learnings_text="learn",
            overview_text="overview",
        )
        assert ba.system_prompt == "sys"
        assert ba.chat_history_tokens == 100


class TestContextBudgetManager:
    def test_default_budget(self):
        mgr = ContextBudgetManager()
        assert mgr._total == 16000

    def test_custom_budget(self):
        mgr = ContextBudgetManager(total_budget=8000)
        assert mgr._total == 8000

    def test_allocate_returns_budget_allocation(self):
        mgr = ContextBudgetManager(total_budget=16000)
        result = mgr.allocate(system_prompt="Hello")
        assert isinstance(result, BudgetAllocation)

    def test_system_prompt_preserved(self):
        mgr = ContextBudgetManager(total_budget=16000)
        prompt = "System prompt text"
        result = mgr.allocate(system_prompt=prompt)
        assert result.system_prompt == prompt

    def test_chat_history_budget_capped_at_30_percent(self):
        mgr = ContextBudgetManager(total_budget=10000)
        result = mgr.allocate(system_prompt="x")
        assert result.chat_history_tokens <= int(10000 * 0.30)

    def test_schema_truncated_when_too_large(self):
        mgr = ContextBudgetManager(total_budget=100)
        large_schema = "x" * 10000
        result = mgr.allocate(system_prompt="hi", schema_text=large_schema)
        assert "truncated" in result.schema_text
        assert len(result.schema_text) < len(large_schema)

    def test_schema_kept_when_fits(self):
        mgr = ContextBudgetManager(total_budget=100000)
        schema = "small schema"
        result = mgr.allocate(system_prompt="hi", schema_text=schema)
        assert result.schema_text == schema

    def test_rules_truncated_when_too_large(self):
        mgr = ContextBudgetManager(total_budget=100)
        large_rules = "r" * 10000
        result = mgr.allocate(system_prompt="hi", rules_text=large_rules)
        assert "truncated" in result.rules_text

    def test_learnings_truncated_when_too_large(self):
        mgr = ContextBudgetManager(total_budget=100)
        result = mgr.allocate(system_prompt="hi", learnings_text="L" * 10000)
        assert "truncated" in result.learnings_text

    def test_overview_fills_remaining(self):
        mgr = ContextBudgetManager(total_budget=100000)
        result = mgr.allocate(
            system_prompt="hi",
            overview_text="overview text",
        )
        assert result.overview_text == "overview text"

    def test_overview_truncated_when_budget_exhausted(self):
        mgr = ContextBudgetManager(total_budget=50)
        result = mgr.allocate(
            system_prompt="a" * 200,
            overview_text="overview " * 100,
        )
        assert "truncated" in result.overview_text

    def test_empty_texts_pass_through(self):
        mgr = ContextBudgetManager(total_budget=16000)
        result = mgr.allocate(system_prompt="hi")
        assert result.schema_text == ""
        assert result.rules_text == ""
        assert result.learnings_text == ""
        assert result.overview_text == ""

    def test_huge_system_prompt_zeroes_remaining(self):
        mgr = ContextBudgetManager(total_budget=10)
        big_prompt = "x" * 1000
        result = mgr.allocate(
            system_prompt=big_prompt,
            schema_text="schema",
            rules_text="rules",
        )
        assert result.system_prompt == big_prompt
        assert result.chat_history_tokens == 0


class TestTruncate:
    def test_empty_returns_empty(self):
        assert ContextBudgetManager._truncate("", 100) == ""

    def test_short_text_unchanged(self):
        text = "hello"
        assert ContextBudgetManager._truncate(text, 100) == text

    def test_long_text_truncated(self):
        text = "a" * 1000
        result = ContextBudgetManager._truncate(text, 10)
        max_chars = 10 * CHARS_PER_TOKEN
        assert result.startswith("a" * max_chars)
        assert result.endswith("... (truncated to fit context budget)")

    def test_exact_boundary(self):
        budget = 5
        text = "a" * (budget * CHARS_PER_TOKEN)
        assert ContextBudgetManager._truncate(text, budget) == text

    def test_one_over_boundary(self):
        budget = 5
        text = "a" * (budget * CHARS_PER_TOKEN + 1)
        result = ContextBudgetManager._truncate(text, budget)
        assert "truncated" in result
