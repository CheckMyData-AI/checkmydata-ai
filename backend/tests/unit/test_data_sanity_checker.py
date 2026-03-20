"""Unit tests for DataSanityChecker."""

import pytest

from app.core.data_sanity_checker import DataSanityChecker


@pytest.fixture
def checker():
    return DataSanityChecker()


class TestCheckAllZeroNull:
    def test_all_null_column(self, checker):
        rows = [{"a": None}, {"a": None}, {"a": None}]
        warnings = checker.check(rows, ["a"])
        assert len(warnings) == 1
        assert warnings[0].check_type == "all_null"
        assert warnings[0].column == "a"

    def test_all_zero_column(self, checker):
        rows = [{"val": 0}, {"val": 0}, {"val": 0}]
        warnings = checker.check(rows, ["val"])
        assert len(warnings) == 1
        assert warnings[0].check_type == "all_zero"
        assert warnings[0].column == "val"

    def test_normal_data_no_warnings(self, checker):
        rows = [{"val": 10}, {"val": 20}, {"val": 30}]
        warnings = checker.check(rows, ["val"])
        assert len(warnings) == 0

    def test_single_row_null_no_warning(self, checker):
        rows = [{"val": None}]
        warnings = checker.check(rows, ["val"])
        assert len(warnings) == 0

    def test_single_row_zero_no_warning(self, checker):
        rows = [{"val": 0}]
        warnings = checker.check(rows, ["val"])
        assert len(warnings) == 0

    def test_empty_rows_no_warnings(self, checker):
        warnings = checker.check([], ["val"])
        assert len(warnings) == 0

    def test_mixed_columns(self, checker):
        rows = [{"a": None, "b": 5}, {"a": None, "b": 10}]
        warnings = checker.check(rows, ["a", "b"])
        assert len(warnings) == 1
        assert warnings[0].column == "a"


class TestCheckTemporalAnomalies:
    def test_future_dates_detected(self, checker):
        rows = [{"dt": "2099-01-01"}]
        warnings = checker.check(rows, ["dt"])
        assert any(w.check_type == "future_dates" for w in warnings)

    def test_past_dates_no_warning(self, checker):
        rows = [{"dt": "2020-01-01"}, {"dt": "2021-06-15"}]
        warnings = checker.check(rows, ["dt"])
        future_warns = [w for w in warnings if w.check_type == "future_dates"]
        assert len(future_warns) == 0

    def test_non_date_strings_ignored(self, checker):
        rows = [{"name": "Alice"}, {"name": "Bob"}]
        warnings = checker.check(rows, ["name"])
        assert len(warnings) == 0


class TestCheckAggregationSanity:
    def test_percentage_sum_warning(self, checker):
        rows = [{"pct": 10}, {"pct": 20}, {"pct": 15}]
        warnings = checker.check(rows, ["pct"])
        assert any(w.check_type == "percentage_sum" for w in warnings)

    def test_percentage_near_100_no_warning(self, checker):
        rows = [{"pct": 33.3}, {"pct": 33.3}, {"pct": 33.4}]
        warnings = checker.check(rows, ["pct"])
        pct_warns = [w for w in warnings if w.check_type == "percentage_sum"]
        assert len(pct_warns) == 0

    def test_non_percentage_column_ignored(self, checker):
        rows = [{"count": 10}, {"count": 20}]
        warnings = checker.check(rows, ["count"])
        pct_warns = [w for w in warnings if w.check_type == "percentage_sum"]
        assert len(pct_warns) == 0


class TestCheckAgainstBenchmark:
    def test_ok_deviation(self, checker):
        rows = [{"total": 100}]
        result = checker.check_against_benchmark(rows, ["total"], 95.0, "revenue")
        assert result is not None
        assert result.level == "ok"
        assert result.deviation_pct < 30

    def test_warning_deviation(self, checker):
        rows = [{"total": 150}]
        result = checker.check_against_benchmark(rows, ["total"], 100.0, "revenue")
        assert result is not None
        assert result.level == "warning"

    def test_critical_deviation(self, checker):
        rows = [{"total": 500}]
        result = checker.check_against_benchmark(rows, ["total"], 100.0, "revenue")
        assert result is not None
        assert result.level == "critical"

    def test_zero_benchmark_returns_none(self, checker):
        rows = [{"total": 100}]
        result = checker.check_against_benchmark(rows, ["total"], 0.0, "revenue")
        assert result is None

    def test_no_numeric_value_returns_none(self, checker):
        rows = [{"name": "Alice"}]
        result = checker.check_against_benchmark(rows, ["name"], 100.0, "revenue")
        assert result is None


class TestFormatWarnings:
    def test_empty_warnings(self, checker):
        assert checker.format_warnings([]) == ""

    def test_formats_warnings(self, checker):
        rows = [{"a": None}, {"a": None}]
        warnings = checker.check(rows, ["a"])
        text = checker.format_warnings(warnings)
        assert "DATA SANITY WARNINGS" in text
        assert "all_null" in text
