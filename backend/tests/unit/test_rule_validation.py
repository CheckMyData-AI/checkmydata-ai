"""Tests for RuleService.validate_rules_against_schema."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.rule_service import RuleService


def _make_rule(rule_id: str, name: str, content: str) -> MagicMock:
    rule = MagicMock()
    rule.id = rule_id
    rule.name = name
    rule.content = content
    return rule


@pytest.fixture
def svc():
    return RuleService()


class TestValidateRulesAgainstSchema:
    @pytest.mark.asyncio
    async def test_empty_known_tables(self, svc: RuleService):
        session = AsyncMock()
        result = await svc.validate_rules_against_schema(session, "proj-1", known_tables=set())
        assert result == []

    @pytest.mark.asyncio
    async def test_no_issues_when_all_tables_exist(self, svc: RuleService):
        rules = [
            _make_rule(
                "r1",
                "Revenue rule",
                "When querying the order_items table, always sum amount.",
            )
        ]
        with patch.object(svc, "list_all", new_callable=AsyncMock, return_value=rules):
            result = await svc.validate_rules_against_schema(
                AsyncMock(),
                "proj-1",
                known_tables={"order_items", "users"},
            )
        assert result == []

    @pytest.mark.asyncio
    async def test_detects_missing_table_reference(self, svc: RuleService):
        rules = [
            _make_rule(
                "r1",
                "Revenue rule",
                "When querying the order_items table, also join invoice_lines.",
            )
        ]
        with patch.object(svc, "list_all", new_callable=AsyncMock, return_value=rules):
            result = await svc.validate_rules_against_schema(
                AsyncMock(),
                "proj-1",
                known_tables={"order_items", "users"},
            )
        assert len(result) == 1
        assert result[0]["rule_name"] == "Revenue rule"
        assert "invoice_lines" in result[0]["missing_tables"]

    @pytest.mark.asyncio
    async def test_no_false_positive_for_plain_words(self, svc: RuleService):
        """Plain English words without underscores should not be flagged."""
        rules = [
            _make_rule(
                "r1",
                "Status rule",
                "When using order_items, status can be active or inactive.",
            )
        ]
        with patch.object(svc, "list_all", new_callable=AsyncMock, return_value=rules):
            result = await svc.validate_rules_against_schema(
                AsyncMock(),
                "proj-1",
                known_tables={"order_items"},
            )
        assert result == []

    @pytest.mark.asyncio
    async def test_empty_content_rule_is_skipped(self, svc: RuleService):
        rules = [_make_rule("r1", "Empty rule", "")]
        with patch.object(svc, "list_all", new_callable=AsyncMock, return_value=rules):
            result = await svc.validate_rules_against_schema(
                AsyncMock(),
                "proj-1",
                known_tables={"orders"},
            )
        assert result == []

    @pytest.mark.asyncio
    async def test_rule_with_no_known_table_ref_is_skipped(self, svc: RuleService):
        """Rules that don't reference any known table at all are skipped."""
        rules = [
            _make_rule(
                "r1",
                "Generic rule",
                "Always format output as markdown with bullet points.",
            )
        ]
        with patch.object(svc, "list_all", new_callable=AsyncMock, return_value=rules):
            result = await svc.validate_rules_against_schema(
                AsyncMock(),
                "proj-1",
                known_tables={"order_items", "users"},
            )
        assert result == []

    @pytest.mark.asyncio
    async def test_case_insensitive_detection(self, svc: RuleService):
        rules = [
            _make_rule(
                "r1",
                "Case rule",
                "Query Order_Items and join User_Sessions for the report.",
            )
        ]
        with patch.object(svc, "list_all", new_callable=AsyncMock, return_value=rules):
            result = await svc.validate_rules_against_schema(
                AsyncMock(),
                "proj-1",
                known_tables={"order_items"},
            )
        assert len(result) == 1
        assert "user_sessions" in result[0]["missing_tables"]
