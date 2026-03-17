"""Unit tests for DbIndexPipeline helpers and sample query generation."""

import json

from app.connectors.base import ColumnInfo, QueryResult, TableInfo
from app.knowledge.db_index_pipeline import (
    _detect_latest_record,
    _find_ordering_column,
    _sample_query,
    _sample_to_json,
)


class TestFindOrderingColumn:
    def test_prefers_created_at(self):
        table = TableInfo(
            name="users",
            columns=[
                ColumnInfo(name="id", data_type="int", is_primary_key=True),
                ColumnInfo(name="created_at", data_type="timestamp"),
                ColumnInfo(name="updated_at", data_type="timestamp"),
            ],
        )
        assert _find_ordering_column(table) == "created_at"

    def test_falls_back_to_pk(self):
        table = TableInfo(
            name="tags",
            columns=[
                ColumnInfo(name="id", data_type="int", is_primary_key=True),
                ColumnInfo(name="name", data_type="varchar"),
            ],
        )
        assert _find_ordering_column(table) == "id"

    def test_case_insensitive(self):
        table = TableInfo(
            name="events",
            columns=[
                ColumnInfo(name="ID", data_type="int", is_primary_key=True),
                ColumnInfo(name="CreatedAt", data_type="timestamp"),
            ],
        )
        assert _find_ordering_column(table) == "CreatedAt"

    def test_no_suitable_column(self):
        table = TableInfo(
            name="pivot",
            columns=[
                ColumnInfo(name="left_id", data_type="int"),
                ColumnInfo(name="right_id", data_type="int"),
            ],
        )
        assert _find_ordering_column(table) is None

    def test_timestamp_column(self):
        table = TableInfo(
            name="logs",
            columns=[
                ColumnInfo(name="msg", data_type="text"),
                ColumnInfo(name="timestamp", data_type="timestamp"),
            ],
        )
        assert _find_ordering_column(table) == "timestamp"


class TestSampleQuery:
    def test_postgres_with_ordering(self):
        table = TableInfo(
            name="users",
            schema="public",
            columns=[
                ColumnInfo(name="id", data_type="int", is_primary_key=True),
                ColumnInfo(name="created_at", data_type="timestamp"),
            ],
        )
        query, col = _sample_query(table, "postgres")
        assert '"users"' in query
        assert "ORDER BY" in query
        assert '"created_at"' in query
        assert "DESC LIMIT 3" in query
        assert col == "created_at"

    def test_mysql_with_ordering(self):
        table = TableInfo(
            name="orders",
            columns=[
                ColumnInfo(name="id", data_type="int", is_primary_key=True),
                ColumnInfo(name="created_at", data_type="datetime"),
            ],
        )
        query, col = _sample_query(table, "mysql")
        assert "`orders`" in query
        assert "`created_at`" in query
        assert col == "created_at"

    def test_no_ordering_column(self):
        table = TableInfo(
            name="pivot",
            columns=[
                ColumnInfo(name="a_id", data_type="int"),
                ColumnInfo(name="b_id", data_type="int"),
            ],
        )
        query, col = _sample_query(table, "postgres")
        assert "ORDER BY" not in query
        assert "LIMIT 3" in query
        assert col is None

    def test_custom_limit(self):
        table = TableInfo(
            name="logs",
            columns=[ColumnInfo(name="id", data_type="int", is_primary_key=True)],
        )
        query, _ = _sample_query(table, "postgres", limit=5)
        assert "LIMIT 5" in query

    def test_non_public_schema(self):
        table = TableInfo(
            name="events",
            schema="analytics",
            columns=[ColumnInfo(name="id", data_type="int", is_primary_key=True)],
        )
        query, _ = _sample_query(table, "postgres")
        assert '"analytics"."events"' in query


class TestSampleToJson:
    def test_basic_conversion(self):
        result = QueryResult(
            columns=["id", "name"],
            rows=[[1, "Alice"], [2, "Bob"]],
            row_count=2,
        )
        data = json.loads(_sample_to_json(result))
        assert len(data) == 2
        assert data[0]["id"] == 1
        assert data[1]["name"] == "Bob"

    def test_empty_result(self):
        result = QueryResult(columns=[], rows=[], row_count=0)
        assert _sample_to_json(result) == "[]"

    def test_non_serializable_values(self):
        from datetime import datetime

        result = QueryResult(
            columns=["id", "created"],
            rows=[[1, datetime(2026, 3, 17)]],
            row_count=1,
        )
        data = json.loads(_sample_to_json(result))
        assert len(data) == 1
        assert "2026" in str(data[0]["created"])


class TestDetectLatestRecord:
    def test_with_timestamp(self):
        from datetime import datetime

        result = QueryResult(
            columns=["id", "created_at"],
            rows=[[1, datetime(2026, 3, 17, 10, 30)]],
            row_count=1,
        )
        ts = _detect_latest_record(result, "created_at")
        assert ts is not None
        assert "2026-03-17" in ts

    def test_with_string_value(self):
        result = QueryResult(
            columns=["id", "created_at"],
            rows=[[1, "2026-03-17 10:30:00"]],
            row_count=1,
        )
        ts = _detect_latest_record(result, "created_at")
        assert ts == "2026-03-17 10:30:00"

    def test_no_ordering_column(self):
        result = QueryResult(columns=["id"], rows=[[1]], row_count=1)
        assert _detect_latest_record(result, None) is None

    def test_empty_rows(self):
        result = QueryResult(columns=["id"], rows=[], row_count=0)
        assert _detect_latest_record(result, "id") is None

    def test_none_value(self):
        result = QueryResult(
            columns=["id", "created_at"],
            rows=[[1, None]],
            row_count=1,
        )
        assert _detect_latest_record(result, "created_at") is None

    def test_column_not_found(self):
        result = QueryResult(
            columns=["id", "name"],
            rows=[[1, "test"]],
            row_count=1,
        )
        assert _detect_latest_record(result, "created_at") is None
