"""Tests for owner-attributed budget gate + usage sink (H5)."""

import pytest

from app.services import sync_budget


class _FakeProject:
    def __init__(self, owner_id):
        self.owner_id = owner_id


@pytest.fixture
def patch_owner(monkeypatch):
    def _set(owner):
        async def _resolve(session, project_id):
            return owner

        monkeypatch.setattr(sync_budget, "resolve_owner_user_id", _resolve)

    return _set


async def test_preflight_disabled_always_ok(monkeypatch, patch_owner):
    monkeypatch.setattr(sync_budget.settings, "sync_budget_enforcement_enabled", False)
    patch_owner("u1")
    ok, reason, owner = await sync_budget.preflight_owner_budget(None, "p1")
    assert ok is True and reason is None and owner == "u1"


async def test_preflight_blocks_when_budget_message(monkeypatch, patch_owner):
    monkeypatch.setattr(sync_budget.settings, "sync_budget_enforcement_enabled", True)
    patch_owner("u1")

    async def _budget(db, user_id):
        return "daily token budget exhausted"

    monkeypatch.setattr(sync_budget._usage_svc, "check_token_budget", _budget)
    ok, reason, owner = await sync_budget.preflight_owner_budget(None, "p1")
    assert ok is False and "budget" in reason and owner == "u1"


async def test_preflight_owner_missing(monkeypatch):
    """C1: missing owner degrades (unenforced), does NOT block."""
    monkeypatch.setattr(sync_budget.settings, "sync_budget_enforcement_enabled", True)

    async def _resolve(session, project_id):
        return None

    monkeypatch.setattr(sync_budget, "resolve_owner_user_id", _resolve)
    ok, reason, owner = await sync_budget.preflight_owner_budget(None, "p1")
    assert ok is True and reason is None and owner is None
