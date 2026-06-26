"""Tests for H4 confidence gate and C6 bare-suffix indexing in SQLAgent required-filters."""

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.sql_agent import SQLAgent
from app.connectors.base import ConnectionConfig
from app.models.code_db_sync import CodeDbSync  # used as spec for MagicMock

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent() -> SQLAgent:
    """Minimal SQLAgent construction without real DB/LLM deps."""
    mock_llm = MagicMock()
    mock_llm.complete = AsyncMock()
    mock_vs = MagicMock()
    mock_vs.query = MagicMock(return_value=[])
    mock_rules = MagicMock()
    mock_rules.load_rules = MagicMock(return_value=[])
    mock_rules.load_db_rules = AsyncMock(return_value=[])
    mock_rules.rules_to_context = MagicMock(return_value="")
    return SQLAgent(llm_router=mock_llm, vector_store=mock_vs, rules_engine=mock_rules)


def _make_sync_entry(
    table_name: str,
    required_filters: dict,
    confidence_score: int,
    connection_id: str = "conn-test",
) -> MagicMock:
    """Return a duck-typed stand-in for a CodeDbSync ORM row."""
    entry = MagicMock(spec=CodeDbSync)
    entry.table_name = table_name
    entry.connection_id = connection_id
    entry.required_filters_json = json.dumps(required_filters)
    entry.confidence_score = confidence_score
    entry.column_value_mappings_json = "{}"
    return entry


def _make_conn_cfg(connection_id: str = "conn-test") -> ConnectionConfig:
    return ConnectionConfig(
        db_type="postgres",
        db_host="localhost",
        db_port=5432,
        db_name="testdb",
        db_user="user",
        connection_id=connection_id,
    )


def _patch_db(monkeypatch, sync_entries: list) -> None:
    """Monkeypatch CodeDbSyncService.get_sync, DbIndexService.get_index,
    async_session_factory, and the min-confidence threshold."""

    async def fake_get_sync(self, session, connection_id):  # noqa: ANN001
        return sync_entries

    async def fake_get_index(self, session, connection_id):  # noqa: ANN001
        return []

    @asynccontextmanager
    async def fake_session_factory():
        yield MagicMock()

    monkeypatch.setattr(
        "app.services.code_db_sync_service.CodeDbSyncService.get_sync",
        fake_get_sync,
    )
    monkeypatch.setattr(
        "app.services.db_index_service.DbIndexService.get_index",
        fake_get_index,
    )
    monkeypatch.setattr("app.models.base.async_session_factory", fake_session_factory)
    monkeypatch.setattr("app.config.settings.sync_min_confidence_to_enforce_filters", 2)


# ---------------------------------------------------------------------------
# H4: low-confidence entries must NOT be enforced
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_low_confidence_filters_not_enforced(monkeypatch):
    """Confidence 1 < threshold 2 → table absent from required-filter dict."""
    agent = _make_agent()
    cfg = _make_conn_cfg()
    _patch_db(monkeypatch, [_make_sync_entry("orders", {"status": "= 1"}, confidence_score=1)])

    result = await agent._load_required_filters_by_table(cfg)

    assert "orders" not in result, (
        f"Low-confidence entry (score=1 < threshold=2) must not appear in required filters, "
        f"got: {result}"
    )


@pytest.mark.asyncio
async def test_sufficient_confidence_filters_are_enforced(monkeypatch):
    """Confidence 3 >= threshold 2 → table IS included in required-filter dict."""
    agent = _make_agent()
    cfg = _make_conn_cfg()
    _patch_db(monkeypatch, [_make_sync_entry("orders", {"status": "= 1"}, confidence_score=3)])

    result = await agent._load_required_filters_by_table(cfg)

    assert "orders" in result, (
        f"High-confidence entry (score=3 >= 2) must be enforced, got: {result}"
    )


@pytest.mark.asyncio
async def test_threshold_boundary_exactly_equal_passes(monkeypatch):
    """Confidence exactly equal to threshold (2 == 2) → entry IS enforced."""
    agent = _make_agent()
    cfg = _make_conn_cfg()
    _patch_db(monkeypatch, [_make_sync_entry("orders", {"status": "= 1"}, confidence_score=2)])

    result = await agent._load_required_filters_by_table(cfg)

    assert "orders" in result, (
        f"Entry with confidence == threshold (2) should be enforced, got: {result}"
    )


# ---------------------------------------------------------------------------
# C6: schema-qualified table names must also be indexed under bare suffix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_qualified_table_indexed_under_bare_suffix(monkeypatch):
    """'analytics.orders' with sufficient confidence → appears under BOTH
    'analytics.orders' AND bare 'orders' in the returned dict."""
    agent = _make_agent()
    cfg = _make_conn_cfg()
    _patch_db(
        monkeypatch,
        [_make_sync_entry("analytics.orders", {"tenant_id": "= 42"}, confidence_score=5)],
    )

    result = await agent._load_required_filters_by_table(cfg)

    assert "analytics.orders" in result, (
        f"Qualified key 'analytics.orders' must be in result, got keys: {list(result.keys())}"
    )
    assert "orders" in result, (
        f"Bare suffix key 'orders' must also be in result, got keys: {list(result.keys())}"
    )
    # Both keys should carry the same filter condition
    assert result["analytics.orders"] == result["orders"], (
        f"Both keys must have identical filter sets: "
        f"qualified={result['analytics.orders']}, bare={result['orders']}"
    )


@pytest.mark.asyncio
async def test_qualified_low_confidence_not_indexed_at_all(monkeypatch):
    """Qualified table with low confidence → neither qualified NOR bare key appears."""
    agent = _make_agent()
    cfg = _make_conn_cfg()
    _patch_db(
        monkeypatch,
        [_make_sync_entry("analytics.orders", {"tenant_id": "= 42"}, confidence_score=1)],
    )

    result = await agent._load_required_filters_by_table(cfg)

    assert "analytics.orders" not in result
    assert "orders" not in result


@pytest.mark.asyncio
async def test_unqualified_table_no_extra_bare_key(monkeypatch):
    """A plain 'orders' entry (no dot) is indexed only under 'orders', not duplicated."""
    agent = _make_agent()
    cfg = _make_conn_cfg()
    _patch_db(monkeypatch, [_make_sync_entry("orders", {"status": "= 1"}, confidence_score=4)])

    result = await agent._load_required_filters_by_table(cfg)

    assert "orders" in result
    # Only one key that contains 'orders' — no spurious schema-prefix duplicate
    assert len([k for k in result.keys() if "orders" in k]) == 1
