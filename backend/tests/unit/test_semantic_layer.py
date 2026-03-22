"""Unit tests for SemanticLayerService."""

from __future__ import annotations

import json
import unittest

from app.core.semantic_layer import (
    MetricCandidate,
    SemanticLayerService,
)


class TestSemanticLayerService(unittest.TestCase):
    def setUp(self) -> None:
        self.svc = SemanticLayerService()

    def _make_entry(
        self,
        table: str,
        columns: dict[str, str],
        biz_desc: str = "",
    ) -> dict:
        return {
            "table_name": table,
            "column_notes_json": json.dumps(columns),
            "column_distinct_values_json": "{}",
            "business_description": biz_desc,
            "data_patterns": "",
        }

    def test_discover_revenue_metric(self) -> None:
        entries = [self._make_entry("orders", {"total_revenue": "Total order revenue"})]
        candidates = self.svc.discover_metrics_from_index(entries, "conn-1")
        assert len(candidates) == 1
        c = candidates[0]
        assert c.source_table == "orders"
        assert c.source_column == "total_revenue"
        assert c.aggregation == "SUM"
        assert c.unit == "$"
        assert c.category == "revenue"
        assert c.canonical_name == "revenue"
        assert c.confidence > 0.3

    def test_discover_count_metric(self) -> None:
        entries = [self._make_entry("analytics", {"page_views": "Number of page views"})]
        candidates = self.svc.discover_metrics_from_index(entries)
        assert len(candidates) == 1
        assert candidates[0].aggregation == "COUNT"
        assert candidates[0].unit == "count"

    def test_discover_rate_metric(self) -> None:
        entries = [self._make_entry("funnel", {"conversion_rate": "Signup conversion"})]
        candidates = self.svc.discover_metrics_from_index(entries)
        assert len(candidates) == 1
        assert candidates[0].aggregation == "AVG"
        assert candidates[0].unit == "%"
        assert candidates[0].canonical_name == "conversion_rate"

    def test_low_confidence_filtered_out(self) -> None:
        entries = [self._make_entry("misc", {"some_id": ""})]
        candidates = self.svc.discover_metrics_from_index(entries)
        assert len(candidates) == 0

    def test_multiple_columns_per_table(self) -> None:
        entries = [
            self._make_entry(
                "transactions",
                {
                    "amount": "Transaction amount",
                    "fee": "Processing fee",
                    "status": "Transaction status",
                },
            )
        ]
        candidates = self.svc.discover_metrics_from_index(entries)
        names = [c.source_column for c in candidates]
        assert "amount" in names
        assert "fee" in names

    def test_normalize_same_canonical(self) -> None:
        candidates = [
            MetricCandidate(
                name="orders.total_revenue",
                display_name="Total Revenue",
                canonical_name="revenue",
                description="",
                category="revenue",
                source_table="orders",
                source_column="total_revenue",
                aggregation="SUM",
                unit="$",
                data_type="numeric",
                confidence=0.8,
                connection_id="conn-1",
            ),
            MetricCandidate(
                name="payments.revenue",
                display_name="Revenue",
                canonical_name="revenue",
                description="",
                category="revenue",
                source_table="payments",
                source_column="revenue",
                aggregation="SUM",
                unit="$",
                data_type="numeric",
                confidence=0.7,
                connection_id="conn-2",
            ),
        ]
        results = self.svc.normalize_across_connections(candidates)
        assert len(results) == 1
        assert results[0].canonical_name == "revenue"
        assert len(results[0].variants) == 2
        assert results[0].confidence > 0.8

    def test_normalize_different_canonical(self) -> None:
        candidates = [
            MetricCandidate(
                name="t.revenue",
                display_name="Revenue",
                canonical_name="revenue",
                description="",
                category="revenue",
                source_table="t",
                source_column="revenue",
                aggregation="SUM",
                unit="$",
                data_type="numeric",
                confidence=0.7,
            ),
            MetricCandidate(
                name="t.users",
                display_name="Users",
                canonical_name="users",
                description="",
                category="engagement",
                source_table="t",
                source_column="users",
                aggregation="COUNT",
                unit="count",
                data_type="numeric",
                confidence=0.6,
            ),
        ]
        results = self.svc.normalize_across_connections(candidates)
        assert len(results) == 2

    def test_normalize_empty(self) -> None:
        results = self.svc.normalize_across_connections([])
        assert results == []

    def test_canonical_name_mapping(self) -> None:
        assert self.svc._normalize_name("total_revenue") == "revenue"
        assert self.svc._normalize_name("mau") == "active_users"
        assert self.svc._normalize_name("ltv") == "lifetime_value"
        assert self.svc._normalize_name("unknown_metric") == "unknown_metric"

    def test_infer_aggregation(self) -> None:
        assert self.svc._infer_aggregation("total_revenue")[0] == "SUM"
        assert self.svc._infer_aggregation("conversion_rate")[0] == "AVG"
        assert self.svc._infer_aggregation("page_views")[0] == "COUNT"
        assert self.svc._infer_aggregation("some_id")[0] == ""

    def test_infer_unit(self) -> None:
        assert self.svc._infer_unit("revenue") == "$"
        assert self.svc._infer_unit("conversion_rate") == "%"
        assert self.svc._infer_unit("users") == "count"
        assert self.svc._infer_unit("unknown") == ""

    def test_metric_candidate_to_dict(self) -> None:
        c = MetricCandidate(
            name="t.col",
            display_name="Col",
            canonical_name="col",
            description="Test",
            category="general",
            source_table="t",
            source_column="col",
            aggregation="SUM",
            unit="$",
            data_type="numeric",
            confidence=0.5,
        )
        d = c.to_dict()
        assert d["name"] == "t.col"
        assert d["aggregation"] == "SUM"

    def test_normalization_result_to_dict(self) -> None:
        from app.core.semantic_layer import NormalizationResult

        nr = NormalizationResult(
            canonical_name="revenue",
            display_name="Revenue",
            variants=[
                {
                    "name": "t.rev",
                    "connection_id": "c1",
                    "source_table": "t",
                    "source_column": "rev",
                }
            ],
            category="revenue",
            aggregation="SUM",
            unit="$",
            confidence=0.8,
        )
        d = nr.to_dict()
        assert d["canonical_name"] == "revenue"
        assert len(d["variants"]) == 1

    def test_parse_json_valid(self) -> None:
        result = self.svc._parse_json('{"a": 1}')
        assert result == {"a": 1}

    def test_parse_json_invalid(self) -> None:
        result = self.svc._parse_json("not json")
        assert result == {}

    def test_parse_json_empty(self) -> None:
        result = self.svc._parse_json("")
        assert result == {}

    def test_business_description_used_as_fallback(self) -> None:
        entries = [
            self._make_entry(
                "sales",
                {"revenue": ""},
                biz_desc="Monthly sales data",
            )
        ]
        candidates = self.svc.discover_metrics_from_index(entries)
        assert len(candidates) == 1
        assert "Monthly sales data" in candidates[0].description


if __name__ == "__main__":
    unittest.main()
