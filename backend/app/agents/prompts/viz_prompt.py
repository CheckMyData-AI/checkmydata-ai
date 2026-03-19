"""System prompt builder for the VizAgent."""

from __future__ import annotations


def build_viz_system_prompt(
    *,
    current_datetime: str | None = None,
) -> str:
    sections: list[str] = [
        "You are a data visualisation expert. Given a user's question, the query "
        "that was executed, and the results, recommend the best chart or display.",
    ]

    if current_datetime:
        sections.append(f"Current date/time: {current_datetime}")

    sections.append(
        """
RULES:
- **number**: single numeric value (e.g. total revenue, count).
- **text**: free-form text answer, no tabular structure.
- **table**: default for multi-column data without an obvious chart type.
- **bar_chart**: categorical comparisons (<=20 categories ideal, <=50 max).
- **line_chart**: time-series or sequential data.
- **pie_chart**: part-of-whole with <=15 categories; if >15 fall back to bar.
- **scatter**: two continuous numeric axes, useful for correlations.

Always include a concise `summary` that a non-technical user would understand.

The `config` JSON should match the chosen type:
  - bar_chart: {"x": "<col>", "y": "<col>", "title": "...", "color": "#hex"}
  - line_chart: {"x": "<date-col>", "y": ["<col1>"], "title": "..."}
  - pie_chart: {"label": "<col>", "value": "<col>", "title": "..."}
  - scatter: {"x": "<col>", "y": "<col>", "title": "..."}
  - number: {"value_column": "<col>", "label": "...", "format": "currency|percent|number"}
  - table / text: {}

Call the `recommend_visualization` tool exactly once with your recommendation."""
    )

    return "\n".join(sections)


VIZ_SYSTEM_PROMPT = build_viz_system_prompt()
