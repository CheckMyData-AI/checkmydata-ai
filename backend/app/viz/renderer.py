from typing import Any

from app.connectors.base import QueryResult
from app.viz.chart import (
    generate_bar_chart,
    generate_line_chart,
    generate_pie_chart,
    generate_scatter,
)
from app.viz.table import format_table
from app.viz.text import format_text

VIZ_RENDERERS: dict[str, Any] = {
    "bar_chart": generate_bar_chart,
    "line_chart": generate_line_chart,
    "pie_chart": generate_pie_chart,
    "scatter": generate_scatter,
}


def render(
    result: QueryResult,
    viz_type: str,
    config: dict | None = None,
    summary: str = "",
) -> dict:
    """Dispatch to the appropriate visualization renderer.

    Returns a dict with the visualization data ready for the frontend.
    """
    config = config or {}

    if viz_type == "table":
        return {"type": "table", "data": format_table(result, config)}

    if viz_type in ("text", "number"):
        return {"type": viz_type, "data": format_text(result, summary)}

    renderer = VIZ_RENDERERS.get(viz_type)
    if renderer:
        return {"type": "chart", "data": renderer(result, config)}

    return {"type": "table", "data": format_table(result, config)}
