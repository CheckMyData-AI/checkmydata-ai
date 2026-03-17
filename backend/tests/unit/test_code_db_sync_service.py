"""Unit tests for CodeDbSyncService."""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.code_db_sync import CodeDbSync, CodeDbSyncSummary
from app.services.code_db_sync_service import CodeDbSyncService


@pytest.fixture
def svc():
    return CodeDbSyncService()


def _make_entry(**overrides) -> CodeDbSync:
    defaults = {
        "id": "e1",
        "connection_id": "conn-1",
        "table_name": "orders",
        "entity_name": "Order",
        "entity_file_path": "models/order.py",
        "code_columns_json": '[{"name": "amount", "type": "Integer"}]',
        "used_in_files_json": '["services/order_service.py"]',
        "read_count": 3,
        "write_count": 2,
        "data_format_notes": "Amount stored in cents (integer), divide by 100 for dollars",
        "column_sync_notes_json": '{"amount": "cents, divide by 100"}',
        "business_logic_notes": "Orders are created via API, status transitions: pending -> paid -> shipped",
        "conversion_warnings": "amount is in cents not dollars",
        "query_recommendations": "Always filter by status != 'cancelled'",
        "sync_status": "matched",
        "confidence_score": 4,
        "synced_at": datetime(2026, 3, 17, tzinfo=UTC),
        "created_at": datetime(2026, 3, 17, tzinfo=UTC),
        "updated_at": datetime(2026, 3, 17, tzinfo=UTC),
    }
    defaults.update(overrides)
    entry = MagicMock(spec=CodeDbSync)
    for k, v in defaults.items():
        setattr(entry, k, v)
    return entry


def _make_summary(**overrides) -> CodeDbSyncSummary:
    defaults = {
        "id": "s1",
        "connection_id": "conn-1",
        "total_tables": 10,
        "synced_tables": 8,
        "code_only_tables": 1,
        "db_only_tables": 1,
        "mismatch_tables": 0,
        "global_notes": "E-commerce app with order processing",
        "data_conventions": "All money in cents. All timestamps UTC.",
        "query_guidelines": "- Divide amount by 100 for display\n- Filter deleted_at IS NULL",
        "sync_status": "completed",
        "synced_at": datetime(2026, 3, 17, tzinfo=UTC),
        "created_at": datetime(2026, 3, 17, tzinfo=UTC),
        "updated_at": datetime(2026, 3, 17, tzinfo=UTC),
    }
    defaults.update(overrides)
    entry = MagicMock(spec=CodeDbSyncSummary)
    for k, v in defaults.items():
        setattr(entry, k, v)
    return entry


class TestSyncToPromptContext:
    def test_empty_entries(self, svc):
        result = svc.sync_to_prompt_context([], None)
        assert result == ""

    def test_with_warnings(self, svc):
        entries = [_make_entry()]
        summary = _make_summary()
        result = svc.sync_to_prompt_context(entries, summary)
        assert "Conversion Warnings" in result
        assert "cents not dollars" in result
        assert "orders" in result

    def test_data_conventions(self, svc):
        entries = [_make_entry()]
        summary = _make_summary()
        result = svc.sync_to_prompt_context(entries, summary)
        assert "Data Conventions" in result
        assert "money in cents" in result

    def test_query_guidelines(self, svc):
        entries = [_make_entry()]
        summary = _make_summary()
        result = svc.sync_to_prompt_context(entries, summary)
        assert "Query Guidelines" in result
        assert "Divide amount by 100" in result

    def test_db_only_tables(self, svc):
        entries = [_make_entry(sync_status="db_only", conversion_warnings="")]
        result = svc.sync_to_prompt_context(entries, None)
        assert "DB-only" in result

    def test_matched_tables_table(self, svc):
        entries = [_make_entry(sync_status="matched", conversion_warnings="")]
        result = svc.sync_to_prompt_context(entries, None)
        assert "Synced Tables" in result


class TestTableSyncToDetail:
    def test_basic_detail(self, svc):
        entry = _make_entry()
        result = svc.table_sync_to_detail(entry)
        assert "orders" in result
        assert "matched" in result
        assert "4/5" in result
        assert "Order" in result

    def test_with_column_notes(self, svc):
        entry = _make_entry()
        result = svc.table_sync_to_detail(entry)
        assert "`amount`" in result
        assert "cents" in result

    def test_with_used_files(self, svc):
        entry = _make_entry()
        result = svc.table_sync_to_detail(entry)
        assert "order_service" in result

    def test_conversion_warnings(self, svc):
        entry = _make_entry()
        result = svc.table_sync_to_detail(entry)
        assert "WARNINGS" in result
        assert "cents not dollars" in result

    def test_empty_column_notes(self, svc):
        entry = _make_entry(column_sync_notes_json="{}")
        result = svc.table_sync_to_detail(entry)
        assert "Column notes" not in result


class TestSyncToResponse:
    def test_basic_response(self, svc):
        entries = [_make_entry()]
        summary = _make_summary()
        result = svc.sync_to_response(entries, summary)
        assert len(result["tables"]) == 1
        assert result["tables"][0]["table_name"] == "orders"
        assert result["summary"]["total_tables"] == 10

    def test_no_summary(self, svc):
        entries = [_make_entry()]
        result = svc.sync_to_response(entries, None)
        assert "summary" not in result

    def test_empty_entries(self, svc):
        result = svc.sync_to_response([], None)
        assert result["tables"] == []


class TestIsSynced:
    @pytest.mark.asyncio
    async def test_not_synced(self, svc):
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result)

        assert await svc.is_synced(session, "conn-1") is False

    @pytest.mark.asyncio
    async def test_synced(self, svc):
        session = AsyncMock()
        summary = _make_summary(sync_status="completed")
        result = MagicMock()
        result.scalar_one_or_none.return_value = summary
        session.execute = AsyncMock(return_value=result)

        assert await svc.is_synced(session, "conn-1") is True

    @pytest.mark.asyncio
    async def test_stale_not_synced(self, svc):
        session = AsyncMock()
        summary = _make_summary(sync_status="stale")
        result = MagicMock()
        result.scalar_one_or_none.return_value = summary
        session.execute = AsyncMock(return_value=result)

        assert await svc.is_synced(session, "conn-1") is False


class TestGetStatus:
    @pytest.mark.asyncio
    async def test_no_summary(self, svc):
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result)

        status = await svc.get_status(session, "conn-1")
        assert status["is_synced"] is False

    @pytest.mark.asyncio
    async def test_completed(self, svc):
        session = AsyncMock()
        summary = _make_summary()
        result = MagicMock()
        result.scalar_one_or_none.return_value = summary
        session.execute = AsyncMock(return_value=result)

        status = await svc.get_status(session, "conn-1")
        assert status["is_synced"] is True
        assert status["total_tables"] == 10
        assert status["synced_tables"] == 8
