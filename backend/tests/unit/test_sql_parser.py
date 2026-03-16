"""Tests for lightweight SQL parser."""

from app.core.sql_parser import (
    detect_aggregations,
    detect_subqueries,
    extract_column_table_pairs,
    extract_columns,
    extract_tables,
)


class TestExtractTables:
    def test_simple_select(self):
        tables = extract_tables("SELECT * FROM users")
        assert tables == ["users"]

    def test_join(self):
        tables = extract_tables(
            "SELECT u.name FROM users u "
            "JOIN orders o ON u.id = o.user_id"
        )
        assert "users" in tables
        assert "orders" in tables

    def test_left_join(self):
        tables = extract_tables(
            "SELECT * FROM users LEFT JOIN orders ON users.id = orders.uid"
        )
        assert "users" in tables
        assert "orders" in tables

    def test_multiple_joins(self):
        tables = extract_tables(
            "SELECT * FROM a "
            "INNER JOIN b ON a.id = b.a_id "
            "LEFT JOIN c ON b.id = c.b_id"
        )
        assert set(tables) == {"a", "b", "c"}

    def test_backtick_quoting(self):
        tables = extract_tables("SELECT * FROM `my_table`")
        assert "my_table" in tables

    def test_schema_qualified(self):
        tables = extract_tables("SELECT * FROM public.users")
        assert "users" in tables

    def test_cte_excluded(self):
        tables = extract_tables(
            "WITH cte AS (SELECT * FROM real_table) "
            "SELECT * FROM cte"
        )
        assert "real_table" in tables
        assert "cte" not in tables

    def test_subquery_inner_table(self):
        tables = extract_tables(
            "SELECT * FROM users WHERE id IN "
            "(SELECT user_id FROM orders)"
        )
        assert "users" in tables
        assert "orders" in tables

    def test_deduplication(self):
        tables = extract_tables(
            "SELECT * FROM users u JOIN users u2 ON u.id = u2.manager_id"
        )
        assert tables.count("users") == 1

    def test_insert_into(self):
        tables = extract_tables("INSERT INTO logs SELECT * FROM events")
        assert "logs" in tables
        assert "events" in tables


class TestExtractColumnTablePairs:
    def test_qualified(self):
        pairs = extract_column_table_pairs("SELECT users.id FROM users")
        assert ("id", "users") in pairs

    def test_multiple_qualified(self):
        pairs = extract_column_table_pairs(
            "SELECT u.name, o.total FROM users u JOIN orders o ON u.id = o.user_id"
        )
        cols = {(c, t) for c, t in pairs}
        assert ("name", "u") in cols
        assert ("total", "o") in cols


class TestExtractColumns:
    def test_qualified(self):
        cols = extract_columns("SELECT users.name, users.email FROM users")
        assert "name" in cols
        assert "email" in cols


class TestDetectSubqueries:
    def test_has_subquery(self):
        assert detect_subqueries(
            "SELECT * FROM users WHERE id IN (SELECT user_id FROM orders)"
        )

    def test_no_subquery(self):
        assert not detect_subqueries("SELECT * FROM users")


class TestDetectAggregations:
    def test_count(self):
        aggs = detect_aggregations("SELECT COUNT(*) FROM users")
        assert "COUNT" in aggs

    def test_multiple(self):
        aggs = detect_aggregations(
            "SELECT COUNT(*), SUM(total), AVG(price) FROM orders"
        )
        assert "COUNT" in aggs
        assert "SUM" in aggs
        assert "AVG" in aggs

    def test_none(self):
        aggs = detect_aggregations("SELECT * FROM users")
        assert aggs == []
