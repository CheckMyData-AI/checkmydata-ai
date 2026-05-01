"""Unit tests for DataProcessor."""

from unittest.mock import MagicMock, patch

import pytest

from app.connectors.base import QueryResult
from app.services.data_processor import DataProcessor, get_data_processor
from app.services.geoip_service import GeoIPResult, GeoIPService


@pytest.fixture(autouse=True)
def _reset_singleton():
    import app.services.data_processor as mod

    mod._processor_instance = None
    yield
    mod._processor_instance = None


def _mock_geoip() -> GeoIPService:
    """Create a GeoIPService with a mocked lookup."""
    svc = GeoIPService()
    mapping = {
        "1.2.3.4": GeoIPResult(country_code="US", country_name="United States"),
        "5.6.7.8": GeoIPResult(country_code="DE", country_name="Germany"),
        "10.0.0.1": GeoIPResult(country_code="", country_name="Private Network", is_private=True),
        "": GeoIPResult(country_code="", country_name="Unknown"),
    }
    with patch("app.services.geoip_service._get_geoip") as mock_get:
        mock_geoip_obj = MagicMock()

        def _lookup(ip: str) -> GeoIPResult:
            return mapping.get(ip, GeoIPResult(country_code="", country_name="Unknown"))

        svc.lookup = _lookup  # type: ignore[assignment]
        mock_get.return_value = mock_geoip_obj
    return svc


class TestDataProcessorIPToCountry:
    def test_adds_country_columns(self):
        geoip = _mock_geoip()
        proc = DataProcessor(geoip=geoip)

        qr = QueryResult(
            columns=["id", "user_ip", "amount"],
            rows=[
                [1, "1.2.3.4", 100],
                [2, "5.6.7.8", 200],
            ],
            row_count=2,
        )

        result = proc.process(qr, "ip_to_country", {"column": "user_ip"})

        assert result.query_result.columns == [
            "id",
            "user_ip",
            "amount",
            "user_ip_country_code",
            "user_ip_country_name",
        ]
        assert len(result.query_result.rows) == 2
        assert result.query_result.rows[0][-2] == "US"
        assert result.query_result.rows[0][-1] == "United States"
        assert result.query_result.rows[1][-2] == "DE"
        assert result.query_result.rows[1][-1] == "Germany"
        assert result.query_result.row_count == 2

    def test_handles_none_ip(self):
        geoip = _mock_geoip()
        proc = DataProcessor(geoip=geoip)

        qr = QueryResult(
            columns=["ip"],
            rows=[[None]],
            row_count=1,
        )

        result = proc.process(qr, "ip_to_country", {"column": "ip"})
        assert result.query_result.rows[0][-2] == ""
        assert result.query_result.rows[0][-1] == "Unknown"

    def test_preserves_metadata(self):
        geoip = _mock_geoip()
        proc = DataProcessor(geoip=geoip)

        qr = QueryResult(
            columns=["ip"],
            rows=[["1.2.3.4"]],
            row_count=1,
            execution_time_ms=42.0,
            truncated=True,
        )

        result = proc.process(qr, "ip_to_country", {"column": "ip"})
        assert result.query_result.execution_time_ms == 42.0
        assert result.query_result.truncated is True

    def test_dedup_lookups_for_repeated_ips(self):
        """T18: duplicated IPs trigger a single GeoIP lookup per unique value."""
        geoip = _mock_geoip()
        tracked = MagicMock(side_effect=geoip.lookup)
        geoip.lookup = tracked  # type: ignore[assignment]
        proc = DataProcessor(geoip=geoip)

        qr = QueryResult(
            columns=["ip"],
            rows=[["1.2.3.4"]] * 50 + [["5.6.7.8"]] * 50,
            row_count=100,
        )
        result = proc.process(qr, "ip_to_country", {"column": "ip"})
        # Only two distinct IPs → exactly two lookup calls.
        assert tracked.call_count == 2
        assert "(2 unique)" in result.summary

    def test_summary_contains_stats(self):
        geoip = _mock_geoip()
        proc = DataProcessor(geoip=geoip)

        qr = QueryResult(
            columns=["ip"],
            rows=[["1.2.3.4"], ["1.2.3.4"], ["5.6.7.8"]],
            row_count=3,
        )

        result = proc.process(qr, "ip_to_country", {"column": "ip"})
        assert "US: 2 rows" in result.summary
        assert "DE: 1 rows" in result.summary
        assert "Resolved 3 IP addresses" in result.summary


