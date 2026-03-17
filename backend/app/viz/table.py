from typing import Any

from app.connectors.base import QueryResult
from app.viz.utils import serialize_value


def format_table(result: QueryResult, config: dict | None = None) -> dict[str, Any]:
    config = config or {}
    page = max(1, config.get("page", 1))
    page_size = max(1, config.get("page_size", 50))

    start = (page - 1) * page_size
    end = start + page_size
    page_rows = result.rows[start:end]

    serialized_rows = []
    for row in page_rows:
        serialized_rows.append({col: serialize_value(val) for col, val in zip(result.columns, row)})

    return {
        "columns": result.columns,
        "rows": serialized_rows,
        "total_rows": result.row_count,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (result.row_count + page_size - 1) // page_size),
        "execution_time_ms": result.execution_time_ms,
    }
