"""Characterization tests for result_handler module (W0 decomposition, ORCH-A04).

These tests lock the CURRENT output of the three formatting helpers extracted
from SQLAgent so any future change in behavior is caught immediately.
"""

from __future__ import annotations

from app.agents.result_handler import (
    format_query_results,
    format_schema_overview,
    format_table_detail,
)
from app.connectors.base import ColumnInfo, QueryResult, SchemaInfo, TableInfo

# ---------------------------------------------------------------------------
# format_query_results
# ---------------------------------------------------------------------------


def test_format_query_results_no_rows():
    out = format_query_results(QueryResult(columns=["a"], rows=[], row_count=0))
    assert out == "Query executed successfully but returned no rows."


def test_format_query_results_truncation_banner():
    qr = QueryResult(columns=["a"], rows=[[1]], row_count=1, truncated=True)
    out = format_query_results(qr)
    assert "RESULT TRUNCATED" in out
    assert "| a |" in out


def test_format_query_results_single_row():
    qr = QueryResult(columns=["id", "name"], rows=[[1, "alice"]], row_count=1)
    out = format_query_results(qr)
    assert "| id | name |" in out
    assert "| 1 | alice |" in out
    assert "Total rows: 1" in out


def test_format_query_results_more_rows_banner():
    """Rows beyond max_rows produce a '... and N more rows' suffix."""
    rows = [[i] for i in range(5)]
    qr = QueryResult(columns=["n"], rows=rows, row_count=10)
    out = format_query_results(qr, max_rows=5)
    assert "... and 5 more rows" in out


def test_format_query_results_no_truncation_banner_when_not_truncated():
    qr = QueryResult(columns=["x"], rows=[[42]], row_count=1, truncated=False)
    out = format_query_results(qr)
    assert "RESULT TRUNCATED" not in out


# ---------------------------------------------------------------------------
# format_schema_overview
# ---------------------------------------------------------------------------


def test_format_schema_overview_lists_tables():
    schema = SchemaInfo(
        db_type="postgres",
        db_name="db",
        tables=[
            TableInfo(name="users", columns=[ColumnInfo(name="id", data_type="int")], row_count=5)
        ],
    )
    out = format_schema_overview(schema)
    assert "users" in out and "Tables: 1" in out


def test_format_schema_overview_empty():
    out = format_schema_overview(SchemaInfo(tables=[]))
    assert out == "No tables found in the database."


def test_format_schema_overview_row_count_unknown():
    schema = SchemaInfo(
        db_type="mysql",
        db_name="mydb",
        tables=[TableInfo(name="orders", columns=[], row_count=None)],
    )
    out = format_schema_overview(schema)
    assert "| orders |" in out
    # unknown row count renders as "?"
    assert "| ? |" in out


def test_format_schema_overview_shows_db_name_and_type():
    schema = SchemaInfo(
        db_type="clickhouse",
        db_name="analytics",
        tables=[TableInfo(name="events", columns=[])],
    )
    out = format_schema_overview(schema)
    assert "analytics" in out
    assert "clickhouse" in out


# ---------------------------------------------------------------------------
# format_table_detail
# ---------------------------------------------------------------------------


def test_format_table_detail_not_found():
    out = format_table_detail(SchemaInfo(tables=[]), "ghost")
    assert "not found" in out


def test_format_table_detail_found():
    schema = SchemaInfo(
        tables=[
            TableInfo(
                name="users",
                columns=[ColumnInfo(name="id", data_type="int", is_primary_key=True)],
            )
        ]
    )
    out = format_table_detail(schema, "users")
    assert "## users" in out
    assert "| id |" in out
    assert "PK" in out


def test_format_table_detail_case_insensitive():
    """Lookup must be case-insensitive per the implementation."""
    schema = SchemaInfo(tables=[TableInfo(name="Users", columns=[])])
    out = format_table_detail(schema, "users")
    assert "not found" not in out
    assert "## Users" in out
