from app.api.routes.chat import _build_raw_result
from app.connectors.base import QueryResult
from app.viz.chart import (
    _auto_detect_columns,
    _normalize_config,
    _resolve_col_idx,
    _safe_numeric,
    generate_bar_chart,
    generate_line_chart,
    generate_pie_chart,
    generate_scatter,
)
from app.viz.export import export_csv, export_json, export_xlsx
from app.viz.renderer import render
from app.viz.table import format_table
from app.viz.text import format_text
from app.viz.utils import serialize_value


def _sample_result():
    return QueryResult(
        columns=["name", "count", "total"],
        rows=[
            ["Alice", 10, 500],
            ["Bob", 20, 800],
            ["Carol", 15, 600],
        ],
        row_count=3,
        execution_time_ms=12.5,
    )


class TestTable:
    def test_basic_format(self):
        result = format_table(_sample_result())
        assert result["total_rows"] == 3
        assert len(result["rows"]) == 3
        assert result["columns"] == ["name", "count", "total"]

    def test_pagination(self):
        result = format_table(_sample_result(), {"page": 1, "page_size": 2})
        assert len(result["rows"]) == 2
        assert result["total_pages"] == 2


class TestText:
    def test_empty_result(self):
        result = format_text(QueryResult(row_count=0), "No data")
        assert result["type"] == "text"
        assert "No data" in result["content"]

    def test_single_number(self):
        result = format_text(QueryResult(columns=["total"], rows=[[42]], row_count=1))
        assert result["type"] == "number"
        assert result["value"] == 42

    def test_single_row(self):
        result = format_text(
            QueryResult(
                columns=["name", "age"],
                rows=[["Alice", 30]],
                row_count=1,
            )
        )
        assert result["type"] == "key_value"


class TestChart:
    def test_bar_chart(self):
        config = {"labels_column": "name", "data_columns": ["count", "total"]}
        chart = generate_bar_chart(_sample_result(), config)
        assert chart["type"] == "bar"
        assert len(chart["data"]["labels"]) == 3
        assert len(chart["data"]["datasets"]) == 2

    def test_line_chart(self):
        config = {"labels_column": "name", "data_columns": ["count"]}
        chart = generate_line_chart(_sample_result(), config)
        assert chart["type"] == "line"

    def test_pie_chart(self):
        config = {"labels_column": "name", "data_column": "count"}
        chart = generate_pie_chart(_sample_result(), config)
        assert chart["type"] == "pie"
        assert len(chart["data"]["labels"]) == 3

    def test_bar_chart_with_x_y_keys(self):
        """LLM may return x/y instead of labels_column/data_columns."""
        config = {"x": "name", "y": "count"}
        chart = generate_bar_chart(_sample_result(), config)
        assert chart["type"] == "bar"
        assert chart["data"]["labels"] == ["Alice", "Bob", "Carol"]
        assert len(chart["data"]["datasets"]) == 1
        assert chart["data"]["datasets"][0]["label"] == "count"

    def test_line_chart_with_group_by(self):
        """Pivot rows by a category column into multi-series datasets."""
        result = QueryResult(
            columns=["month", "source", "revenue"],
            rows=[
                ["Jan", "Google", 100],
                ["Jan", "Facebook", 50],
                ["Feb", "Google", 150],
                ["Feb", "Facebook", 80],
                ["Mar", "Google", 200],
                ["Mar", "Facebook", 120],
            ],
            row_count=6,
            execution_time_ms=10,
        )
        config = {
            "labels_column": "month",
            "data_columns": ["revenue"],
            "group_by": "source",
        }
        chart = generate_line_chart(result, config)
        assert chart["type"] == "line"
        assert chart["data"]["labels"] == ["Jan", "Feb", "Mar"]
        ds_labels = {ds["label"] for ds in chart["data"]["datasets"]}
        assert ds_labels == {"Google", "Facebook"}
        google_ds = next(ds for ds in chart["data"]["datasets"] if ds["label"] == "Google")
        assert google_ds["data"] == [100, 150, 200]

    def test_bar_chart_with_group_by(self):
        result = QueryResult(
            columns=["month", "source", "revenue"],
            rows=[
                ["Jan", "A", 10],
                ["Jan", "B", 20],
                ["Feb", "A", 30],
                ["Feb", "B", 40],
            ],
            row_count=4,
            execution_time_ms=5,
        )
        config = {
            "labels_column": "month",
            "data_columns": ["revenue"],
            "group_by": "source",
        }
        chart = generate_bar_chart(result, config)
        assert chart["type"] == "bar"
        assert chart["data"]["labels"] == ["Jan", "Feb"]
        assert len(chart["data"]["datasets"]) == 2

    def test_line_chart_with_legacy_x_column_y_column(self):
        """Backward compat: x_column/y_column should be normalized."""
        config = {"x_column": "name", "y_column": "count"}
        chart = generate_line_chart(_sample_result(), config)
        assert chart["type"] == "line"
        assert chart["data"]["labels"] == ["Alice", "Bob", "Carol"]
        assert len(chart["data"]["datasets"]) == 1


