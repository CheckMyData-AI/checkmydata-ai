from collections import OrderedDict
from typing import Any

from app.connectors.base import QueryResult
from app.viz.utils import serialize_value

_EMPTY_CHART: dict[str, Any] = {
    "data": {"labels": [], "datasets": []},
    "options": {},
}


def _normalize_config(config: dict) -> dict:
    """Map alternative key names produced by LLMs to the canonical keys."""
    out = dict(config)
    if "x" in out and "labels_column" not in out:
        out["labels_column"] = out.pop("x")
    if "y" in out and "data_columns" not in out:
        val = out.pop("y")
        out["data_columns"] = val if isinstance(val, list) else [val]
    if "label" in out and "labels_column" not in out:
        out["labels_column"] = out.pop("label")
    if "value" in out and "data_column" not in out:
        out["data_column"] = out.pop("value")
    if "x_column" in out and "labels_column" not in out:
        out["labels_column"] = out.pop("x_column")
    if "y_column" in out and "data_columns" not in out:
        val = out.pop("y_column")
        out["data_columns"] = val if isinstance(val, list) else [val]
    dc = out.get("data_columns")
    if isinstance(dc, str):
        out["data_columns"] = [dc]
    return out


def _pivot_grouped(
    result: QueryResult,
    labels_col: str,
    data_col: str,
    group_col: str,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Pivot rows into multi-series datasets grouped by *group_col*.

    Returns (labels, datasets) where each dataset corresponds to one
    unique value in *group_col*.
    """
    labels_idx = result.columns.index(labels_col) if labels_col in result.columns else 0
    data_idx = result.columns.index(data_col) if data_col in result.columns else 1
    group_idx = result.columns.index(group_col) if group_col in result.columns else 2

    label_order: OrderedDict[str, int] = OrderedDict()
    groups: OrderedDict[str, dict[str, Any]] = OrderedDict()

    for row in result.rows:
        lbl = str(row[labels_idx])
        grp = str(row[group_idx])
        val = serialize_value(row[data_idx])
        if lbl not in label_order:
            label_order[lbl] = len(label_order)
        if grp not in groups:
            groups[grp] = {}
        groups[grp][lbl] = val

    labels = list(label_order.keys())
    datasets = []
    for grp_name, mapping in groups.items():
        datasets.append(
            {
                "label": grp_name,
                "data": [mapping.get(lbl, 0) for lbl in labels],
                "fill": False,
            }
        )
    return labels, datasets


def _build_series(
    result: QueryResult,
    config: dict,
    chart_type: str,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Build labels and datasets, handling group_by pivot when present."""
    cfg = _normalize_config(config)
    group_col = cfg.get("group_by")

    labels_col = cfg.get("labels_column", result.columns[0])
    data_cols = cfg.get("data_columns", result.columns[1:] if len(result.columns) > 1 else [])

    if group_col and group_col in result.columns and data_cols:
        data_col = data_cols[0] if isinstance(data_cols, list) else data_cols
        return _pivot_grouped(result, labels_col, data_col, group_col)

    labels_idx = result.columns.index(labels_col) if labels_col in result.columns else 0
    labels = [str(row[labels_idx]) for row in result.rows]

    datasets = []
    for col in data_cols:
        if col in result.columns:
            col_idx = result.columns.index(col)
            ds: dict[str, Any] = {
                "label": col,
                "data": [serialize_value(row[col_idx]) for row in result.rows],
            }
            if chart_type == "line":
                ds["fill"] = False
            datasets.append(ds)
    return labels, datasets


def generate_bar_chart(result: QueryResult, config: dict) -> dict[str, Any]:
    if not result.columns:
        return {"type": "bar", **_EMPTY_CHART}

    labels, datasets = _build_series(result, config, "bar")

    return {
        "type": "bar",
        "data": {"labels": labels, "datasets": datasets},
        "options": config.get("options", {}),
    }


def generate_line_chart(result: QueryResult, config: dict) -> dict[str, Any]:
    if not result.columns:
        return {"type": "line", **_EMPTY_CHART}

    labels, datasets = _build_series(result, config, "line")

    return {
        "type": "line",
        "data": {"labels": labels, "datasets": datasets},
        "options": config.get("options", {}),
    }


def generate_pie_chart(result: QueryResult, config: dict) -> dict[str, Any]:
    if not result.columns or len(result.columns) < 2:
        return {"type": "pie", **_EMPTY_CHART}

    cfg = _normalize_config(config)
    labels_col = cfg.get("labels_column", result.columns[0])
    data_col = cfg.get("data_column", result.columns[1])

    labels_idx = result.columns.index(labels_col) if labels_col in result.columns else 0
    data_idx = result.columns.index(data_col) if data_col in result.columns else 1

    labels = [str(row[labels_idx]) for row in result.rows]
    data = [serialize_value(row[data_idx]) for row in result.rows]

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

    cfg = _normalize_config(config)
    x_col = cfg.get("x_column", cfg.get("labels_column", result.columns[0]))
    y_col = cfg.get("y_column", result.columns[1])
    if "data_columns" in cfg and cfg["data_columns"]:
        y_col = cfg["data_columns"][0]

    x_idx = result.columns.index(x_col) if x_col in result.columns else 0
    y_idx = result.columns.index(y_col) if y_col in result.columns else 1

    points = [
        {"x": serialize_value(row[x_idx]), "y": serialize_value(row[y_idx])} for row in result.rows
    ]

    return {
        "type": "scatter",
        "data": {
            "datasets": [{"label": f"{x_col} vs {y_col}", "data": points}],
        },
        "options": config.get("options", {}),
    }
