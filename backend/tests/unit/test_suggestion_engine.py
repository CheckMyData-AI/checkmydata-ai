"""Unit tests for SuggestionEngine."""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.db_index import DbIndex
from app.services.suggestion_engine import SuggestionEngine


@pytest.fixture
def engine():
    return SuggestionEngine()


def _make_db_index(**overrides) -> DbIndex:
    defaults = {
        "id": "e1",
        "connection_id": "conn-1",
        "table_name": "orders",
        "table_schema": "public",
        "column_count": 8,
        "row_count": 5000,
        "sample_data_json": "[]",
        "ordering_column": "created_at",
        "latest_record_at": None,
        "is_active": True,
        "relevance_score": 4,
        "business_description": "Customer orders",
        "data_patterns": "",
        "column_notes_json": '{"status": "order status enum"}',
        "column_distinct_values_json": '{"status": ["pending", "shipped", "delivered"]}',
        "query_hints": "Filter by status",
        "numeric_format_notes": "{}",
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


@pytest.mark.asyncio
async def test_schema_based_suggestions_returns_results(engine):
    entries = [
        _make_db_index(table_name="orders", relevance_score=5),
        _make_db_index(
            id="e2",
            table_name="users",
            relevance_score=4,
            column_notes_json='{"email": "unique"}',
            column_distinct_values_json="{}",
        ),
    ]

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = entries

    db = AsyncMock()
    db.execute.return_value = mock_result

    suggestions = await engine.schema_based_suggestions(db, "conn-1", limit=5)

    assert len(suggestions) >= 1
    assert len(suggestions) <= 5
    for s in suggestions:
        assert "text" in s
        assert s["source"] == "schema"
        assert "table" in s


@pytest.mark.asyncio
async def test_schema_based_suggestions_empty_when_no_tables(engine):
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []

    db = AsyncMock()
    db.execute.return_value = mock_result

    suggestions = await engine.schema_based_suggestions(db, "conn-1")
    assert suggestions == []


@pytest.mark.asyncio
async def test_history_based_suggestions(engine):
    rows = [
        (
            "Here are the results.",
            json.dumps(
                {
                    "query": "SELECT * FROM orders",
                    "question": "Show me all orders from last week",
                }
            ),
        ),
        (
            "Found 42 users.",
            json.dumps(
                {
                    "query": "SELECT count(*) FROM users",
                    "question": "How many users do we have?",
                }
            ),
        ),
    ]

    mock_result = MagicMock()
    mock_result.all.return_value = rows

    db = AsyncMock()
    db.execute.return_value = mock_result

    suggestions = await engine.history_based_suggestions(db, "user-1", "proj-1", limit=3)

    assert len(suggestions) >= 1
    assert len(suggestions) <= 3
    for s in suggestions:
        assert "text" in s
        assert s["source"] == "history"


@pytest.mark.asyncio
async def test_history_skips_errors(engine):
    rows = [
        (
            "Error occurred.",
            json.dumps(
                {
                    "query": "SELECT bad",
                    "error": "syntax error",
                    "question": "Bad query",
                }
            ),
        ),
    ]

    mock_result = MagicMock()
    mock_result.all.return_value = rows

    db = AsyncMock()
    db.execute.return_value = mock_result

    suggestions = await engine.history_based_suggestions(db, "user-1", "proj-1")
    assert suggestions == []


@pytest.mark.asyncio
async def test_get_suggestions_deduplicates(engine):
    with patch.object(
        engine,
        "history_based_suggestions",
        return_value=[
            {"text": "Show me all orders", "source": "history"},
        ],
    ):
        with patch.object(
            engine,
            "schema_based_suggestions",
            return_value=[
                {"text": "Show me all orders", "source": "schema", "table": "orders"},
                {"text": "How many records are in users?", "source": "schema", "table": "users"},
            ],
        ):
            suggestions = await engine.get_suggestions(
                AsyncMock(), "user-1", "proj-1", "conn-1", limit=5
            )

    texts = [s["text"].lower() for s in suggestions]
    assert len(texts) == len(set(texts))


def test_generate_followups_basic():
    followups = SuggestionEngine.generate_followups(
        query="SELECT status, count(*) FROM orders GROUP BY status",
        columns=["status", "count"],
        row_count=5,
    )

    assert isinstance(followups, list)
    assert 1 <= len(followups) <= 3
    for f in followups:
        assert isinstance(f, str)
        assert len(f) > 0


def test_generate_followups_no_rows():
    followups = SuggestionEngine.generate_followups(
        query="SELECT * FROM empty_table",
        columns=["id"],
        row_count=0,
    )

    assert isinstance(followups, list)
    assert len(followups) <= 3


def test_pick_interesting_column():
    entry = _make_db_index()
    col = SuggestionEngine._pick_interesting_column(entry)
    assert col == "status"


def test_pick_interesting_column_fallback_to_notes():
    entry = _make_db_index(column_distinct_values_json="{}")
    col = SuggestionEngine._pick_interesting_column(entry)
    assert col == "status"


def test_pick_interesting_column_none():
    entry = _make_db_index(column_distinct_values_json="{}", column_notes_json="{}")
    col = SuggestionEngine._pick_interesting_column(entry)
    assert col is None
