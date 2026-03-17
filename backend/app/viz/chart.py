from typing import Any

from app.connectors.base import QueryResult

_EMPTY_CHART: dict[str, Any] = {
    "data": {"labels": [], "datasets": []},
    "options": {},
}


def generate_bar_chart(result: QueryResult, config: dict) -> dict[str, Any]:
    if not result.columns:
        return {"type": "bar", **_EMPTY_CHART}

    labels_col = config.get("labels_column", result.columns[0])
    data_cols = config.get("data_columns", result.columns[1:] if len(result.columns) > 1 else [])

    labels_idx = result.columns.index(labels_col) if labels_col in result.columns else 0
    labels = [str(row[labels_idx]) for row in result.rows]

    datasets = []
    for col in data_cols:
        if col in result.columns:
            col_idx = result.columns.index(col)
            datasets.append(
                {
                    "label": col,
                    "data": [row[col_idx] for row in result.rows],
                }
            )

    return {
        "type": "bar",
        "data": {"labels": labels, "datasets": datasets},
        "options": config.get("options", {}),
    }


def generate_line_chart(result: QueryResult, config: dict) -> dict[str, Any]:
    if not result.columns:
        return {"type": "line", **_EMPTY_CHART}

    labels_col = config.get("labels_column", result.columns[0])
    data_cols = config.get("data_columns", result.columns[1:] if len(result.columns) > 1 else [])

    labels_idx = result.columns.index(labels_col) if labels_col in result.columns else 0
    labels = [str(row[labels_idx]) for row in result.rows]

    datasets = []
    for col in data_cols:
        if col in result.columns:
            col_idx = result.columns.index(col)
            datasets.append(
                {
                    "label": col,
                    "data": [row[col_idx] for row in result.rows],
                    "fill": False,
                }
            )

    return {
        "type": "line",
        "data": {"labels": labels, "datasets": datasets},
        "options": config.get("options", {}),
    }


def generate_pie_chart(result: QueryResult, config: dict) -> dict[str, Any]:
    if not result.columns or len(result.columns) < 2:
        return {"type": "pie", **_EMPTY_CHART}

    labels_col = config.get("labels_column", result.columns[0])
    data_col = config.get("data_column", result.columns[1])

    labels_idx = result.columns.index(labels_col) if labels_col in result.columns else 0
    data_idx = result.columns.index(data_col) if data_col in result.columns else 1

    labels = [str(row[labels_idx]) for row in result.rows]
    data = [row[data_idx] for row in result.rows]

    return {
        "type": "pie",
        "data": {
            "labels": labels,
            "datasets": [{"data": data}],
        },
        "options": config.get("options", {}),
    }


def generate_scatter(result: QueryResult, config: dict) -> dict[str, Any]:
    if not result.columns or len(result.columns) < 2:
        return {"type": "scatter", **_EMPTY_CHART}

    x_col = config.get("x_column", result.columns[0])
    y_col = config.get("y_column", result.columns[1])

    x_idx = result.columns.index(x_col) if x_col in result.columns else 0
    y_idx = result.columns.index(y_col) if y_col in result.columns else 1

    points = [{"x": row[x_idx], "y": row[y_idx]} for row in result.rows]

    return {
        "type": "scatter",
        "data": {
            "datasets": [{"label": f"{x_col} vs {y_col}", "data": points}],
        },
        "options": config.get("options", {}),
    }
