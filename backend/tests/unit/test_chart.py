"""DATA-09: charts render NULL/missing as a gap (None), not 0."""

from app.connectors.base import QueryResult
from app.viz.chart import generate_bar_chart


def test_null_value_renders_as_gap_not_zero():
    result = QueryResult(
        columns=["region", "sales"],
        rows=[["us", 100], ["eu", None]],
        row_count=2,
    )
    chart = generate_bar_chart(result, {"labels_column": "region", "data_columns": ["sales"]})
    data = chart["data"]["datasets"][0]["data"]
    assert data[0] == 100.0
    assert data[1] is None  # NULL must be a gap, not 0


def test_missing_pivot_cell_is_gap_not_zero():
    from app.viz.chart import generate_line_chart

    result = QueryResult(
        columns=["month", "sales", "region"],
        rows=[["jan", 10, "us"], ["feb", 20, "eu"]],  # us has no feb, eu has no jan
        row_count=2,
    )
    chart = generate_line_chart(
        result,
        {"labels_column": "month", "data_columns": ["sales"], "group_by": "region"},
    )
    all_points = [p for ds in chart["data"]["datasets"] for p in ds["data"]]
    assert None in all_points  # the absent (region, month) cell is a gap


def test_real_zero_stays_zero():
    """A genuine numeric 0 must not be converted to None."""
    result = QueryResult(
        columns=["region", "sales"],
        rows=[["us", 100], ["eu", 0]],
        row_count=2,
    )
    chart = generate_bar_chart(result, {"labels_column": "region", "data_columns": ["sales"]})
    data = chart["data"]["datasets"][0]["data"]
    assert data[0] == 100.0
    assert data[1] == 0.0  # real zero must stay 0


def test_unparseable_string_renders_as_gap():
    """Unparseable string values should also become None (gap), not 0."""
    result = QueryResult(
        columns=["region", "sales"],
        rows=[["us", 100], ["eu", "N/A"]],
        row_count=2,
    )
    chart = generate_bar_chart(result, {"labels_column": "region", "data_columns": ["sales"]})
    data = chart["data"]["datasets"][0]["data"]
    assert data[0] == 100.0
    assert data[1] is None  # unparseable → gap
