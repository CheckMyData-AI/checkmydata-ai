"""Unit tests for T11: FK-aware schema retrieval + distinct/numeric-format splicing.

Covers two changes:
1. DBIDX-D7 — _build_schema_doc splices column_distinct_values_json and
   numeric_format_notes so value-level queries retrieve the right table.
2. RET-R9 — expand_fk_hop expands a retrieved set by one FK hop so
   join/bridge tables with no lexical overlap are included before the cap.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from app.knowledge.schema_retriever import SchemaRetriever, expand_fk_hop
from app.models.db_index import DbIndex


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(
    *,
    table_name: str,
    business_description: str = "",
    data_patterns: str = "",
    column_notes: dict | None = None,
    distinct_values: dict | None = None,
    numeric_format_notes: dict | None = None,
    query_hints: str = "",
    relevance_score: int = 3,
    is_active: bool = True,
    table_schema: str = "public",
    connection_id: str = "conn-t11",
) -> DbIndex:
    return DbIndex(
        id=f"id-{table_schema}-{table_name}",
        connection_id=connection_id,
        table_name=table_name,
        table_schema=table_schema,
        column_count=len(column_notes or {}),
        row_count=100,
        sample_data_json="[]",
        is_active=is_active,
        relevance_score=relevance_score,
        business_description=business_description,
        data_patterns=data_patterns,
        column_notes_json=json.dumps(column_notes or {}),
        column_distinct_values_json=json.dumps(distinct_values or {}),
        query_hints=query_hints,
        numeric_format_notes=json.dumps(numeric_format_notes or {}),
        code_match_status="unknown",
        code_match_details="",
        indexed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


# ---------------------------------------------------------------------------
# DBIDX-D7: distinct-values and numeric-format-notes spliced into BM25 doc
# ---------------------------------------------------------------------------


class TestBuildSchemaDocSplice:
    """_build_schema_doc includes distinct values and numeric format notes."""

    def test_distinct_values_appear_in_doc(self):
        entry = _make_entry(
            table_name="orders",
            column_notes={"status": "order status"},
            distinct_values={"status": ["pending", "shipped", "cancelled"]},
        )
        doc = SchemaRetriever._build_schema_doc(entry)
        assert "shipped" in doc
        assert "pending" in doc
        assert "cancelled" in doc

    def test_numeric_format_note_appears_in_doc(self):
        entry = _make_entry(
            table_name="payments",
            column_notes={"amount_cents": "payment amount"},
            numeric_format_notes={"amount_cents": "stored in cents divide by 100 for dollars"},
        )
        doc = SchemaRetriever._build_schema_doc(entry)
        assert "cents" in doc
        assert "dollars" in doc

    def test_empty_distinct_values_no_crash(self):
        entry = _make_entry(table_name="users")
        doc = SchemaRetriever._build_schema_doc(entry)
        assert "users" in doc

    def test_malformed_json_fields_no_crash(self):
        entry = _make_entry(table_name="events")
        # Force malformed JSON to trigger the except branch
        entry.column_distinct_values_json = "not-json"
        entry.numeric_format_notes = "also-not-json"
        doc = SchemaRetriever._build_schema_doc(entry)
        assert "events" in doc


class TestValueLevelRetrieval:
    """A value-level query retrieves the table whose distinct values match."""

    def test_status_value_query_retrieves_orders(self, tmp_path):
        """Query 'orders where status = shipped' must surface orders table."""
        entries = [
            _make_entry(
                table_name="orders",
                business_description="customer orders",
                column_notes={"status": "order status"},
                distinct_values={"status": ["pending", "shipped", "cancelled"]},
            ),
            _make_entry(
                table_name="users",
                business_description="user accounts",
                column_notes={"email": "user email"},
            ),
            _make_entry(
                table_name="payments",
                business_description="payment records",
                column_notes={"amount_cents": "payment amount"},
                numeric_format_notes={"amount_cents": "stored in cents"},
            ),
        ]
        retriever = SchemaRetriever(data_dir=tmp_path / "bm25")
        retriever.build("conn-t11", indexed_sha="sha-v1", entries=entries)

        hits = retriever.query("conn-t11", "orders where status = shipped", k=5)
        names = [h["metadata"]["table_name"] for h in hits]
        assert "orders" in names, f"Expected 'orders' in {names}"
        assert names[0] == "orders", f"Expected 'orders' at rank 0, got {names}"

    def test_numeric_format_query_retrieves_payments(self, tmp_path):
        """Query about cents/dollars surfaces payments table."""
        entries = [
            _make_entry(
                table_name="payments",
                business_description="payment records",
                column_notes={"amount_cents": "amount"},
                numeric_format_notes={"amount_cents": "stored in cents divide by 100 for dollars"},
            ),
            _make_entry(
                table_name="users",
                business_description="user accounts",
            ),
            _make_entry(
                table_name="orders",
                business_description="customer orders",
            ),
        ]
        retriever = SchemaRetriever(data_dir=tmp_path / "bm25")
        retriever.build("conn-t11-num", indexed_sha="sha-n1", entries=entries)

        hits = retriever.query("conn-t11-num", "total revenue in dollars", k=5)
        names = [h["metadata"]["table_name"] for h in hits]
        assert "payments" in names, f"Expected 'payments' in {names}"


# ---------------------------------------------------------------------------
# RET-R9: FK-hop expansion
# ---------------------------------------------------------------------------


class TestExpandFkHop:
    """expand_fk_hop adds FK-linked tables to the retrieved set."""

    def _make_fk_map(self, fk_pairs: list[tuple[str, str]]) -> dict[str, set[str]]:
        """Build a {table -> set(referenced_tables)} FK map from pairs."""
        fk_map: dict[str, set[str]] = {}
        for src, tgt in fk_pairs:
            fk_map.setdefault(src, set()).add(tgt)
        return fk_map

    def test_fk_referenced_table_added(self):
        """Retrieving orders (which FKs to order_items) pulls in order_items."""
        all_entries = {
            "orders": _make_entry(table_name="orders"),
            "order_items": _make_entry(table_name="order_items"),
            "users": _make_entry(table_name="users"),
        }
        retrieved = [all_entries["orders"]]
        # orders -> order_items (FK direction: orders references order_items,
        # or order_items references orders — both should expand)
        fk_map = {"orders": {"order_items"}}

        result = expand_fk_hop(retrieved, fk_map, all_entries)
        result_names = {e.table_name for e in result}
        assert "order_items" in result_names
        assert "orders" in result_names

    def test_reverse_fk_also_expands(self):
        """If order_items has FK to orders and we retrieve orders, order_items is pulled."""
        all_entries = {
            "orders": _make_entry(table_name="orders"),
            "order_items": _make_entry(table_name="order_items"),
            "payments": _make_entry(table_name="payments"),
        }
        retrieved = [all_entries["orders"]]
        # order_items references orders (reverse direction)
        fk_map = {"order_items": {"orders"}}

        result = expand_fk_hop(retrieved, fk_map, all_entries)
        result_names = {e.table_name for e in result}
        assert "order_items" in result_names

    def test_unrelated_tables_not_pulled(self):
        """Tables with no FK relationship are not added."""
        all_entries = {
            "orders": _make_entry(table_name="orders"),
            "order_items": _make_entry(table_name="order_items"),
            "audit_logs": _make_entry(table_name="audit_logs"),
            "users": _make_entry(table_name="users"),
        }
        retrieved = [all_entries["orders"]]
        fk_map = {"orders": {"order_items"}}

        result = expand_fk_hop(retrieved, fk_map, all_entries)
        result_names = {e.table_name for e in result}
        assert "audit_logs" not in result_names
        assert "users" not in result_names

    def test_empty_fk_map_returns_original(self):
        """No FK map → original list returned unchanged."""
        all_entries = {
            "orders": _make_entry(table_name="orders"),
            "users": _make_entry(table_name="users"),
        }
        retrieved = [all_entries["orders"]]
        result = expand_fk_hop(retrieved, {}, all_entries)
        assert [e.table_name for e in result] == ["orders"]

    def test_already_retrieved_not_duplicated(self):
        """Tables already in the retrieved set are not added again."""
        all_entries = {
            "orders": _make_entry(table_name="orders"),
            "order_items": _make_entry(table_name="order_items"),
        }
        retrieved = [all_entries["orders"], all_entries["order_items"]]
        fk_map = {"orders": {"order_items"}}

        result = expand_fk_hop(retrieved, fk_map, all_entries)
        names = [e.table_name for e in result]
        assert names.count("order_items") == 1

    def test_retrieved_entries_stay_first(self):
        """Original retrieved entries maintain their position at the front."""
        all_entries = {
            "orders": _make_entry(table_name="orders"),
            "order_items": _make_entry(table_name="order_items"),
            "users": _make_entry(table_name="users"),
        }
        retrieved = [all_entries["orders"], all_entries["users"]]
        fk_map = {"orders": {"order_items"}}

        result = expand_fk_hop(retrieved, fk_map, all_entries)
        # Original entries come first
        assert result[0].table_name == "orders"
        assert result[1].table_name == "users"
        # FK-hop addition comes after
        assert result[2].table_name == "order_items"

    def test_missing_entry_in_all_entries_skipped(self):
        """If FK target not in all_entries (e.g. external schema), skip gracefully."""
        all_entries = {
            "orders": _make_entry(table_name="orders"),
        }
        retrieved = [all_entries["orders"]]
        fk_map = {"orders": {"nonexistent_table"}}

        result = expand_fk_hop(retrieved, fk_map, all_entries)
        names = {e.table_name for e in result}
        assert "nonexistent_table" not in names
        assert "orders" in names

    def test_chain_only_one_hop(self):
        """Only one hop is performed, not transitive expansion."""
        all_entries = {
            "a": _make_entry(table_name="a"),
            "b": _make_entry(table_name="b"),
            "c": _make_entry(table_name="c"),
        }
        retrieved = [all_entries["a"]]
        # a -> b -> c (chain)
        fk_map = {"a": {"b"}, "b": {"c"}}

        result = expand_fk_hop(retrieved, fk_map, all_entries)
        names = {e.table_name for e in result}
        assert "b" in names  # one hop
        assert "c" not in names  # two hops — not included
