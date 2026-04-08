"""Tests for the lightweight table resolver heuristics."""

from __future__ import annotations

from app.agents.table_resolver import (
    TableResolution,
    build_resolution_hints,
    parse_table_map,
    resolve_tables,
)

SAMPLE_MAP = (
    "orders(~50000, customer purchase orders), "
    "users(~12000, registered platform users), "
    "products(~800, product catalog with pricing), "
    "payments(~45000, payment transactions and refunds), "
    "categories(~25, product categories)"
)


class TestParseTableMap:
    def test_basic(self):
        result = parse_table_map(SAMPLE_MAP)
        assert "orders" in result
        assert "users" in result
        assert len(result) == 5

    def test_empty_string(self):
        assert parse_table_map("") == {}

    def test_description_extraction(self):
        result = parse_table_map("items(~10, inventory items)")
        assert "inventory items" in result["items"]


class TestResolveTablesExact:
    def test_exact_match(self):
        r = resolve_tables("Show me all orders", SAMPLE_MAP)
        assert "orders" in r.matched

    def test_plural_singular(self):
        r = resolve_tables("Show me each product", SAMPLE_MAP)
        assert "products" in r.matched

    def test_substring_match(self):
        r = resolve_tables("Show me payment data", SAMPLE_MAP)
        assert "payments" in r.matched

    def test_multiple_tables(self):
        r = resolve_tables("Compare orders and payments", SAMPLE_MAP)
        assert "orders" in r.matched
        assert "payments" in r.matched

    def test_case_insensitive(self):
        r = resolve_tables("Show me ORDERS", SAMPLE_MAP)
        assert "orders" in r.matched


class TestResolveTablesFuzzy:
    def test_keyword_to_description(self):
        r = resolve_tables("Show product catalog pricing", SAMPLE_MAP)
        assert "products" in r.matched or any("products" == f[1] for f in r.fuzzy)

    def test_no_match_goes_to_unresolved(self):
        r = resolve_tables("Show me the invoices", SAMPLE_MAP)
        assert "invoices" in r.unresolved or any("invoices" == f[0] for f in r.fuzzy)


class TestResolveTablesEdgeCases:
    def test_empty_question(self):
        r = resolve_tables("", SAMPLE_MAP)
        assert r == TableResolution()

    def test_empty_table_map(self):
        r = resolve_tables("Show me orders", "")
        assert r == TableResolution()

    def test_noise_only(self):
        r = resolve_tables("show me all the data", SAMPLE_MAP)
        assert not r.matched
        assert not r.fuzzy

    def test_no_false_positives_on_short_words(self):
        r = resolve_tables("is it ok?", SAMPLE_MAP)
        assert not r.matched


class TestBuildResolutionHints:
    def test_no_hints_when_all_matched(self):
        r = TableResolution(matched=["orders"], fuzzy=[], unresolved=[])
        assert build_resolution_hints(r) == ""

    def test_warning_when_unresolved_and_no_match(self):
        r = TableResolution(matched=[], fuzzy=[], unresolved=["invoices"])
        hints = build_resolution_hints(r)
        assert "WARNING" in hints
        assert "invoices" in hints
        assert "ask_user" in hints

    def test_note_for_fuzzy(self):
        r = TableResolution(matched=[], fuzzy=[("catalog", "products", 0.35)], unresolved=[])
        hints = build_resolution_hints(r)
        assert "NOTE" in hints
        assert "products" in hints

    def test_empty_resolution(self):
        r = TableResolution()
        assert build_resolution_hints(r) == ""

    def test_mixed_matched_and_unresolved(self):
        r = TableResolution(matched=["orders"], fuzzy=[], unresolved=["invoices"])
        hints = build_resolution_hints(r)
        assert "WARNING" in hints
        assert "'invoices'" in hints

    def test_fuzzy_notes_shown_even_when_matched(self):
        r = TableResolution(
            matched=["orders"],
            fuzzy=[("catalog", "products", 0.45)],
            unresolved=[],
        )
        hints = build_resolution_hints(r)
        assert "NOTE" in hints
        assert "'catalog'" in hints
        assert "'products'" in hints
