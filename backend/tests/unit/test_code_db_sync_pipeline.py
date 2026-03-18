"""Unit tests for CodeDbSyncPipeline — table matching logic."""

from unittest.mock import MagicMock

from app.knowledge.code_db_sync_pipeline import CodeDbSyncPipeline
from app.knowledge.entity_extractor import (
    ColumnInfo,
    EntityInfo,
    ProjectKnowledge,
    TableUsage,
)
from app.models.db_index import DbIndex


def _make_db_entry(table_name: str, **overrides) -> DbIndex:
    defaults = {
        "id": f"db-{table_name}",
        "connection_id": "conn-1",
        "table_name": table_name,
        "table_schema": "public",
        "column_count": 5,
        "row_count": 100,
        "sample_data_json": "[]",
        "ordering_column": None,
        "latest_record_at": None,
        "is_active": True,
        "relevance_score": 3,
        "business_description": f"Table: {table_name}",
        "data_patterns": "",
        "column_notes_json": "{}",
        "query_hints": "",
        "code_match_status": "unknown",
        "code_match_details": "",
    }
    defaults.update(overrides)
    entry = MagicMock(spec=DbIndex)
    for k, v in defaults.items():
        setattr(entry, k, v)
    return entry


def _make_knowledge(
    entities: dict | None = None,
    table_usage: dict | None = None,
    enums: list | None = None,
    service_functions: list | None = None,
    validation_rules: list | None = None,
) -> ProjectKnowledge:
    return ProjectKnowledge(
        entities=entities or {},
        table_usage=table_usage or {},
        enums=enums or [],
        service_functions=service_functions or [],
        validation_rules=validation_rules or [],
    )


class TestMatchTables:
    def setup_method(self):
        self.pipeline = CodeDbSyncPipeline.__new__(CodeDbSyncPipeline)

    def test_db_only_table(self):
        knowledge = _make_knowledge()
        db_entries = [_make_db_entry("users")]

        results = self.pipeline._match_tables(knowledge, db_entries)

        assert len(results) == 1
        assert results[0].table_name == "users"
        assert results[0].has_code_info is False

    def test_code_entity_matches_db(self):
        entity = EntityInfo(
            name="User",
            table_name="users",
            file_path="models/user.py",
            columns=[ColumnInfo(name="id", col_type="Integer", is_pk=True)],
            relationships=["orders"],
            used_in_files=["services/user_svc.py"],
        )
        knowledge = _make_knowledge(entities={"User": entity})
        db_entries = [_make_db_entry("users")]

        results = self.pipeline._match_tables(knowledge, db_entries)

        assert len(results) == 1
        assert results[0].table_name == "users"
        assert results[0].has_code_info is True
        assert results[0].entity_name == "User"
        assert "Integer" in results[0].code_columns_json

    def test_code_only_table(self):
        entity = EntityInfo(
            name="AuditLog",
            table_name="audit_logs",
            file_path="models/audit.py",
            columns=[],
            relationships=[],
            used_in_files=[],
        )
        knowledge = _make_knowledge(entities={"AuditLog": entity})
        db_entries = []

        results = self.pipeline._match_tables(knowledge, db_entries)

        assert len(results) == 1
        assert results[0].table_name == "audit_logs"
        assert results[0].has_code_info is True
        assert results[0].entity_name == "AuditLog"

    def test_table_usage_without_entity(self):
        usage = TableUsage(
            table_name="orders",
            readers=["reports.py"],
            writers=["api.py"],
            orm_refs=[],
        )
        knowledge = _make_knowledge(table_usage={"orders": usage})
        db_entries = [_make_db_entry("orders")]

        results = self.pipeline._match_tables(knowledge, db_entries)

        assert len(results) == 1
        assert results[0].table_name == "orders"
        assert results[0].has_code_info is True
        assert results[0].read_count == 1
        assert results[0].write_count == 1

    def test_mixed_tables(self):
        entity = EntityInfo(
            name="Product",
            table_name="products",
            file_path="models/product.py",
            columns=[],
            relationships=[],
            used_in_files=[],
        )
        knowledge = _make_knowledge(entities={"Product": entity})
        db_entries = [
            _make_db_entry("products"),
            _make_db_entry("categories"),
        ]

        results = self.pipeline._match_tables(knowledge, db_entries)

        assert len(results) == 2
        names = {r.table_name for r in results}
        assert "products" in names
        assert "categories" in names

        products = next(r for r in results if r.table_name == "products")
        categories = next(r for r in results if r.table_name == "categories")
        assert products.has_code_info is True
        assert categories.has_code_info is False


class TestBuildDbContext:
    def setup_method(self):
        self.pipeline = CodeDbSyncPipeline.__new__(CodeDbSyncPipeline)

    def test_includes_description(self):
        entry = _make_db_entry("users", business_description="User accounts")
        result = self.pipeline._build_db_context(entry)
        assert "User accounts" in result

    def test_includes_row_count(self):
        entry = _make_db_entry("users", row_count=50000)
        result = self.pipeline._build_db_context(entry)
        assert "50,000" in result

    def test_includes_column_notes(self):
        entry = _make_db_entry("users", column_notes_json='{"email": "unique not null"}')
        result = self.pipeline._build_db_context(entry)
        assert "email" in result
        assert "unique" in result


class TestBuildCodeContext:
    def setup_method(self):
        self.pipeline = CodeDbSyncPipeline.__new__(CodeDbSyncPipeline)

    def test_entity_columns(self):
        entity = EntityInfo(
            name="Order",
            table_name="orders",
            file_path="models/order.py",
            columns=[
                ColumnInfo(name="amount", col_type="Integer"),
                ColumnInfo(name="status", col_type="String", enum_values=["pending", "paid"]),
            ],
            relationships=["user"],
            used_in_files=[],
        )
        knowledge = _make_knowledge()
        result = self.pipeline._build_code_context(entity, None, knowledge, "orders")
        assert "amount: Integer" in result
        assert "enum: pending, paid" in result
        assert "Relationships: user" in result

    def test_usage_info(self):
        usage = TableUsage(
            table_name="orders",
            readers=["report.py", "api.py"],
            writers=["service.py"],
            orm_refs=[],
        )
        knowledge = _make_knowledge()
        result = self.pipeline._build_code_context(None, usage, knowledge, "orders")
        assert "report.py" in result
        assert "service.py" in result

    def test_no_code_info(self):
        knowledge = _make_knowledge()
        result = self.pipeline._build_code_context(None, None, knowledge, "orders")
        assert result == ""
