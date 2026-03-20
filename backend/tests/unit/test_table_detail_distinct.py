"""Tests for DISTINCT values appearing in table_index_to_detail output."""

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

from app.models.db_index import DbIndex
from app.services.db_index_service import DbIndexService


def _make_entry(**overrides) -> DbIndex:
    defaults = {
        "id": "e1",
        "connection_id": "conn-1",
        "table_name": "orders",
        "table_schema": "public",
        "column_count": 5,
        "row_count": 5000,
        "sample_data_json": "[]",
        "ordering_column": "created_at",
        "latest_record_at": None,
        "is_active": True,
        "relevance_score": 4,
        "business_description": "Customer orders",
        "data_patterns": "",
        "column_notes_json": "{}",
        "column_distinct_values_json": "{}",
        "query_hints": "",
        "numeric_format_notes": "{}",
        "code_match_status": "unknown",
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


class TestTableDetailDistinctValues:
    def test_distinct_values_included(self):
        distinct = {"status": ["active", "inactive", "pending"]}
        entry = _make_entry(column_distinct_values_json=json.dumps(distinct))
        result = DbIndexService.table_index_to_detail(entry)
        assert "Distinct values" in result
        assert "`status`" in result
        assert "active" in result
        assert "inactive" in result
        assert "pending" in result

    def test_distinct_values_empty(self):
        entry = _make_entry(column_distinct_values_json="{}")
        result = DbIndexService.table_index_to_detail(entry)
        assert "Distinct values" not in result

    def test_distinct_values_multiple_columns(self):
        distinct = {
            "status": ["active", "inactive"],
            "type": ["order", "return"],
        }
        entry = _make_entry(column_distinct_values_json=json.dumps(distinct))
        result = DbIndexService.table_index_to_detail(entry)
        assert "`status`" in result
        assert "`type`" in result
        assert "order" in result

    def test_distinct_values_truncated_at_20(self):
        distinct = {"category": [f"cat_{i}" for i in range(30)]}
        entry = _make_entry(column_distinct_values_json=json.dumps(distinct))
        result = DbIndexService.table_index_to_detail(entry)
        assert "cat_0" in result
        assert "cat_19" in result
        assert "cat_20" not in result

    def test_invalid_json_gracefully_handled(self):
        entry = _make_entry(column_distinct_values_json="not valid json")
        result = DbIndexService.table_index_to_detail(entry)
        assert "Distinct values" not in result
