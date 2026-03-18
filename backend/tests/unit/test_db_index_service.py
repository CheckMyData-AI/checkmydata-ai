"""Unit tests for DbIndexService."""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.db_index import DbIndex, DbIndexSummary
from app.services.db_index_service import DbIndexService


@pytest.fixture
def svc():
    return DbIndexService()


def _make_entry(**overrides) -> DbIndex:
    defaults = {
        "id": "e1",
        "connection_id": "conn-1",
        "table_name": "users",
        "table_schema": "public",
        "column_count": 5,
        "row_count": 1000,
        "sample_data_json": "[]",
        "ordering_column": "created_at",
        "latest_record_at": None,
        "is_active": True,
        "relevance_score": 4,
        "business_description": "User accounts",
        "data_patterns": "email column has unique values",
        "column_notes_json": '{"id": "auto-increment PK"}',
        "query_hints": "Filter by is_active, join via id",
        "code_match_status": "matched",
        "code_match_details": "",
        "indexed_at": datetime(2026, 3, 17, tzinfo=UTC),
        "created_at": datetime(2026, 3, 17, tzinfo=UTC),
        "updated_at": datetime(2026, 3, 17, tzinfo=UTC),
    }
    defaults.update(overrides)
    entry = MagicMock(spec=DbIndex)
    for k, v in defaults.items():
        setattr(entry, k, v)
    return entry


def _make_summary(**overrides) -> DbIndexSummary:
    defaults = {
        "id": "s1",
        "connection_id": "conn-1",
        "total_tables": 10,
        "active_tables": 8,
        "empty_tables": 2,
        "orphan_tables": 1,
        "phantom_tables": 0,
        "summary_text": "E-commerce database",
        "recommendations": "- Use created_at for date ranges",
        "indexed_at": datetime(2026, 3, 17, tzinfo=UTC),
        "created_at": datetime(2026, 3, 17, tzinfo=UTC),
        "updated_at": datetime(2026, 3, 17, tzinfo=UTC),
    }
    defaults.update(overrides)
    entry = MagicMock(spec=DbIndexSummary)
    for k, v in defaults.items():
        setattr(entry, k, v)
    return entry


class TestIndexToPromptContext:
    def test_empty_entries(self, svc):
        result = svc.index_to_prompt_context([], None)
        assert result == ""

    def test_high_relevance_table(self, svc):
        entries = [_make_entry(relevance_score=5, is_active=True)]
        summary = _make_summary()
        result = svc.index_to_prompt_context(entries, summary)
        assert "Key Tables" in result
        assert "users" in result
        assert "~1,000" in result

    def test_medium_relevance_table(self, svc):
        entries = [_make_entry(relevance_score=3, is_active=True)]
        result = svc.index_to_prompt_context(entries, None)
        assert "Supporting Tables" in result
        assert "users" in result

    def test_inactive_tables(self, svc):
        entries = [_make_entry(is_active=False, relevance_score=1)]
        result = svc.index_to_prompt_context(entries, None)
        assert "low-relevance/inactive tables omitted" in result

    def test_recommendations_included(self, svc):
        entries = [_make_entry()]
        summary = _make_summary(recommendations="- Always filter by status")
        result = svc.index_to_prompt_context(entries, summary)
        assert "Always filter by status" in result

    def test_mixed_tables(self, svc):
        entries = [
            _make_entry(table_name="orders", relevance_score=5, is_active=True),
            _make_entry(table_name="logs", relevance_score=2, is_active=True),
            _make_entry(table_name="temp", relevance_score=1, is_active=False),
        ]
        result = svc.index_to_prompt_context(entries, None)
        assert "orders" in result
        assert "logs" in result
        assert "1 low-relevance/inactive tables omitted" in result


class TestTableIndexToDetail:
    def test_basic_detail(self, svc):
        entry = _make_entry()
        result = svc.table_index_to_detail(entry)
        assert "users" in result
        assert "User accounts" in result
        assert "4/5" in result
        assert "matched" in result

    def test_with_column_notes(self, svc):
        entry = _make_entry(column_notes_json='{"email": "unique, varchar(255)"}')
        result = svc.table_index_to_detail(entry)
        assert "`email`" in result
        assert "unique" in result

    def test_with_sample_data(self, svc):
        sample = json.dumps([{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}])
        entry = _make_entry(sample_data_json=sample)
        result = svc.table_index_to_detail(entry)
        assert "Alice" in result
        assert "Bob" in result

    def test_inactive_entry(self, svc):
        entry = _make_entry(is_active=False)
        result = svc.table_index_to_detail(entry)
        assert "Active:** No" in result

    def test_empty_column_notes(self, svc):
        entry = _make_entry(column_notes_json="{}")
        result = svc.table_index_to_detail(entry)
        assert "Column notes" not in result


class TestIndexToResponse:
    def test_basic_response(self, svc):
        entries = [_make_entry()]
        summary = _make_summary()
        result = svc.index_to_response(entries, summary)
        assert len(result["tables"]) == 1
        assert result["tables"][0]["table_name"] == "users"
        assert result["summary"]["total_tables"] == 10

    def test_no_summary(self, svc):
        entries = [_make_entry()]
        result = svc.index_to_response(entries, None)
        assert "summary" not in result

    def test_empty_entries(self, svc):
        result = svc.index_to_response([], None)
        assert result["tables"] == []


class TestBuildTableMap:
    def test_empty_entries(self, svc):
        result = svc.build_table_map([])
        assert result == ""

    def test_basic_map(self, svc):
        entries = [
            _make_entry(table_name="orders", row_count=125000, relevance_score=5,
                        business_description="Customer orders and transactions"),
            _make_entry(table_name="users", row_count=50000, relevance_score=4,
                        business_description="User accounts"),
        ]
        result = svc.build_table_map(entries)
        assert "orders(~125,000" in result
        assert "users(~50,000" in result

    def test_excludes_inactive_and_low_relevance(self, svc):
        entries = [
            _make_entry(table_name="orders", relevance_score=5, is_active=True),
            _make_entry(table_name="temp", relevance_score=1, is_active=False),
            _make_entry(table_name="logs", relevance_score=1, is_active=True),
        ]
        result = svc.build_table_map(entries)
        assert "orders" in result
        assert "temp" not in result
        assert "logs" not in result


class TestGetStatus:
    @pytest.mark.asyncio
    async def test_not_indexed(self, svc):
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result)

        status = await svc.get_status(session, "conn-1")
        assert status["is_indexed"] is False

    @pytest.mark.asyncio
    async def test_indexed(self, svc):
        session = AsyncMock()
        summary = _make_summary()
        result = MagicMock()
        result.scalar_one_or_none.return_value = summary
        session.execute = AsyncMock(return_value=result)

        status = await svc.get_status(session, "conn-1")
        assert status["is_indexed"] is True
        assert status["total_tables"] == 10
        assert status["active_tables"] == 8
