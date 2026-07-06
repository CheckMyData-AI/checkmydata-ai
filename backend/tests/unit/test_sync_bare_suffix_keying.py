"""T7: Uniform bare-suffix keying alias for sync guidance (SYNC-L7).

Tests that:
1. bare_suffix() static helper works correctly.
2. get_table_sync() resolves a bare-name request to a schema-qualified stored row.
3. _load_sync_filters_and_mappings emits lines under BOTH qualified AND bare keys.
4. _load_sync_for_prompt emits warnings under BOTH qualified AND bare table names.
"""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import app.models.batch_query  # noqa: F401
import app.models.chat_session  # noqa: F401
import app.models.code_db_sync  # noqa: F401
import app.models.commit_index  # noqa: F401
import app.models.connection  # noqa: F401
import app.models.custom_rule  # noqa: F401
import app.models.indexing_checkpoint  # noqa: F401
import app.models.knowledge_doc  # noqa: F401
import app.models.notification  # noqa: F401
import app.models.project  # noqa: F401
import app.models.project_cache  # noqa: F401
import app.models.project_invite  # noqa: F401
import app.models.project_member  # noqa: F401
import app.models.rag_feedback  # noqa: F401
import app.models.repository  # noqa: F401
import app.models.saved_note  # noqa: F401
import app.models.scheduled_query  # noqa: F401
import app.models.ssh_key  # noqa: F401
import app.models.token_usage  # noqa: F401
import app.models.user  # noqa: F401
from app.models.base import Base
from app.models.code_db_sync import CodeDbSync
from app.models.connection import Connection
from app.models.project import Project
from app.services.code_db_sync_service import CodeDbSyncService

svc = CodeDbSyncService()


# ---------------------------------------------------------------------------
# In-memory DB fixture (mirrors existing test_code_db_sync_service pattern)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()


async def _make_project(db: AsyncSession) -> Project:
    p = Project(name=f"proj-{uuid.uuid4().hex[:6]}")
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


async def _make_connection(db: AsyncSession, project_id: str) -> Connection:
    c = Connection(
        project_id=project_id,
        name="test-conn",
        db_type="postgresql",
        db_port=5432,
        db_name="testdb",
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


# ---------------------------------------------------------------------------
# 1. bare_suffix() static helper
# ---------------------------------------------------------------------------


class TestBareSuffix:
    def test_bare_suffix_simple(self):
        """Bare name returned unchanged."""
        assert CodeDbSyncService.bare_suffix("orders") == "orders"

    def test_bare_suffix_schema_qualified(self):
        """Single-dot qualification → last segment returned."""
        assert CodeDbSyncService.bare_suffix("analytics.orders") == "orders"

    def test_bare_suffix_multi_level(self):
        """Multiple-dot qualification → last segment returned."""
        assert CodeDbSyncService.bare_suffix("a.b.orders") == "orders"

    def test_bare_suffix_empty_string(self):
        """Empty string returns empty string (no crash)."""
        assert CodeDbSyncService.bare_suffix("") == ""


# ---------------------------------------------------------------------------
# 2. get_table_sync() bare-lookup resolution
# ---------------------------------------------------------------------------


class TestGetTableSyncBareLookup:
    async def test_get_table_sync_exact_match(self, db):
        """Exact table_name still resolves as before."""
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        await svc.upsert_table_sync(
            db,
            conn.id,
            {"table_name": "analytics.orders", "confidence_score": 5},
        )

        result = await svc.get_table_sync(db, conn.id, "analytics.orders")
        assert result is not None
        assert result.table_name == "analytics.orders"

    async def test_get_table_sync_resolves_bare_when_stored_qualified(self, db):
        """Stored as 'analytics.orders'; lookup by bare 'orders' → returns the row."""
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        await svc.upsert_table_sync(
            db,
            conn.id,
            {"table_name": "analytics.orders", "confidence_score": 5},
        )

        result = await svc.get_table_sync(db, conn.id, "orders")
        assert result is not None, (
            "get_table_sync(bare='orders') must find the 'analytics.orders' row"
        )
        assert result.table_name == "analytics.orders"

    async def test_get_table_sync_returns_none_when_no_match(self, db):
        """No row at all → returns None (no false positives)."""
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        await svc.upsert_table_sync(
            db,
            conn.id,
            {"table_name": "analytics.orders", "confidence_score": 5},
        )

        result = await svc.get_table_sync(db, conn.id, "users")
        assert result is None

    async def test_get_table_sync_bare_already_stored_unqualified(self, db):
        """Row stored as plain 'orders'; bare lookup still works (exact-match path)."""
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        await svc.upsert_table_sync(
            db,
            conn.id,
            {"table_name": "orders", "confidence_score": 3},
        )

        result = await svc.get_table_sync(db, conn.id, "orders")
        assert result is not None
        assert result.table_name == "orders"

    async def test_get_table_sync_three_level_schema(self, db):
        """Stored as 'a.b.orders'; lookup by 'orders' returns it."""
        proj = await _make_project(db)
        conn = await _make_connection(db, proj.id)
        await svc.upsert_table_sync(
            db,
            conn.id,
            {"table_name": "a.b.orders", "confidence_score": 3},
        )

        result = await svc.get_table_sync(db, conn.id, "orders")
        assert result is not None
        assert result.table_name == "a.b.orders"


# ---------------------------------------------------------------------------
# Helpers for sql_agent tests
# ---------------------------------------------------------------------------


def _make_agent():  # type: ignore[return]
    """Minimal SQLAgent without real DB/LLM deps."""
    from app.agents.sql_agent import SQLAgent

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
    conversion_warnings: str = "",
    column_value_mappings: dict | None = None,
    connection_id: str = "conn-test",
) -> MagicMock:
    entry = MagicMock(spec=CodeDbSync)
    entry.table_name = table_name
    entry.connection_id = connection_id
    entry.required_filters_json = json.dumps(required_filters)
    entry.confidence_score = confidence_score
    entry.conversion_warnings = conversion_warnings
    entry.column_value_mappings_json = json.dumps(column_value_mappings or {})
    return entry


