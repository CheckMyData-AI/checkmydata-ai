"""Tests for cross-tenant scoping of ToolDispatcher._handle_manage_rules (F-RULE-05).

A prompted agent must not be able to update or delete a rule that belongs to a
different project, nor a global rule (project_id=None). For both ``update`` and
``delete`` the handler loads the rule first and verifies ``rule.project_id ==
ctx.project_id`` before mutating.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.base import AgentContext
from app.agents.tool_dispatcher import ToolDispatcher
from app.core.workflow_tracker import WorkflowTracker


@pytest.fixture
def mock_tracker():
    t = MagicMock(spec=WorkflowTracker)
    t.emit = AsyncMock()

    @asynccontextmanager
    async def fake_step(wf_id, step, detail="", **kwargs):
        yield

    t.step = MagicMock(side_effect=fake_step)
    return t


def _make_dispatcher(mock_tracker):
    return ToolDispatcher(
        sql_agent=MagicMock(),
        knowledge_agent=MagicMock(),
        mcp_source_agent=MagicMock(),
        validator=MagicMock(),
        tracker=mock_tracker,
        wf_sql_results={},
        wf_enriched={},
        git_agent=None,
    )


@pytest.fixture
def context():
    return AgentContext(
        project_id="proj-1",
        connection_config=None,
        user_question="Update a rule",
        chat_history=[],
        llm_router=MagicMock(),
        tracker=MagicMock(),
        workflow_id="wf-1",
        user_id="user-1",
    )


def _patch_services(monkeypatch, *, rule_get_return, role="editor"):
    """Patch the locally-imported services and session factory.

    Returns the ``rule_svc`` mock so tests can assert update/delete were (not)
    called.
    """
    rule_svc = MagicMock()
    rule_svc.get = AsyncMock(return_value=rule_get_return)
    rule_svc.update = AsyncMock(
        return_value=SimpleNamespace(name="n", id="r1", content="c"),
    )
    rule_svc.delete = AsyncMock(return_value=True)

    membership_svc = MagicMock()
    membership_svc.get_role = AsyncMock(return_value=role)

    monkeypatch.setattr("app.services.rule_service.RuleService", lambda: rule_svc)
    monkeypatch.setattr("app.services.membership_service.MembershipService", lambda: membership_svc)

    @asynccontextmanager
    async def fake_session_factory():
        yield MagicMock()

    monkeypatch.setattr("app.models.base.async_session_factory", fake_session_factory)
    return rule_svc


class TestManageRulesCrossTenant:
    @pytest.mark.asyncio
    async def test_update_rule_in_another_project_denied(self, mock_tracker, context, monkeypatch):
        foreign_rule = SimpleNamespace(id="r1", project_id="other-proj", name="x", content="y")
        rule_svc = _patch_services(monkeypatch, rule_get_return=foreign_rule)
        d = _make_dispatcher(mock_tracker)

        out = await d._handle_manage_rules(
            {"action": "update", "rule_id": "r1", "content": "hacked"},
            context,
            "wf-1",
        )

        assert "Permission denied" in out
        assert "another project" in out
        rule_svc.update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_delete_global_rule_denied(self, mock_tracker, context, monkeypatch):
        global_rule = SimpleNamespace(id="r1", project_id=None, name="x", content="y")
        rule_svc = _patch_services(monkeypatch, rule_get_return=global_rule)
        d = _make_dispatcher(mock_tracker)

        out = await d._handle_manage_rules(
            {"action": "delete", "rule_id": "r1"},
            context,
            "wf-1",
        )

        assert "Permission denied" in out
        assert "another project" in out
        rule_svc.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_missing_rule_not_found(self, mock_tracker, context, monkeypatch):
        rule_svc = _patch_services(monkeypatch, rule_get_return=None)
        d = _make_dispatcher(mock_tracker)

        out = await d._handle_manage_rules(
            {"action": "update", "rule_id": "ghost", "content": "x"},
            context,
            "wf-1",
        )

        assert "not found" in out
        rule_svc.update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_rule_in_own_project_succeeds(self, mock_tracker, context, monkeypatch):
        own_rule = SimpleNamespace(id="r1", project_id="proj-1", name="x", content="y")
        rule_svc = _patch_services(monkeypatch, rule_get_return=own_rule)
        rule_svc.update = AsyncMock(
            return_value=SimpleNamespace(name="updated", id="r1", content="new content"),
        )
        d = _make_dispatcher(mock_tracker)

        out = await d._handle_manage_rules(
            {"action": "update", "rule_id": "r1", "content": "new content"},
            context,
            "wf-1",
        )

        assert "updated successfully" in out
        rule_svc.update.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_rule_in_own_project_succeeds(self, mock_tracker, context, monkeypatch):
        own_rule = SimpleNamespace(id="r1", project_id="proj-1", name="x", content="y")
        rule_svc = _patch_services(monkeypatch, rule_get_return=own_rule)
        d = _make_dispatcher(mock_tracker)

        out = await d._handle_manage_rules(
            {"action": "delete", "rule_id": "r1"},
            context,
            "wf-1",
        )

        assert "deleted successfully" in out
        rule_svc.delete.assert_awaited_once()
