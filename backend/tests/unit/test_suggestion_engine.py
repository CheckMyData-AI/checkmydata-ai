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


def test_make_variation_returns_prefixed_unchanged():
    result = SuggestionEngine._make_variation("Show me all the orders")
    assert result == "Show me all the orders"


def test_make_variation_strips_question_mark():
    result = SuggestionEngine._make_variation("What happened?")
    assert result == "What happened"


def test_make_variation_no_prefix():
    result = SuggestionEngine._make_variation("Monthly revenue breakdown")
    assert result == "Monthly revenue breakdown"


@pytest.mark.asyncio
async def test_history_skips_null_meta(engine):
    rows = [("Some content.", None)]
    mock_result = MagicMock()
    mock_result.all.return_value = rows
    db = AsyncMock()
    db.execute.return_value = mock_result
    suggestions = await engine.history_based_suggestions(db, "u1", "p1")
    assert suggestions == []


@pytest.mark.asyncio
async def test_history_skips_invalid_json(engine):
    rows = [("Content.", "not json!!!")]
    mock_result = MagicMock()
    mock_result.all.return_value = rows
    db = AsyncMock()
    db.execute.return_value = mock_result
    suggestions = await engine.history_based_suggestions(db, "u1", "p1")
    assert suggestions == []


@pytest.mark.asyncio
async def test_history_skips_short_question(engine):
    rows = [("Content.", json.dumps({"query": "SELECT 1", "question": "Short"}))]
    mock_result = MagicMock()
    mock_result.all.return_value = rows
    db = AsyncMock()
    db.execute.return_value = mock_result
    suggestions = await engine.history_based_suggestions(db, "u1", "p1")
    assert suggestions == []


def test_pick_interesting_column_bad_distinct_json():
    entry = _make_db_index(column_distinct_values_json="not json")
    col = SuggestionEngine._pick_interesting_column(entry)
    assert col == "status"


def test_pick_interesting_column_bad_notes_json():
    entry = _make_db_index(column_distinct_values_json="{}", column_notes_json="not json")
    col = SuggestionEngine._pick_interesting_column(entry)
    assert col is None


@pytest.mark.asyncio
async def test_schema_suggestions_limit_reached(engine):
    """Cover line 78/95: limit reached during iteration."""
    import random

    random.seed(42)
    entries = [
        _make_db_index(id=f"e{i}", table_name=f"table_{i}", relevance_score=5) for i in range(10)
    ]
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = entries

    db = AsyncMock()
    db.execute.return_value = mock_result

    suggestions = await engine.schema_based_suggestions(db, "conn-1", limit=2)
    assert len(suggestions) <= 2
    random.seed()


@pytest.mark.asyncio
async def test_schema_no_interesting_column(engine):
    """Cover line 80: template with {column} but no interesting column."""
    entries = [
        _make_db_index(
            column_distinct_values_json="{}",
            column_notes_json="{}",
        )
    ]
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = entries

    db = AsyncMock()
    db.execute.return_value = mock_result

    suggestions = await engine.schema_based_suggestions(db, "conn-1", limit=5)
    for s in suggestions:
        assert "{column}" not in s["text"]


@pytest.mark.asyncio
async def test_history_limit_reached(engine):
    """Cover line 125: history_based_suggestions reaching limit."""
    rows = [
        (
            f"Content {i}.",
            json.dumps(
                {
                    "query": f"SELECT * FROM t{i}",
                    "question": f"Show me all records from table number {i} please",
                }
            ),
        )
        for i in range(10)
    ]

    mock_result = MagicMock()
    mock_result.all.return_value = rows

    db = AsyncMock()
    db.execute.return_value = mock_result

    suggestions = await engine.history_based_suggestions(db, "u1", "p1", limit=2)
    assert len(suggestions) <= 2


@pytest.mark.asyncio
async def test_history_deduplicates_variations(engine):
    """Cover line 142: duplicate variation detection."""
    rows = [
        (
            "Content 1.",
            json.dumps(
                {
                    "query": "SELECT * FROM orders",
                    "question": "Show me all orders from the database",
                }
            ),
        ),
        (
            "Content 2.",
            json.dumps(
                {
                    "query": "SELECT * FROM orders",
                    "question": "Show me all orders from the database",
                }
            ),
        ),
    ]

    mock_result = MagicMock()
    mock_result.all.return_value = rows

    db = AsyncMock()
    db.execute.return_value = mock_result

    suggestions = await engine.history_based_suggestions(db, "u1", "p1")
    texts = [s["text"] for s in suggestions]
    assert len(texts) == len(set(texts))