def _patch_db_for_agent(monkeypatch, sync_entries: list) -> None:
    """Monkeypatch CodeDbSyncService.get_sync + session factory for sql_agent tests."""

    async def fake_get_sync(self, session, connection_id):  # noqa: ANN001
        return sync_entries

    @asynccontextmanager
    async def fake_session_factory():
        yield MagicMock()

    monkeypatch.setattr(
        "app.services.code_db_sync_service.CodeDbSyncService.get_sync",
        fake_get_sync,
    )
    monkeypatch.setattr("app.models.base.async_session_factory", fake_session_factory)
    monkeypatch.setattr("app.config.settings.sync_min_confidence_to_enforce_filters", 2)


# ---------------------------------------------------------------------------
# 3. _load_sync_filters_and_mappings — keys under both qualified + bare
# ---------------------------------------------------------------------------


class TestLoadSyncFiltersAndMappings:
    async def test_filters_contains_both_qualified_and_bare_key(self, monkeypatch):
        """Entry stored as 'analytics.orders' → filters text must have a dedicated line
        for both 'analytics.orders' AND a separate line starting with '- orders:'."""
        agent = _make_agent()
        _patch_db_for_agent(
            monkeypatch,
            [
                _make_sync_entry(
                    "analytics.orders",
                    {"tenant_id": "= 42"},
                    confidence_score=5,
                )
            ],
        )

        filters_text, _ = await agent._load_sync_filters_and_mappings("conn-test")

        lines = filters_text.splitlines()
        # Qualified line e.g. "- analytics.orders: ALWAYS add WHERE ..."
        assert any("analytics.orders" in line for line in lines), (
            f"Qualified name must appear in filters text; got: {filters_text!r}"
        )
        # Bare-key line e.g. "- orders: ALWAYS add WHERE ..." (NOT inside analytics.orders)
        assert any(line.startswith("- orders:") or line.startswith("-orders:") for line in lines), (
            f"A dedicated bare-name line ('- orders: ...') must exist in filters text; "
            f"got: {filters_text!r}"
        )

    async def test_mappings_contains_both_qualified_and_bare_key(self, monkeypatch):
        """Entry stored as 'analytics.events' → mappings text must have a line for
        'analytics.events.status' AND a separate line for bare 'events.status'."""
        agent = _make_agent()
        _patch_db_for_agent(
            monkeypatch,
            [
                _make_sync_entry(
                    "analytics.events",
                    {},
                    confidence_score=5,
                    column_value_mappings={"status": {"1": "active", "0": "inactive"}},
                )
            ],
        )

        _, mappings_text = await agent._load_sync_filters_and_mappings("conn-test")

        lines = mappings_text.splitlines()
        # Qualified line e.g. "- analytics.events.status: ..."
        assert any("analytics.events.status" in line for line in lines), (
            f"Qualified mapping line must exist; got: {mappings_text!r}"
        )
        # Bare line e.g. "- events.status: ..."
        assert any("events.status" in line and "analytics" not in line for line in lines), (
            f"A bare-name mapping line ('- events.status: ...') must exist; got: {mappings_text!r}"
        )

    async def test_low_confidence_entry_not_emitted_at_all(self, monkeypatch):
        """Low-confidence entry → neither qualified nor bare name in output."""
        agent = _make_agent()
        _patch_db_for_agent(
            monkeypatch,
            [
                _make_sync_entry(
                    "analytics.orders",
                    {"tenant_id": "= 42"},
                    confidence_score=1,
                )
            ],
        )

        filters_text, _ = await agent._load_sync_filters_and_mappings("conn-test")

        assert "analytics.orders" not in filters_text
        assert "orders" not in filters_text

    async def test_unqualified_table_emitted_once(self, monkeypatch):
        """Plain 'orders' (no schema) → only appears once, not duplicated."""
        agent = _make_agent()
        _patch_db_for_agent(
            monkeypatch,
            [
                _make_sync_entry(
                    "orders",
                    {"status": "= 1"},
                    confidence_score=5,
                )
            ],
        )

        filters_text, _ = await agent._load_sync_filters_and_mappings("conn-test")

        assert filters_text.count("orders") == 1, (
            f"Unqualified table 'orders' must appear exactly once; got: {filters_text!r}"
        )


