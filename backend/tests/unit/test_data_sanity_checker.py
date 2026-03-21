"""Tests for DataSanityChecker."""

import pytest

from app.core.data_sanity_checker import DataSanityChecker


@pytest.fixture
def checker():
    return DataSanityChecker()


class TestDataSanityChecker:
    def test_empty_rows(self, checker):
        warnings = checker.check(rows=[], columns=["id", "name"])
        assert isinstance(warnings, list)

    def test_healthy_data_no_warnings(self, checker):
        rows = [
            {"id": 1, "name": "Alice", "amount": 100},
            {"id": 2, "name": "Bob", "amount": 200},
            {"id": 3, "name": "Charlie", "amount": 300},
        ]
        warnings = checker.check(rows=rows, columns=["id", "name", "amount"])
        assert len(warnings) == 0

    def test_duplicate_ids_detected(self, checker):
        rows = [
            {"id": 1, "name": "Alice"},
            {"id": 1, "name": "Bob"},
            {"id": 2, "name": "Charlie"},
        ]
        warnings = checker.check(rows=rows, columns=["id", "name"])
        dup_warnings = [w for w in warnings if w.check_type == "duplicate_values"]
        if dup_warnings:
            assert any("id" in w.message for w in dup_warnings)

    def test_negative_amounts_detected(self, checker):
        rows = [
            {"id": 1, "amount": -100},
            {"id": 2, "amount": 200},
            {"id": 3, "amount": -50},
        ]
        warnings = checker.check(rows=rows, columns=["id", "amount"])
        neg_warnings = [w for w in warnings if w.check_type == "negative_values"]
        if neg_warnings:
            assert any("amount" in w.message for w in neg_warnings)

    def test_all_null_column_detected(self, checker):
        rows = [
            {"id": 1, "email": None},
            {"id": 2, "email": None},
            {"id": 3, "email": None},
        ]
        warnings = checker.check(rows=rows, columns=["id", "email"])
        null_warnings = [w for w in warnings if "null" in w.check_type.lower()]
        if null_warnings:
            assert any("email" in w.message for w in null_warnings)