class TestDataProcessorErrors:
    def test_unknown_operation(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(columns=["ip"], rows=[["1.2.3.4"]], row_count=1)

        with pytest.raises(ValueError, match="Unknown operation"):
            proc.process(qr, "nonexistent_op", {})

    def test_missing_column_param(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(columns=["ip"], rows=[["1.2.3.4"]], row_count=1)

        with pytest.raises(ValueError, match="requires a 'column' parameter"):
            proc.process(qr, "ip_to_country", {})

    def test_column_not_found(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(columns=["id", "amount"], rows=[[1, 100]], row_count=1)

        with pytest.raises(ValueError, match="Column 'ip' not found"):
            proc.process(qr, "ip_to_country", {"column": "ip"})


class TestOrchestratorToolRegistration:
    def test_process_data_included_with_connection(self):
        from app.agents.tools.orchestrator_tools import get_orchestrator_tools

        tools = get_orchestrator_tools(has_connection=True)
        names = [t.name for t in tools]
        assert "process_data" in names

    def test_process_data_excluded_without_connection(self):
        from app.agents.tools.orchestrator_tools import get_orchestrator_tools

        tools = get_orchestrator_tools(has_connection=False)
        names = [t.name for t in tools]
        assert "process_data" not in names

    def test_process_data_tool_has_correct_params(self):
        from app.agents.tools.orchestrator_tools import PROCESS_DATA_TOOL

        param_names = [p.name for p in PROCESS_DATA_TOOL.parameters]
        assert "operation" in param_names
        assert "column" in param_names
        assert "group_by" in param_names
        assert "aggregations" in param_names

        op_param = next(p for p in PROCESS_DATA_TOOL.parameters if p.name == "operation")
        assert op_param.enum == [
            "ip_to_country",
            "phone_to_country",
            "aggregate_data",
            "filter_data",
        ]


class TestDataProcessorPhoneToCountry:
    def test_adds_country_columns(self):
        geoip = _mock_geoip()
        proc = DataProcessor(geoip=geoip)

        qr = QueryResult(
            columns=["id", "phone"],
            rows=[
                [1, "+442071234567"],
                [2, "+491711234567"],
                [3, "+12125551234"],
            ],
            row_count=3,
        )

        result = proc.process(qr, "phone_to_country", {"column": "phone"})
        assert "phone_country_code" in result.query_result.columns
        assert "phone_country_name" in result.query_result.columns
        assert result.query_result.rows[0][-2] == "GB"
        assert result.query_result.rows[1][-2] == "DE"
        assert result.query_result.rows[2][-2] == "US"

    def test_handles_none_phone(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(columns=["phone"], rows=[[None]], row_count=1)
        result = proc.process(qr, "phone_to_country", {"column": "phone"})
        assert result.query_result.rows[0][-2] == ""
        assert result.query_result.rows[0][-1] == "Unknown"

    def test_handles_empty_phone(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(columns=["phone"], rows=[[""]], row_count=1)
        result = proc.process(qr, "phone_to_country", {"column": "phone"})
        assert result.query_result.rows[0][-2] == ""

    def test_missing_column_raises(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(columns=["id"], rows=[[1]], row_count=1)
        with pytest.raises(ValueError, match="requires a 'column' parameter"):
            proc.process(qr, "phone_to_country", {})

    def test_column_not_found_raises(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(columns=["id"], rows=[[1]], row_count=1)
        with pytest.raises(ValueError, match="Column 'phone' not found"):
            proc.process(qr, "phone_to_country", {"column": "phone"})

    def test_summary_contains_stats(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(
            columns=["phone"],
            rows=[["+442071234567"], ["+442071234568"], ["+491711234567"]],
            row_count=3,
        )
        result = proc.process(qr, "phone_to_country", {"column": "phone"})
        assert "GB: 2 rows" in result.summary
        assert "DE: 1 rows" in result.summary


class TestDataProcessorAggregateData:
    def test_basic_group_by_count(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(
            columns=["country", "amount"],
            rows=[
                ["US", 100],
                ["US", 200],
                ["DE", 50],
            ],
            row_count=3,
        )

        result = proc.process(
            qr,
            "aggregate_data",
            {
                "group_by": ["country"],
                "aggregations": {"*": "count"},
            },
        )

        assert result.query_result.columns == ["country", "count_all"]
        assert result.query_result.row_count == 2
        rows_dict = {r[0]: r[1] for r in result.query_result.rows}
        assert rows_dict["US"] == 2
        assert rows_dict["DE"] == 1

    def test_sum_and_avg(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(
            columns=["country", "amount"],
            rows=[
                ["US", 100],
                ["US", 200],
                ["DE", 50],
            ],
            row_count=3,
        )

        result = proc.process(
            qr,
            "aggregate_data",
            {
                "group_by": ["country"],
                "aggregations": {"amount": "sum", "*": "count"},
            },
        )

        assert "sum_amount" in result.query_result.columns
        assert "count_all" in result.query_result.columns
        rows_dict = {r[0]: (r[1], r[2]) for r in result.query_result.rows}
        assert rows_dict["US"] == (300.0, 2)
        assert rows_dict["DE"] == (50.0, 1)

    def test_avg_aggregation(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(
            columns=["country", "amount"],
            rows=[["US", 100], ["US", 300]],
            row_count=2,
        )

        result = proc.process(
            qr,
            "aggregate_data",
            {
                "group_by": ["country"],
                "aggregations": {"amount": "avg"},
            },
        )

        assert result.query_result.rows[0][1] == 200.0

    def test_min_max(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(
            columns=["country", "amount"],
            rows=[["US", 100], ["US", 300], ["US", 50]],
            row_count=3,
        )

        result = proc.process(
            qr,
            "aggregate_data",
            {
                "group_by": ["country"],
                "aggregations": {"amount": "min"},
            },
        )
        assert result.query_result.rows[0][1] == 50.0

        result = proc.process(
            qr,
            "aggregate_data",
            {
                "group_by": ["country"],
                "aggregations": {"amount": "max"},
            },
        )
        assert result.query_result.rows[0][1] == 300.0

    def test_multiple_group_by(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(
            columns=["country", "product", "amount"],
            rows=[
                ["US", "A", 100],
                ["US", "A", 200],
                ["US", "B", 50],
                ["DE", "A", 75],
            ],
            row_count=4,
        )

        result = proc.process(
            qr,
            "aggregate_data",
            {
                "group_by": ["country", "product"],
                "aggregations": {"*": "count", "amount": "sum"},
            },
        )

        assert result.query_result.row_count == 3
        assert result.query_result.columns == ["country", "product", "count_all", "sum_amount"]

    def test_none_values_excluded_from_numeric_aggs(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(
            columns=["country", "amount"],
            rows=[["US", 100], ["US", None], ["US", 200]],
            row_count=3,
        )

        result = proc.process(
            qr,
            "aggregate_data",
            {
                "group_by": ["country"],
                "aggregations": {"amount": "avg"},
            },
        )

        assert result.query_result.rows[0][1] == 150.0

    def test_missing_group_by_raises(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(columns=["country", "amount"], rows=[["US", 100]], row_count=1)
        with pytest.raises(ValueError, match="non-empty 'group_by'"):
            proc.process(qr, "aggregate_data", {"aggregations": {"*": "count"}})

    def test_missing_aggregations_raises(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(columns=["country", "amount"], rows=[["US", 100]], row_count=1)
        with pytest.raises(ValueError, match="non-empty 'aggregations'"):
            proc.process(qr, "aggregate_data", {"group_by": ["country"]})

    def test_invalid_group_by_column_raises(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(columns=["country", "amount"], rows=[["US", 100]], row_count=1)
        with pytest.raises(ValueError, match="group_by column 'bad' not found"):
            proc.process(
                qr,
                "aggregate_data",
                {
                    "group_by": ["bad"],
                    "aggregations": {"*": "count"},
                },
            )

    def test_unsupported_function_raises(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(columns=["country", "amount"], rows=[["US", 100]], row_count=1)
        with pytest.raises(ValueError, match="Unsupported aggregation 'percentile'"):
            proc.process(
                qr,
                "aggregate_data",
                {
                    "group_by": ["country"],
                    "aggregations": {"amount": "percentile"},
                },
            )

    def test_summary_content(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(
            columns=["country", "amount"],
            rows=[["US", 100], ["DE", 50]],
            row_count=2,
        )

        result = proc.process(
            qr,
            "aggregate_data",
            {
                "group_by": ["country"],
                "aggregations": {"*": "count"},
            },
        )

        assert "Aggregated 2 rows into 2 groups" in result.summary
        assert "country" in result.summary


class TestDataProcessorMultiAggPerColumn:
    """NC-1: Multiple aggregation functions on the same column."""

    def test_same_column_two_functions(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(
            columns=["country", "amount"],
            rows=[["US", 100], ["US", 200], ["DE", 50]],
            row_count=3,
        )

        result = proc.process(
            qr,
            "aggregate_data",
            {
                "group_by": ["country"],
                "aggregations": [("amount", "sum"), ("amount", "avg"), ("*", "count")],
            },
        )

        assert "sum_amount" in result.query_result.columns
        assert "avg_amount" in result.query_result.columns
        assert "count_all" in result.query_result.columns
        rows_dict = {r[0]: r[1:] for r in result.query_result.rows}
        assert rows_dict["US"] == [300.0, 150.0, 2]
        assert rows_dict["DE"] == [50.0, 50.0, 1]

    def test_five_functions_on_same_column(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(
            columns=["country", "amount"],
            rows=[["US", 100], ["US", 300], ["US", 200]],
            row_count=3,
        )

        result = proc.process(
            qr,
            "aggregate_data",
            {
                "group_by": ["country"],
                "aggregations": [
                    ("amount", "sum"),
                    ("amount", "avg"),
                    ("amount", "min"),
                    ("amount", "max"),
                    ("*", "count"),
                ],
            },
        )

        cols = result.query_result.columns
        expected = [
            "country",
            "sum_amount",
            "avg_amount",
            "min_amount",
            "max_amount",
            "count_all",
        ]
        assert cols == expected
        row = result.query_result.rows[0]
        assert row[1] == 600.0  # sum
        assert row[2] == 200.0  # avg
        assert row[3] == 100.0  # min
        assert row[4] == 300.0  # max
        assert row[5] == 3  # count

    def test_legacy_dict_format_still_works(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(
            columns=["country", "amount"],
            rows=[["US", 100], ["DE", 50]],
            row_count=2,
        )

        result = proc.process(
            qr,
            "aggregate_data",
            {
                "group_by": ["country"],
                "aggregations": {"amount": "sum", "*": "count"},
            },
        )

        assert "sum_amount" in result.query_result.columns
        assert "count_all" in result.query_result.columns

    def test_all_none_column_returns_none_for_numeric_aggs(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(
            columns=["country", "amount"],
            rows=[["US", None], ["US", None]],
            row_count=2,
        )

        result = proc.process(
            qr,
            "aggregate_data",
            {
                "group_by": ["country"],
                "aggregations": [("amount", "avg"), ("amount", "sum"), ("*", "count")],
            },
        )

        row = result.query_result.rows[0]
        assert row[1] is None  # avg
        assert row[2] is None  # sum
        assert row[3] == 2  # count


class TestCountDistinct:
    """NC-3: count_distinct aggregation."""

    def test_count_distinct_basic(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(
            columns=["country", "user_id"],
            rows=[
                ["US", "u1"],
                ["US", "u1"],
                ["US", "u2"],
                ["DE", "u3"],
                ["DE", "u3"],
            ],
            row_count=5,
        )

        result = proc.process(
            qr,
            "aggregate_data",
            {
                "group_by": ["country"],
                "aggregations": [("user_id", "count_distinct"), ("*", "count")],
            },
        )

        rows_dict = {r[0]: (r[1], r[2]) for r in result.query_result.rows}
        assert rows_dict["US"] == (2, 3)  # 2 unique users, 3 rows
        assert rows_dict["DE"] == (1, 2)  # 1 unique user, 2 rows

    def test_count_distinct_excludes_none(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(
            columns=["country", "user_id"],
            rows=[["US", "u1"], ["US", None], ["US", "u2"]],
            row_count=3,
        )

        result = proc.process(
            qr,
            "aggregate_data",
            {
                "group_by": ["country"],
                "aggregations": [("user_id", "count_distinct")],
            },
        )

        assert result.query_result.rows[0][1] == 2

    def test_count_distinct_all_same(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(
            columns=["country", "user_id"],
            rows=[["US", "u1"], ["US", "u1"], ["US", "u1"]],
            row_count=3,
        )

        result = proc.process(
            qr,
            "aggregate_data",
            {
                "group_by": ["country"],
                "aggregations": [("user_id", "count_distinct")],
            },
        )

        assert result.query_result.rows[0][1] == 1

    def test_count_distinct_star_raises(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(columns=["country", "amount"], rows=[["US", 100]], row_count=1)
        with pytest.raises(ValueError, match="count_distinct requires a column name"):
            proc.process(
                qr,
                "aggregate_data",
                {
                    "group_by": ["country"],
                    "aggregations": [("*", "count_distinct")],
                },
            )

    def test_count_distinct_all_none(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(
            columns=["country", "user_id"],
            rows=[["US", None], ["US", None]],
            row_count=2,
        )

        result = proc.process(
            qr,
            "aggregate_data",
            {
                "group_by": ["country"],
                "aggregations": [("user_id", "count_distinct")],
            },
        )

        assert result.query_result.rows[0][1] == 0


class TestMedianAggregation:
    """NC-11: median aggregation function."""

    def test_median_odd(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(
            columns=["country", "amount"],
            rows=[["US", 10], ["US", 30], ["US", 20]],
            row_count=3,
        )

        result = proc.process(
            qr,
            "aggregate_data",
            {
                "group_by": ["country"],
                "aggregations": [("amount", "median")],
            },
        )

        assert result.query_result.rows[0][1] == 20

    def test_median_even(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(
            columns=["country", "amount"],
            rows=[["US", 10], ["US", 30], ["US", 20], ["US", 40]],
            row_count=4,
        )

        result = proc.process(
            qr,
            "aggregate_data",
            {
                "group_by": ["country"],
                "aggregations": [("amount", "median")],
            },
        )

        assert result.query_result.rows[0][1] == 25.0


class TestSortByOrder:
    """NC-5: sort_by and order params for aggregate_data."""

    def test_sort_descending(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(
            columns=["country", "amount"],
            rows=[["US", 100], ["US", 200], ["DE", 50], ["FR", 300]],
            row_count=4,
        )

        result = proc.process(
            qr,
            "aggregate_data",
            {
                "group_by": ["country"],
                "aggregations": [("*", "count")],
                "sort_by": "count_all",
                "order": "desc",
            },
        )

        assert result.query_result.rows[0][0] == "US"
        assert result.query_result.rows[0][1] == 2

    def test_sort_ascending_explicit(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(
            columns=["country", "amount"],
            rows=[["US", 100], ["US", 200], ["DE", 50], ["FR", 150]],
            row_count=4,
        )

        result = proc.process(
            qr,
            "aggregate_data",
            {
                "group_by": ["country"],
                "aggregations": [("amount", "sum")],
                "sort_by": "sum_amount",
                "order": "asc",
            },
        )

        assert result.query_result.rows[0][0] == "DE"  # 50
        assert result.query_result.rows[1][0] == "FR"  # 150
        assert result.query_result.rows[2][0] == "US"  # 300

    def test_default_sort_alphabetical(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(
            columns=["country", "amount"],
            rows=[["FR", 100], ["DE", 200], ["US", 50]],
            row_count=3,
        )

        result = proc.process(
            qr,
            "aggregate_data",
            {
                "group_by": ["country"],
                "aggregations": [("*", "count")],
            },
        )

        assert [r[0] for r in result.query_result.rows] == ["DE", "FR", "US"]

    def test_invalid_sort_by_raises(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(columns=["country", "amount"], rows=[["US", 100]], row_count=1)
        with pytest.raises(ValueError, match="sort_by column 'nonexistent'"):
            proc.process(
                qr,
                "aggregate_data",
                {
                    "group_by": ["country"],
                    "aggregations": [("*", "count")],
                    "sort_by": "nonexistent",
                },
            )


class TestFilterData:
    """NC-9: filter_data operation."""

    def test_eq_filter(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(
            columns=["country", "amount"],
            rows=[["US", 100], ["DE", 50], ["US", 200]],
            row_count=3,
        )

        result = proc.process(
            qr,
            "filter_data",
            {
                "column": "country",
                "op": "eq",
                "value": "US",
            },
        )

        assert result.query_result.row_count == 2
        assert all(r[0] == "US" for r in result.query_result.rows)

    def test_neq_filter(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(
            columns=["country", "amount"],
            rows=[["US", 100], ["DE", 50], ["FR", 200]],
            row_count=3,
        )

        result = proc.process(
            qr,
            "filter_data",
            {
                "column": "country",
                "op": "neq",
                "value": "US",
            },
        )

        assert result.query_result.row_count == 2
        assert all(r[0] != "US" for r in result.query_result.rows)

    def test_contains_filter(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(
            columns=["name", "amount"],
            rows=[["United States", 100], ["Germany", 50], ["United Kingdom", 200]],
            row_count=3,
        )

        result = proc.process(
            qr,
            "filter_data",
            {
                "column": "name",
                "op": "contains",
                "value": "United",
            },
        )

        assert result.query_result.row_count == 2

    def test_gt_filter(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(
            columns=["country", "amount"],
            rows=[["US", 100], ["DE", 50], ["FR", 200]],
            row_count=3,
        )

        result = proc.process(
            qr,
            "filter_data",
            {
                "column": "amount",
                "op": "gt",
                "value": "75",
            },
        )

        assert result.query_result.row_count == 2

    def test_exclude_empty(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(
            columns=["country", "amount"],
            rows=[["US", 100], ["", 50], [None, 200]],
            row_count=3,
        )

        result = proc.process(
            qr,
            "filter_data",
            {
                "column": "country",
                "exclude_empty": True,
            },
        )

        assert result.query_result.row_count == 1
        assert result.query_result.rows[0][0] == "US"

    def test_in_filter(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(
            columns=["country", "amount"],
            rows=[["US", 100], ["DE", 50], ["FR", 200], ["GB", 150]],
            row_count=4,
        )

        result = proc.process(
            qr,
            "filter_data",
            {
                "column": "country",
                "op": "in",
                "value": "US,DE",
            },
        )

        assert result.query_result.row_count == 2

    def test_missing_column_raises(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(columns=["country"], rows=[["US"]], row_count=1)
        with pytest.raises(ValueError, match="requires a 'column' parameter"):
            proc.process(qr, "filter_data", {})

    def test_column_not_found_raises(self):
        proc = DataProcessor(geoip=_mock_geoip())
        qr = QueryResult(columns=["country"], rows=[["US"]], row_count=1)
        with pytest.raises(ValueError, match="Column 'bad' not found"):
            proc.process(qr, "filter_data", {"column": "bad"})


class TestGetDataProcessor:
    def test_returns_singleton(self):
        s1 = get_data_processor()
        s2 = get_data_processor()
        assert s1 is s2