class TestExport:
    def test_csv(self):
        csv_str = export_csv(_sample_result())
        lines = csv_str.strip().split("\n")
        assert len(lines) == 4
        assert "name" in lines[0]

    def test_json(self):
        import json

        json_str = export_json(_sample_result())
        data = json.loads(json_str)
        assert len(data) == 3
        assert data[0]["name"] == "Alice"

    def test_xlsx(self):
        xlsx_bytes = export_xlsx(_sample_result())
        assert isinstance(xlsx_bytes, bytes)
        assert len(xlsx_bytes) > 0


class TestSerializeValue:
    def test_none(self):
        assert serialize_value(None) is None

    def test_primitives(self):
        assert serialize_value(42) == 42
        assert serialize_value(3.14) == 3.14
        assert serialize_value("hello") == "hello"
        assert serialize_value(True) is True

    def test_decimal(self):
        from decimal import Decimal
        assert serialize_value(Decimal("19.99")) == 19.99

    def test_bytes(self):
        assert serialize_value(b"\xab\xcd") == "abcd"

    def test_fallback_to_str(self):
        from datetime import date
        assert serialize_value(date(2026, 1, 1)) == "2026-01-01"


class TestBuildRawResult:
    def test_returns_none_for_no_results(self):
        assert _build_raw_result(None) is None

    def test_returns_none_for_no_columns(self):
        result = QueryResult(row_count=0)
        assert _build_raw_result(result) is None

    def test_returns_raw_data(self):
        result = _sample_result()
        raw = _build_raw_result(result)
        assert raw is not None
        assert raw["columns"] == ["name", "count", "total"]
        assert len(raw["rows"]) == 3
        assert raw["total_rows"] == 3

    def test_caps_at_500_rows(self):
        big = QueryResult(
            columns=["id"],
            rows=[[i] for i in range(700)],
            row_count=700,
        )
        raw = _build_raw_result(big)
        assert raw is not None
        assert len(raw["rows"]) == 500
        assert raw["total_rows"] == 700

    def test_serializes_special_values(self):
        result = QueryResult(
            columns=["data"],
            rows=[[b"\x00\x01"]],
            row_count=1,
        )
        raw = _build_raw_result(result)
        assert raw is not None
        assert raw["rows"][0][0] == "0001"


class TestNormalizeConfig:
    def test_x_y_aliases(self):
        cfg = _normalize_config({"x": "month", "y": "revenue"})
        assert cfg["labels_column"] == "month"
        assert cfg["data_columns"] == ["revenue"]

    def test_x_axis_y_axis_aliases(self):
        cfg = _normalize_config({"x_axis": "date", "y_axis": ["sales", "cost"]})
        assert cfg["labels_column"] == "date"
        assert cfg["data_columns"] == ["sales", "cost"]

    def test_categories_values_aliases(self):
        cfg = _normalize_config({"categories": "region", "values": "amount"})
        assert cfg["labels_column"] == "region"
        assert cfg["data_columns"] == ["amount"]

    def test_value_alias_for_pie(self):
        cfg = _normalize_config({"label": "category", "value": "total"})
        assert cfg["labels_column"] == "category"
        assert cfg["data_column"] == "total"

    def test_data_column_data_columns_sync(self):
        cfg = _normalize_config({"labels_column": "x", "data_column": "y"})
        assert cfg["data_columns"] == ["y"]

    def test_data_columns_string_to_list(self):
        cfg = _normalize_config({"data_columns": "revenue"})
        assert cfg["data_columns"] == ["revenue"]

    def test_group_by_aliases(self):
        cfg = _normalize_config({"split_by": "channel"})
        assert cfg["group_by"] == "channel"

    def test_dimension_metric_aliases(self):
        cfg = _normalize_config({"dimension": "month", "metric": "revenue"})
        assert cfg["labels_column"] == "month"
        assert cfg["data_column"] == "revenue"


