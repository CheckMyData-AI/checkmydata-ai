"""Tests for schema hints utility."""

from app.connectors.base import ColumnInfo, ForeignKeyInfo, SchemaInfo, TableInfo
from app.core.schema_hints import (
    find_similar_columns,
    find_similar_tables,
    get_related_tables,
    get_table_detail,
    list_all_tables_summary,
)


def _make_schema() -> SchemaInfo:
    return SchemaInfo(
        tables=[
            TableInfo(
                name="users",
                columns=[
                    ColumnInfo(name="id", data_type="int", is_primary_key=True),
                    ColumnInfo(name="username", data_type="varchar"),
                    ColumnInfo(name="email", data_type="varchar"),
                    ColumnInfo(name="created_at", data_type="timestamp"),
                ],
                row_count=1000,
            ),
            TableInfo(
                name="orders",
                columns=[
                    ColumnInfo(name="id", data_type="int", is_primary_key=True),
                    ColumnInfo(name="user_id", data_type="int"),
                    ColumnInfo(name="total", data_type="decimal"),
                    ColumnInfo(name="status", data_type="varchar"),
                ],
                foreign_keys=[
                    ForeignKeyInfo(
                        column="user_id",
                        references_table="users",
                        references_column="id",
                    ),
                ],
                row_count=5000,
            ),
            TableInfo(
                name="products",
                columns=[
                    ColumnInfo(name="id", data_type="int", is_primary_key=True),
                    ColumnInfo(name="name", data_type="varchar"),
                    ColumnInfo(name="price", data_type="decimal"),
                ],
            ),
        ],
        db_type="postgresql",
        db_name="test",
    )


class TestFindSimilarColumns:
    def test_exact_match(self):
        schema = _make_schema()
        results = find_similar_columns("username", schema)
        assert any(col == "username" for _, col, _ in results)

    def test_fuzzy_match(self):
        schema = _make_schema()
        results = find_similar_columns("user_name", schema, threshold=0.5)
        assert len(results) > 0
        assert any("user" in col.lower() for _, col, _ in results)

    def test_no_match(self):
        schema = _make_schema()
        results = find_similar_columns("zzz_nonexistent", schema, threshold=0.9)
        assert len(results) == 0

    def test_multi_table(self):
        schema = _make_schema()
        results = find_similar_columns("id", schema)
        tables = [t for t, _, _ in results]
        assert len(tables) >= 2


class TestFindSimilarTables:
    def test_exact(self):
        schema = _make_schema()
        results = find_similar_tables("users", schema)
        assert any(t == "users" for t, _ in results)

    def test_fuzzy(self):
        schema = _make_schema()
        results = find_similar_tables("user", schema, threshold=0.5)
        assert len(results) > 0

    def test_no_match(self):
        schema = _make_schema()
        results = find_similar_tables("zzz", schema, threshold=0.9)
        assert len(results) == 0


class TestGetTableDetail:
    def test_existing_table(self):
        schema = _make_schema()
        detail = get_table_detail("users", schema)
        assert "users" in detail
        assert "username" in detail
        assert "email" in detail

    def test_missing_table(self):
        schema = _make_schema()
        detail = get_table_detail("nonexistent", schema)
        assert "not found" in detail.lower()

    def test_includes_fk(self):
        schema = _make_schema()
        detail = get_table_detail("orders", schema)
        assert "FK" in detail
        assert "users" in detail


class TestGetRelatedTables:
    def test_outgoing_fk(self):
        schema = _make_schema()
        related = get_related_tables("orders", schema)
        assert "users" in related

    def test_incoming_fk(self):
        schema = _make_schema()
        related = get_related_tables("users", schema)
        assert "orders" in related

    def test_no_relations(self):
        schema = _make_schema()
        related = get_related_tables("products", schema)
        assert related == []


class TestListAllTablesSummary:
    def test_all_tables_listed(self):
        schema = _make_schema()
        summary = list_all_tables_summary(schema)
        assert "users" in summary
        assert "orders" in summary
        assert "products" in summary
