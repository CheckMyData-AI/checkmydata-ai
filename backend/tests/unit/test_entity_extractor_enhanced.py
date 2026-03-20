"""Tests for the enhanced entity extractor: query patterns, constant mappings, scope filters."""

import pytest

from app.knowledge.entity_extractor import (
    ConstantMapping,
    ProjectKnowledge,
    QueryPattern,
    ScopeFilter,
    _extract_constant_mappings,
    _extract_query_patterns,
    _extract_scope_filters,
)


@pytest.fixture
def knowledge():
    return ProjectKnowledge()


class TestExtractQueryPatterns:
    def test_sql_where_clause(self, knowledge):
        code = """
        result = db.execute("SELECT * FROM transactions WHERE status = 1")
        """
        _extract_query_patterns("app/services/payment.py", code, knowledge)
        assert len(knowledge.query_patterns) >= 1
        pat = knowledge.query_patterns[0]
        assert pat.table == "transactions"
        assert pat.column == "status"
        assert pat.value == "1"

    def test_orm_filter_chain(self, knowledge):
        code = """
        payments = Payment.filter(is_processed=True).all()
        """
        _extract_query_patterns("app/models/payment.py", code, knowledge)
        patterns = [p for p in knowledge.query_patterns if p.column == "is_processed"]
        assert len(patterns) >= 1

    def test_sqlalchemy_eq_filter(self, knowledge):
        code = """
        stmt = select(Transaction).where(Transaction.status == 1)
        """
        _extract_query_patterns("app/services/tx.py", code, knowledge)
        patterns = [p for p in knowledge.query_patterns if p.column == "status"]
        assert len(patterns) >= 1

    def test_no_false_positives(self, knowledge):
        code = """
        x = 1 + 2
        print("hello world")
        """
        _extract_query_patterns("app/utils.py", code, knowledge)
        assert len(knowledge.query_patterns) == 0


class TestExtractConstantMappings:
    def test_python_constant(self, knowledge):
        code = """
STATUS_ACTIVE = 1
STATUS_PENDING = 0
STATUS_FAILED = 2
        """
        _extract_constant_mappings("app/constants.py", code, knowledge)
        names = {cm.name for cm in knowledge.constant_mappings}
        assert "STATUS_ACTIVE" in names
        assert "STATUS_PENDING" in names

    def test_js_const(self, knowledge):
        code = """
const PAYMENT_STATUS_PROCESSED = 1;
const PAYMENT_STATUS_PENDING = 0;
        """
        _extract_constant_mappings("src/constants.js", code, knowledge)
        names = {cm.name for cm in knowledge.constant_mappings}
        assert "PAYMENT_STATUS_PROCESSED" in names

    def test_dict_mapping(self, knowledge):
        code = """
STATUS_MAPPING = {"0": "pending", "1": "active", "2": "failed"}
        """
        _extract_constant_mappings("app/constants.py", code, knowledge)
        mapping_entries = [cm for cm in knowledge.constant_mappings if "STATUS_MAPPING" in cm.name]
        assert len(mapping_entries) >= 2

    def test_no_false_positives(self, knowledge):
        code = """
x = 42
name = "Alice"
        """
        _extract_constant_mappings("app/utils.py", code, knowledge)
        assert len(knowledge.constant_mappings) == 0


class TestExtractScopeFilters:
    def test_rails_scope(self, knowledge):
        code = """
class Order < ApplicationRecord
  scope :active, -> { where(deleted_at: nil) }
  scope :completed, -> { where(status: 'completed') }
end
        """
        _extract_scope_filters("app/models/order.rb", code, knowledge)
        assert len(knowledge.scope_filters) >= 2
        names = {sf.name for sf in knowledge.scope_filters}
        assert "active" in names
        assert "completed" in names

    def test_laravel_scope(self, knowledge):
        code = """
class Order extends Model {
    public function scopeActive($query) {
        return $query->where('is_active', 1);
    }
}
        """
        _extract_scope_filters("app/Models/Order.php", code, knowledge)
        assert len(knowledge.scope_filters) >= 1
        assert knowledge.scope_filters[0].name == "Active"

    def test_no_false_positives(self, knowledge):
        code = """
def process_order(order_id):
    order = Order.get(order_id)
    return order.total
        """
        _extract_scope_filters("app/services/order.py", code, knowledge)
        assert len(knowledge.scope_filters) == 0


class TestProjectKnowledgeSerialization:
    def test_round_trip_new_fields(self):
        knowledge = ProjectKnowledge()
        knowledge.query_patterns.append(
            QueryPattern(
                table="orders",
                column="status",
                operator="=",
                value="1",
                file_path="app/services/order.py",
            )
        )
        knowledge.constant_mappings.append(
            ConstantMapping(
                name="STATUS_ACTIVE",
                value="1",
                context="STATUS_ACTIVE = 1",
                file_path="app/constants.py",
            )
        )
        knowledge.scope_filters.append(
            ScopeFilter(
                name="active",
                table="orders",
                filter_expression="where(deleted_at: nil)",
                file_path="app/models/order.rb",
            )
        )

        json_str = knowledge.to_json()
        restored = ProjectKnowledge.from_json(json_str)

        assert len(restored.query_patterns) == 1
        assert restored.query_patterns[0].table == "orders"
        assert len(restored.constant_mappings) == 1
        assert restored.constant_mappings[0].name == "STATUS_ACTIVE"
        assert len(restored.scope_filters) == 1
        assert restored.scope_filters[0].name == "active"