# ---------------------------------------------------------------------------
# 4. _load_sync_for_prompt — warnings under both qualified + bare names
# ---------------------------------------------------------------------------


class TestLoadSyncForPrompt:
    async def _patch_db_for_prompt(self, monkeypatch, sync_entries: list) -> None:
        """Monkeypatch get_sync + get_summary + session factory."""

        async def fake_get_sync(self, session, connection_id):  # noqa: ANN001
            return sync_entries

        async def fake_get_summary(self, session, connection_id):  # noqa: ANN001
            return None

        @asynccontextmanager
        async def fake_session_factory():
            yield MagicMock()

        monkeypatch.setattr(
            "app.services.code_db_sync_service.CodeDbSyncService.get_sync",
            fake_get_sync,
        )
        monkeypatch.setattr(
            "app.services.code_db_sync_service.CodeDbSyncService.get_summary",
            fake_get_summary,
        )
        monkeypatch.setattr("app.models.base.async_session_factory", fake_session_factory)

    async def test_warnings_contain_bare_name_for_qualified_entry(self, monkeypatch):
        """Entry 'analytics.orders' with high confidence + warnings → warning text
        must have a line for 'analytics.orders' AND a separate line for bare 'orders'."""
        agent = _make_agent()
        await self._patch_db_for_prompt(
            monkeypatch,
            [
                _make_sync_entry(
                    "analytics.orders",
                    {},
                    confidence_score=5,
                    conversion_warnings="timestamp stored as UTC",
                )
            ],
        )

        _, warnings_text = await agent._load_sync_for_prompt("conn-test")

        lines = warnings_text.splitlines()
        # Must have the qualified line
        assert any("analytics.orders" in line for line in lines), (
            f"Qualified name must appear in warnings; got: {warnings_text!r}"
        )
        # Must also have a separate bare line starting with "- orders:"
        assert any(line.startswith("- orders:") or line.startswith("-orders:") for line in lines), (
            f"A dedicated bare-name warning line ('- orders: ...') must exist; "
            f"got: {warnings_text!r}"
        )

    async def test_warnings_not_emitted_for_low_confidence_entry(self, monkeypatch):
        """Low confidence (< 4) → no warning emitted for this entry."""
        agent = _make_agent()
        await self._patch_db_for_prompt(
            monkeypatch,
            [
                _make_sync_entry(
                    "analytics.orders",
                    {},
                    confidence_score=3,
                    conversion_warnings="timestamp stored as UTC",
                )
            ],
        )

        _, warnings_text = await agent._load_sync_for_prompt("conn-test")

        assert "analytics.orders" not in warnings_text
        assert "orders" not in warnings_text

    async def test_unqualified_warning_emitted_once(self, monkeypatch):
        """Plain 'orders' → warning line appears exactly once, not doubled."""
        agent = _make_agent()
        await self._patch_db_for_prompt(
            monkeypatch,
            [
                _make_sync_entry(
                    "orders",
                    {},
                    confidence_score=5,
                    conversion_warnings="numeric as string",
                )
            ],
        )

        _, warnings_text = await agent._load_sync_for_prompt("conn-test")

        assert warnings_text.count("orders") == 1, (
            f"Unqualified 'orders' must appear exactly once; got: {warnings_text!r}"
        )
