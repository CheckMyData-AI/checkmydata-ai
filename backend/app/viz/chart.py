import logging
from collections import OrderedDict
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from app.connectors.base import QueryResult
from app.viz.utils import serialize_value

logger = logging.getLogger(__name__)

_EMPTY_CHART: dict[str, Any] = {
    "data": {"labels": [], "datasets": []},
    "options": {},
}


def _normalize_config(config: dict) -> dict:
    """Map alternative key names produced by LLMs to the canonical keys."""
    out = dict(config)

    _LABELS_ALIASES = (
        "x", "label", "x_column", "x_axis", "labels", "categories",
        "category", "dimension", "category_column",
    )
    for alias in _LABELS_ALIASES:
        if alias in out and "labels_column" not in out:
            out["labels_column"] = out.pop(alias)
            break

    _DATA_COLS_ALIASES = (
        "y", "y_column", "y_axis", "values", "series", "metrics",
        "y_columns", "value_columns", "measure", "measures",
    )
    for alias in _DATA_COLS_ALIASES:
        if alias in out and "data_columns" not in out:
            val = out.pop(alias)
            out["data_columns"] = val if isinstance(val, list) else [val]
            break

    _DATA_COL_ALIASES = ("value", "metric", "data", "y_value")
    for alias in _DATA_COL_ALIASES:
        if alias in out and "data_column" not in out:
            out["data_column"] = out.pop(alias)
            break

    if "data_columns" in out and "data_column" not in out:
        dc = out["data_columns"]
        if isinstance(dc, list) and len(dc) == 1:
            out["data_column"] = dc[0]

    if "data_column" in out and "data_columns" not in out:
        out["data_columns"] = [out["data_column"]]

    dc = out.get("data_columns")
    if isinstance(dc, str):
        out["data_columns"] = [dc]

    _GROUP_ALIASES = ("group", "series_by", "color", "split_by", "segment")
    for alias in _GROUP_ALIASES:
        if alias in out and "group_by" not in out:
            out["group_by"] = out.pop(alias)
            break

    return out


def _is_numeric(val: Any) -> bool:
    if val is None:
        return False
    if isinstance(val, (int, float, Decimal)):
        return True
    if isinstance(val, str):
        try:
            float(val)
            return True
        except (ValueError, TypeError):
            return False
    return False


def _is_temporal(val: Any) -> bool:
    return isinstance(val, (date, datetime, time))


def _detect_column_types(result: QueryResult) -> dict[str, str]:
    """Sample rows to classify each column as 'numeric', 'temporal', or 'categorical'."""
    types: dict[str, str] = {}
    sample_rows = result.rows[:20]

    for col_idx, col_name in enumerate(result.columns):
        numeric_count = 0
        temporal_count = 0
        total_non_null = 0

        for row in sample_rows:
            val = row[col_idx]
            if val is None:
                continue
            total_non_null += 1
            if _is_numeric(val):
                numeric_count += 1
            elif _is_temporal(val):
                temporal_count += 1

        if total_non_null == 0:
            types[col_name] = "categorical"
        elif numeric_count / total_non_null >= 0.8:
            types[col_name] = "numeric"
        elif temporal_count / total_non_null >= 0.5:
            types[col_name] = "temporal"
        else:
            types[col_name] = "categorical"

    return types


def _auto_detect_columns(
    result: QueryResult,
    chart_type: str,
) -> tuple[str, list[str]]:
    """Heuristic column selection when LLM config is missing or wrong.

    Returns (labels_column, data_columns).
    """
    col_types = _detect_column_types(result)
    cols = result.columns

    temporal_cols = [c for c in cols if col_types.get(c) == "temporal"]
    categorical_cols = [c for c in cols if col_types.get(c) == "categorical"]
    numeric_cols = [c for c in cols if col_types.get(c) == "numeric"]

    if chart_type in ("line", "line_chart"):
        labels = temporal_cols[0] if temporal_cols else (categorical_cols[0] if categorical_cols else cols[0])
    elif chart_type in ("scatter",):
        if len(numeric_cols) >= 2:
            return numeric_cols[0], [numeric_cols[1]]
        return cols[0], [cols[1]] if len(cols) > 1 else []
    else:
        labels = categorical_cols[0] if categorical_cols else (temporal_cols[0] if temporal_cols else cols[0])

    data = numeric_cols if numeric_cols else [c for c in cols if c != labels]
    if labels in data:
        data = [c for c in data if c != labels]
    if not data and len(cols) > 1:
        data = [c for c in cols if c != labels][:1]

    return labels, data


def _safe_numeric(val: Any, default: float = 0) -> float:
    """Convert a value to float, falling back to *default* for non-numeric."""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, str):
        try:
            return float(val)
        except (ValueError, TypeError):
            return default
    return default