class TestAutoDetectColumns:
    def test_numeric_and_categorical(self):
        result = QueryResult(
            columns=["name", "count", "total"],
            rows=[["Alice", 10, 500], ["Bob", 20, 800]],
            row_count=2,
        )
        labels, data = _auto_detect_columns(result, "bar")
        assert labels == "name"
        assert "count" in data
        assert "total" in data

    def test_line_chart_prefers_temporal(self):
        from datetime import date

        result = QueryResult(
            columns=["date_col", "value"],
            rows=[[date(2024, 1, 1), 100], [date(2024, 2, 1), 200]],
            row_count=2,
        )
        labels, data = _auto_detect_columns(result, "line")
        assert labels == "date_col"
        assert data == ["value"]

    def test_scatter_picks_two_numeric(self):
        result = QueryResult(
            columns=["age", "income", "label"],
            rows=[[25, 50000, "A"], [30, 60000, "B"]],
            row_count=2,
        )
        labels, data = _auto_detect_columns(result, "scatter")
        assert labels == "age"
        assert data == ["income"]


class TestResolveColIdx:
    def test_exact_match(self):
        result = QueryResult(columns=["Name", "Count"], rows=[], row_count=0)
        assert _resolve_col_idx("Count", result) == 1

    def test_case_insensitive(self):
        result = QueryResult(columns=["Name", "Count"], rows=[], row_count=0)
        assert _resolve_col_idx("count", result) == 1
        assert _resolve_col_idx("NAME", result) == 0

    def test_fallback(self):
        result = QueryResult(columns=["a", "b"], rows=[], row_count=0)
        assert _resolve_col_idx("missing", result, -1) == -1
        assert _resolve_col_idx("missing", result, 0) == 0


class TestSafeNumeric:
    def test_none(self):
        assert _safe_numeric(None) == 0

    def test_int(self):
        assert _safe_numeric(42) == 42.0

    def test_float(self):
        assert _safe_numeric(3.14) == 3.14

    def test_string_numeric(self):
        assert _safe_numeric("123.5") == 123.5

    def test_string_non_numeric(self):
        assert _safe_numeric("hello") == 0

    def test_decimal(self):
        from decimal import Decimal

        assert _safe_numeric(Decimal("99.9")) == 99.9


class TestChartNullHandling:
    def test_bar_chart_with_nulls(self):
        result = QueryResult(
            columns=["name", "count"],
            rows=[["Alice", 10], ["Bob", None], ["Carol", 30]],
            row_count=3,
        )
        config = {"labels_column": "name", "data_columns": ["count"]}
        chart = generate_bar_chart(result, config)
        assert chart["data"]["datasets"][0]["data"] == [10.0, 0.0, 30.0]

    def test_scatter_skips_nulls(self):
        result = QueryResult(
            columns=["x", "y"],
            rows=[[1, 10], [2, None], [3, 30]],
            row_count=3,
        )
        config = {"x_column": "x", "y_column": "y"}
        chart = generate_scatter(result, config)
        assert len(chart["data"]["datasets"][0]["data"]) == 2


class TestChartMissingColumns:
    def test_bar_chart_auto_detects_when_columns_missing(self):
        result = QueryResult(
            columns=["category", "amount"],
            rows=[["A", 100], ["B", 200]],
            row_count=2,
        )
        config = {"labels_column": "wrong_col", "data_columns": ["nonexistent"]}
        chart = generate_bar_chart(result, config)
        assert len(chart["data"]["labels"]) == 2
        assert len(chart["data"]["datasets"]) > 0

    def test_pie_chart_auto_detects_when_columns_missing(self):
        result = QueryResult(
            columns=["name", "value"],
            rows=[["X", 10], ["Y", 20]],
            row_count=2,
        )
        config = {"labels_column": "missing", "data_column": "also_missing"}
        chart = generate_pie_chart(result, config)
        assert len(chart["data"]["labels"]) == 2
        assert len(chart["data"]["datasets"][0]["data"]) == 2

    def test_empty_config_auto_detects(self):
        result = QueryResult(
            columns=["month", "revenue"],
            rows=[["Jan", 100], ["Feb", 200]],
            row_count=2,
        )
        chart = generate_bar_chart(result, {})
        assert chart["data"]["labels"] == ["Jan", "Feb"]
        assert len(chart["data"]["datasets"]) == 1


class TestRenderer:
    def test_table_render(self):
        result = render(_sample_result(), "table")
        assert result["type"] == "table"

    def test_chart_render(self):
        config = {"labels_column": "name", "data_columns": ["count"]}
        result = render(_sample_result(), "bar_chart", config)
        assert result["type"] == "chart"

    def test_text_render(self):
        r = QueryResult(columns=["val"], rows=[[100]], row_count=1)
        result = render(r, "text", summary="The total is 100")
        assert result["type"] == "text"

    def test_unknown_falls_back_to_table(self):
        result = render(_sample_result(), "unknown_type")
        assert result["type"] == "table"
