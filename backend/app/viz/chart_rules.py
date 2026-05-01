"""Chart selection and post-validation rules (T15).

Single source of truth for the handful of safety-net rules we still want to
apply *after* the LLM picks a visualization. The LLM is always the primary
decision maker; these rules exist only to catch visually broken outputs
(too many slices in a pie chart, a line chart with a single column, etc.).

Keeping the rules in one module stops ``VizAgent._post_validate`` and
``AgentResultValidator.validate_viz_result`` from drifting apart.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.config import settings

VALID_VIZ_TYPES: frozenset[str] = frozenset(
    {"table", "bar_chart", "line_chart", "pie_chart", "scatter", "text", "number"}
)


@dataclass
class ChartRuleOutcome:
    """Structured outcome from applying chart rules.

    ``adjusted_viz_type`` is the safest chart type given the shape of the
    data. ``warnings`` contains any human-readable reasons we deviated from
    the requested type.
    """

    adjusted_viz_type: str = "table"
    warnings: list[str] = field(default_factory=list)
    invalid_type: bool = False


def apply_chart_rules(
    viz_type: str,
    *,
    row_count: int = 0,
    column_count: int = 0,
) -> ChartRuleOutcome:
    """Apply the consolidated chart-safety rules.

    Rules (minimal by design — everything else is the LLM's call):

    * ``pie_chart`` with ``row_count > settings.max_pie_categories`` →
      ``bar_chart`` (too many slices to be readable).
    * ``line_chart`` / ``bar_chart`` / ``scatter`` with ``column_count < 2``
      → ``table`` (axes need at least two columns).
    * Unknown ``viz_type`` → flag ``invalid_type`` and fall back to
      ``table``.
    """
    outcome = ChartRuleOutcome(adjusted_viz_type=viz_type)

    if viz_type not in VALID_VIZ_TYPES:
        outcome.invalid_type = True
        outcome.adjusted_viz_type = "table"
        outcome.warnings.append(f"Invalid viz_type '{viz_type}'")
        return outcome

    if viz_type == "pie_chart" and row_count > settings.max_pie_categories:
        outcome.adjusted_viz_type = "bar_chart"
        outcome.warnings.append(
            f"Pie chart with {row_count} slices — falling back to bar_chart"
        )
        return outcome

    if viz_type in ("line_chart", "bar_chart", "scatter") and column_count < 2:
        outcome.adjusted_viz_type = "table"
        outcome.warnings.append(
            f"{viz_type} needs at least 2 columns — falling back to table"
        )
        return outcome

    return outcome