def _resolve_col_idx(col_name: str, result: QueryResult, fallback_idx: int = 0) -> int:
    """Find column index by exact match, then case-insensitive match, then fallback."""
    if col_name in result.columns:
        return result.columns.index(col_name)
    lower = col_name.lower()
    for i, c in enumerate(result.columns):
        if c.lower() == lower:
            return i
    return min(fallback_idx, len(result.columns) - 1)


def _pivot_grouped(
    result: QueryResult,
    labels_col: str,
    data_col: str,
    group_col: str,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Pivot rows into multi-series datasets grouped by *group_col*."""
    labels_idx = _resolve_col_idx(labels_col, result, 0)
    data_idx = _resolve_col_idx(data_col, result, 1)
    group_idx = _resolve_col_idx(group_col, result, 2)

    label_order: OrderedDict[str, int] = OrderedDict()
    groups: OrderedDict[str, dict[str, Any]] = OrderedDict()

    for row in result.rows:
        lbl = str(row[labels_idx])
        grp = str(row[group_idx])
        val = _safe_numeric(serialize_value(row[data_idx]))
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

    labels_col = cfg.get("labels_column")
    data_cols = cfg.get("data_columns")

    auto_labels, auto_data = _auto_detect_columns(result, chart_type)
    if not labels_col or _resolve_col_idx(labels_col, result, -1) == -1:
        if labels_col:
            logger.debug("Configured labels_column '%s' not found, using auto-detected '%s'", labels_col, auto_labels)
        labels_col = auto_labels
    if not data_cols:
        data_cols = auto_data

    valid_data_cols = []
    for col in data_cols:
        idx = _resolve_col_idx(col, result, -1)
        if idx >= 0:
            valid_data_cols.append(result.columns[idx])
        else:
            logger.debug("Data column '%s' not found in results, skipping", col)
    if not valid_data_cols:
        logger.debug("No valid data columns found, using auto-detected columns")
        valid_data_cols = auto_data
    data_cols = valid_data_cols

    if group_col:
        group_idx = _resolve_col_idx(group_col, result, -1)
        if group_idx >= 0 and data_cols:
            data_col = data_cols[0] if isinstance(data_cols, list) else data_cols
            return _pivot_grouped(result, labels_col, data_col, result.columns[group_idx])
        elif group_col:
            logger.debug("group_by column '%s' not found, ignoring pivot", group_col)

    labels_idx = _resolve_col_idx(labels_col, result, 0)
    labels = [str(row[labels_idx]) for row in result.rows]

    datasets = []
    for col in data_cols:
        col_idx = _resolve_col_idx(col, result, -1)
        if col_idx < 0:
            continue
        raw_data = [serialize_value(row[col_idx]) for row in result.rows]
        numeric_data = [_safe_numeric(v) for v in raw_data]
        ds: dict[str, Any] = {
            "label": col,
            "data": numeric_data,
        }
        if chart_type == "line":
            ds["fill"] = False
        datasets.append(ds)

    if not datasets and len(result.columns) > 1:
        logger.warning("All configured data columns failed, falling back to auto-detection")
        _, fallback_cols = _auto_detect_columns(result, chart_type)
        for col in fallback_cols:
            col_idx = _resolve_col_idx(col, result, -1)
            if col_idx < 0:
                continue
            numeric_data = [_safe_numeric(serialize_value(row[col_idx])) for row in result.rows]
            ds = {"label": col, "data": numeric_data}
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
    auto_labels, auto_data = _auto_detect_columns(result, "pie")

    labels_col = cfg.get("labels_column", auto_labels)
    data_col = cfg.get("data_column")
    if not data_col:
        data_cols = cfg.get("data_columns")
        data_col = data_cols[0] if data_cols and isinstance(data_cols, list) else (auto_data[0] if auto_data else result.columns[1])

    labels_idx = _resolve_col_idx(labels_col, result, 0)
    data_idx = _resolve_col_idx(data_col, result, 1)

    labels = [str(row[labels_idx]) for row in result.rows]
    data = [_safe_numeric(serialize_value(row[data_idx])) for row in result.rows]

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
    auto_labels, auto_data = _auto_detect_columns(result, "scatter")

    x_col = cfg.get("x_column", cfg.get("labels_column", auto_labels))
    y_col = cfg.get("y_column")
    if not y_col:
        if "data_columns" in cfg and cfg["data_columns"]:
            y_col = cfg["data_columns"][0]
        else:
            y_col = auto_data[0] if auto_data else result.columns[1]

    x_idx = _resolve_col_idx(x_col, result, 0)
    y_idx = _resolve_col_idx(y_col, result, 1)

    points = []
    for row in result.rows:
        x_val = serialize_value(row[x_idx])
        y_val = serialize_value(row[y_idx])
        if x_val is None or y_val is None:
            continue
        points.append({"x": _safe_numeric(x_val), "y": _safe_numeric(y_val)})

    x_name = result.columns[x_idx]
    y_name = result.columns[y_idx]

    return {
        "type": "scatter",
        "data": {
            "datasets": [{"label": f"{x_name} vs {y_name}", "data": points}],
        },
        "options": config.get("options", {}),
    }
