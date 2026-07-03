"""Characterization tests for schema_context_builder.format_table_context.

These tests lock the current output of the extracted function so that the
W0 refactor (pure move from SQLAgent._format_table_context) is behaviour-
preserving, and Wave 4 extensions cannot silently regress the baseline.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from app.agents.schema_context_builder import format_table_context
from app.connectors.base import ColumnInfo, ForeignKeyInfo, TableInfo

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _db(table_name="orders", description="Customer orders", row_count=1234, **kwargs):
    defaults = dict(
        table_name=table_name,
        business_description=description,
        row_count=row_count,
        column_distinct_values_json="{}",
        column_notes_json=None,
        numeric_format_notes="{}",
        query_hints=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _table(name="orders", columns=None, foreign_keys=None):
    cols = columns or [
        ColumnInfo(name="id", data_type="int", is_primary_key=True, is_nullable=False)
    ]
    return TableInfo(name=name, columns=cols, foreign_keys=foreign_keys or [])


# ---------------------------------------------------------------------------
# Core rendering
# ---------------------------------------------------------------------------


def test_renders_table_header_and_description():
    out = format_table_context(_db(), _table(), None, None)
    assert out.startswith("### orders")
    assert "Customer orders" in out
    assert "Rows: ~1,234" in out
    assert "id" in out


def test_renders_column_pk_and_nullable_flags():
    cols = [
        ColumnInfo(name="id", data_type="bigint", is_primary_key=True, is_nullable=False),
        ColumnInfo(name="note", data_type="text", is_primary_key=False, is_nullable=True),
    ]
    out = format_table_context(_db(), _table(columns=cols), None, None)
    assert "id: bigint PK" in out
    assert "note: text NULL" in out


def test_renders_foreign_keys():
    fks = [ForeignKeyInfo(column="user_id", references_table="users", references_column="id")]
    out = format_table_context(_db(), _table(foreign_keys=fks), None, None)
    assert "FKs:" in out
    assert "user_id -> users.id" in out


def test_skips_fks_when_empty():
    out = format_table_context(_db(), _table(foreign_keys=[]), None, None)
    assert "FKs:" not in out


# ---------------------------------------------------------------------------
# Distinct values
# ---------------------------------------------------------------------------


def test_renders_distinct_values():
    dv = json.dumps({"status": ["active", "inactive", "pending"]})
    db = _db(column_distinct_values_json=dv)
    out = format_table_context(db, _table(), None, None)
    assert "Distinct values:" in out
    assert "status: [active | inactive | pending]" in out


def test_skips_distinct_values_when_empty_json():
    db = _db(column_distinct_values_json="{}")
    out = format_table_context(db, _table(), None, None)
    assert "Distinct values:" not in out


def test_skips_distinct_values_on_bad_json():
    db = _db(column_distinct_values_json="NOT_JSON")
    out = format_table_context(db, _table(), None, None)
    assert "Distinct values:" not in out


# ---------------------------------------------------------------------------
# sync_entry fields
# ---------------------------------------------------------------------------


def test_renders_conversion_warnings_from_sync_entry():
    sync = SimpleNamespace(
        conversion_warnings="timestamp tz mismatch",
        column_sync_notes_json=None,
        business_logic_notes=None,
        query_recommendations=None,
    )
    out = format_table_context(_db(), _table(), sync, None)
    assert "WARNINGS: timestamp tz mismatch" in out


def test_renders_query_recommendations_from_sync_entry():
    sync = SimpleNamespace(
        conversion_warnings=None,
        column_sync_notes_json=None,
        business_logic_notes=None,
        query_recommendations="Always filter by tenant_id",
    )
    out = format_table_context(_db(), _table(), sync, None)
    assert "Query tips: Always filter by tenant_id" in out


def test_renders_business_logic_notes_truncated_at_200():
    long_note = "x" * 300
    sync = SimpleNamespace(
        conversion_warnings=None,
        column_sync_notes_json=None,
        business_logic_notes=long_note,
        query_recommendations=None,
    )
    out = format_table_context(_db(), _table(), sync, None)
    assert "Business logic: " + "x" * 200 in out
    # characters beyond 200 must not appear
    assert "x" * 201 not in out


# ---------------------------------------------------------------------------
# Column notes merging
# ---------------------------------------------------------------------------


def test_renders_column_notes_from_db_entry():
    db = _db(column_notes_json=json.dumps({"id": "primary surrogate key"}))
    out = format_table_context(db, _table(), None, None)
    assert "Column notes:" in out
    assert "id: primary surrogate key" in out


def test_merges_sync_notes_with_db_notes():
    db = _db(column_notes_json=json.dumps({"id": "pk"}))
    sync = SimpleNamespace(
        conversion_warnings=None,
        column_sync_notes_json=json.dumps({"id": "auto-increment", "name": "display name"}),
        business_logic_notes=None,
        query_recommendations=None,
    )
    out = format_table_context(db, _table(), sync, None)
    assert "Column notes:" in out
    # "pk" and "auto-increment" merged with "; "
    assert "pk; auto-increment" in out
    assert "name: display name" in out


def test_sync_note_not_duplicated_when_identical():
    db = _db(column_notes_json=json.dumps({"id": "surrogate pk"}))
    sync = SimpleNamespace(
        conversion_warnings=None,
        column_sync_notes_json=json.dumps({"id": "surrogate pk"}),
        business_logic_notes=None,
        query_recommendations=None,
    )
    out = format_table_context(db, _table(), sync, None)
    # Should appear once, not twice with "; "
    assert "surrogate pk; surrogate pk" not in out
    assert "surrogate pk" in out


# ---------------------------------------------------------------------------
# Numeric format notes
# ---------------------------------------------------------------------------


def test_renders_numeric_format_notes():
    db = _db(numeric_format_notes=json.dumps({"price": "USD cents"}))
    out = format_table_context(db, _table(), None, None)
    assert "Numeric formats:" in out
    assert "price: USD cents" in out


# ---------------------------------------------------------------------------
# Query hints
# ---------------------------------------------------------------------------


def test_renders_query_hints():
    db = _db(query_hints="Use index idx_orders_created_at for date filters")
    out = format_table_context(db, _table(), None, None)
    assert "Query hints: Use index idx_orders_created_at for date filters" in out


# ---------------------------------------------------------------------------
# knowledge / code usage
# ---------------------------------------------------------------------------


def test_renders_code_usage_from_knowledge():
    entity = SimpleNamespace(
        table_name="orders",
        read_queries=42,
        write_queries=7,
        graph_callers=None,
    )
    knowledge = SimpleNamespace(entities={"OrderModel": entity})
    out = format_table_context(_db(), _table(), None, knowledge)
    assert "Code usage: 42 reads, 7 writes" in out


def test_no_code_usage_when_knowledge_is_none():
    out = format_table_context(_db(), _table(), None, None)
    assert "Code usage:" not in out


def test_no_code_usage_when_table_not_in_knowledge():
    entity = SimpleNamespace(
        table_name="products",
        read_queries=5,
        write_queries=1,
        graph_callers=None,
    )
    knowledge = SimpleNamespace(entities={"ProductModel": entity})
    out = format_table_context(_db(), _table(), None, knowledge)
    assert "Code usage:" not in out


# ---------------------------------------------------------------------------
# Output always ends with trailing newline separator
# ---------------------------------------------------------------------------


def test_output_ends_with_empty_line():
    out = format_table_context(_db(), _table(), None, None)
    # The method appends "" and joins with "\n", so the last char is "\n"
    assert out.endswith("\n")


# ---------------------------------------------------------------------------
# None schema_table is handled gracefully
# ---------------------------------------------------------------------------


def test_no_schema_table_still_renders_header():
    out = format_table_context(_db(), None, None, None)
    assert "### orders" in out
    assert "Customer orders" in out
    assert "Columns:" not in out
