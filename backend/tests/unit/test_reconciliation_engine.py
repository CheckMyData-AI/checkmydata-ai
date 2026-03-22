"""Unit tests for ReconciliationEngine."""

from __future__ import annotations

import unittest

from app.core.reconciliation_engine import (
    Discrepancy,
    ReconciliationEngine,
)


class TestReconciliationEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = ReconciliationEngine()
        self.src_a = "Postgres Main"
        self.src_b = "Stripe DB"

    def test_matching_counts_no_discrepancies(self) -> None:
        counts = {"users": 1000, "orders": 500}
        result = self.engine.reconcile_row_counts(self.src_a, self.src_b, counts, counts)
        assert result == []

    def test_count_diff_warning(self) -> None:
        counts_a = {"users": 1000}
        counts_b = {"users": 940}
        result = self.engine.reconcile_row_counts(self.src_a, self.src_b, counts_a, counts_b)
        assert len(result) == 1
        assert result[0].severity == "warning"
        assert result[0].discrepancy_type == "count_diff"
        assert "users" in result[0].title

    def test_count_diff_critical(self) -> None:
        counts_a = {"orders": 1000}
        counts_b = {"orders": 700}
        result = self.engine.reconcile_row_counts(self.src_a, self.src_b, counts_a, counts_b)
        assert len(result) == 1
        assert result[0].severity == "critical"

    def test_table_only_in_one_source(self) -> None:
        counts_a = {"users": 1000, "payments": 200}
        counts_b = {"users": 1000}
        result = self.engine.reconcile_row_counts(self.src_a, self.src_b, counts_a, counts_b)
        assert len(result) == 1
        assert result[0].discrepancy_type == "missing_records"
        assert "payments" in result[0].title

    def test_tables_only_in_source_b(self) -> None:
        counts_a = {"users": 100}
        counts_b = {"users": 100, "events": 500}
        result = self.engine.reconcile_row_counts(self.src_a, self.src_b, counts_a, counts_b)
        assert len(result) == 1
        assert self.src_b in result[0].title

    def test_value_mismatch_critical(self) -> None:
        agg_a = {"total_revenue": 100000.0}
        agg_b = {"total_revenue": 90000.0}
        result = self.engine.reconcile_aggregate_values(self.src_a, self.src_b, agg_a, agg_b)
        assert len(result) == 1
        assert result[0].severity == "critical"
        assert result[0].discrepancy_type == "value_mismatch"

    def test_value_mismatch_warning(self) -> None:
        agg_a = {"order_count": 1000.0}
        agg_b = {"order_count": 985.0}
        result = self.engine.reconcile_aggregate_values(self.src_a, self.src_b, agg_a, agg_b)
        assert len(result) == 1
        assert result[0].severity == "warning"

    def test_value_match_no_discrepancy(self) -> None:
        agg = {"total": 500.0}
        result = self.engine.reconcile_aggregate_values(self.src_a, self.src_b, agg, agg)
        assert result == []

    def test_schema_extra_columns(self) -> None:
        schema_a = {"users": ["id", "name", "email", "phone"]}
        schema_b = {"users": ["id", "name", "email"]}
        result = self.engine.reconcile_schemas(self.src_a, self.src_b, schema_a, schema_b)
        assert len(result) == 1
        assert result[0].discrepancy_type == "schema_diff"
        assert "phone" in str(result[0].source_a_value)

    def test_schema_bidirectional_diff(self) -> None:
        schema_a = {"users": ["id", "name", "phone"]}
        schema_b = {"users": ["id", "name", "avatar"]}
        result = self.engine.reconcile_schemas(self.src_a, self.src_b, schema_a, schema_b)
        assert len(result) == 2

    def test_schema_match_no_discrepancy(self) -> None:
        schema = {"users": ["id", "name", "email"]}
        result = self.engine.reconcile_schemas(self.src_a, self.src_b, schema, schema)
        assert result == []

    def test_key_overlap_missing_from_b(self) -> None:
        keys_a = {"1", "2", "3", "4", "5"}
        keys_b = {"1", "2", "3"}
        result = self.engine.reconcile_key_overlap(
            self.src_a, self.src_b, keys_a, keys_b, "orders", "id"
        )
        assert len(result) == 1
        assert result[0].discrepancy_type == "missing_records"
        assert result[0].source_a_value == 2

    def test_key_overlap_bidirectional(self) -> None:
        keys_a = {"1", "2", "3"}
        keys_b = {"2", "3", "4"}
        result = self.engine.reconcile_key_overlap(
            self.src_a, self.src_b, keys_a, keys_b, "orders", "id"
        )
        assert len(result) == 2

    def test_key_overlap_perfect_match(self) -> None:
        keys = {"1", "2", "3"}
        result = self.engine.reconcile_key_overlap(
            self.src_a, self.src_b, keys, keys, "orders", "id"
        )
        assert result == []

    def test_build_report_clean(self) -> None:
        report = self.engine.build_report(self.src_a, self.src_b, "conn-a", "conn-b", [], 10)
        assert report.status == "clean"
        assert "in sync" in report.summary

    def test_build_report_with_discrepancies(self) -> None:
        discs = [
            Discrepancy(
                discrepancy_type="count_diff",
                severity="critical",
                title="Test",
                description="Test disc",
                source_a_name=self.src_a,
                source_b_name=self.src_b,
            ),
            Discrepancy(
                discrepancy_type="schema_diff",
                severity="warning",
                title="Schema",
                description="Schema disc",
                source_a_name=self.src_a,
                source_b_name=self.src_b,
            ),
        ]
        report = self.engine.build_report(self.src_a, self.src_b, "conn-a", "conn-b", discs, 5)
        assert report.status == "discrepancies_found"
        assert report.critical_count == 1
        assert report.warning_count == 1
        assert "2 discrepancies" in report.summary

    def test_report_to_dict(self) -> None:
        report = self.engine.build_report(self.src_a, self.src_b, "conn-a", "conn-b", [], 3)
        d = report.to_dict()
        assert d["status"] == "clean"
        assert d["total_checks"] == 3
        assert d["critical_count"] == 0
        assert isinstance(d["discrepancies"], list)

    def test_discrepancy_to_dict(self) -> None:
        disc = Discrepancy(
            discrepancy_type="value_mismatch",
            severity="warning",
            title="Revenue diff",
            description="Mismatch",
            source_a_name=self.src_a,
            source_b_name=self.src_b,
            source_a_value=100,
            source_b_value=95,
            difference_pct=5.0,
        )
        d = disc.to_dict()
        assert d["discrepancy_type"] == "value_mismatch"
        assert d["source_a_value"] == 100

    def test_report_sorts_critical_first(self) -> None:
        discs = [
            Discrepancy(
                discrepancy_type="schema_diff",
                severity="info",
                title="Info",
                description="",
                source_a_name=self.src_a,
                source_b_name=self.src_b,
            ),
            Discrepancy(
                discrepancy_type="count_diff",
                severity="critical",
                title="Critical",
                description="",
                source_a_name=self.src_a,
                source_b_name=self.src_b,
            ),
            Discrepancy(
                discrepancy_type="value_mismatch",
                severity="warning",
                title="Warning",
                description="",
                source_a_name=self.src_a,
                source_b_name=self.src_b,
            ),
        ]
        report = self.engine.build_report(self.src_a, self.src_b, "conn-a", "conn-b", discs, 3)
        assert report.discrepancies[0].severity == "critical"
        assert report.discrepancies[1].severity == "warning"
        assert report.discrepancies[2].severity == "info"


if __name__ == "__main__":
    unittest.main()
