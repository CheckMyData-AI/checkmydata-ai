"""VizAgent — visualization specialist.

Decides the best way to display query results.  Uses fast rule-based
heuristics for obvious cases (single value, empty results, simple table)
and falls back to an LLM call for ambiguous cases.
"""

from __future__ import annotations

import json as _json
import logging
from dataclasses import dataclass, field
from typing import Any

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.agents.prompts import get_current_datetime_str
from app.agents.prompts.viz_prompt import build_viz_system_prompt
from app.agents.tools.viz_tools import RECOMMEND_VISUALIZATION_TOOL
from app.config import settings
from app.connectors.base import QueryResult
from app.llm.base import Message
from app.viz.chart import _auto_detect_columns, _resolve_col_idx

logger = logging.getLogger(__name__)


@dataclass
class VizResult(AgentResult):
    """Typed result from the viz agent."""

    viz_type: str = "table"
    viz_config: dict[str, Any] = field(default_factory=dict)
    summary: str = ""


class VizAgent(BaseAgent):
    """Visualization specialist agent."""

    @property
    def name(self) -> str:
        return "viz"

    async def run(  # type: ignore[override]
        self,
        context: AgentContext,
        *,
        results: QueryResult,
        question: str = "",
        query: str = "",
        preferred_viz: str | None = None,
    ) -> VizResult:
        question = question or context.user_question

        rule_based = self._rule_based_pick(results, preferred_viz)
        if rule_based is not None:
            return rule_based

        return await self._llm_pick(context, results, question, query)

    # ------------------------------------------------------------------
    # Rule-based fast path (no LLM call)
    # ------------------------------------------------------------------

    def _rule_based_pick(
        self,
        results: QueryResult,
        preferred_viz: str | None,
    ) -> VizResult | None:
        if results.error or not results.rows:
            return VizResult(viz_type="text", summary="No data to display.")

        rows = results.rows
        cols = results.columns

        if len(cols) == 1 and len(rows) == 1:
            val = rows[0][0]
            if isinstance(val, (int, float)):
                return VizResult(
                    viz_type="number",
                    viz_config={"value_column": cols[0], "label": cols[0]},
                    summary=f"{cols[0]}: {val}",
                )
            return VizResult(
                viz_type="text",
                summary=str(val),
            )

        from app.agents.validation import AgentResultValidator

        if preferred_viz and preferred_viz in AgentResultValidator.VALID_VIZ_TYPES:
            if preferred_viz == "pie_chart" and len(rows) > settings.max_pie_categories:
                preferred_viz = "bar_chart"
            config = self._generate_config(results, preferred_viz)
            return VizResult(viz_type=preferred_viz, viz_config=config)

        if len(cols) == 2 and len(rows) == 1:
            return VizResult(
                viz_type="text",
                summary=" | ".join(f"{cols[i]}: {rows[0][i]}" for i in range(len(cols))),
            )

        if len(cols) >= 2:
            has_numeric = any(isinstance(rows[0][i], (int, float)) for i in range(len(cols)))
            labels_col, data_cols = _auto_detect_columns(results, "bar_chart")

            if has_numeric and data_cols:
                if len(rows) <= settings.max_pie_categories and len(data_cols) == 1:
                    config = {
                        "labels_column": labels_col,
                        "data_column": data_cols[0],
                    }
                    return VizResult(viz_type="pie_chart", viz_config=config)

                if len(rows) > 50 and len(data_cols) >= 1:
                    config = {"labels_column": labels_col, "data_columns": data_cols}
                    return VizResult(viz_type="line_chart", viz_config=config)

                if len(rows) > 1 and len(data_cols) >= 1:
                    config = {"labels_column": labels_col, "data_columns": data_cols}
                    return VizResult(viz_type="bar_chart", viz_config=config)

        if len(cols) == 1:
            return VizResult(viz_type="table")

        return None

    @staticmethod
    def _generate_config(results: QueryResult, viz_type: str) -> dict[str, Any]:
        """Auto-generate viz_config based on column type detection."""
        if viz_type in ("table", "text", "number"):
            return {}
        labels_col, data_cols = _auto_detect_columns(results, viz_type)
        if viz_type in ("bar_chart", "line_chart"):
            return {"labels_column": labels_col, "data_columns": data_cols}
        if viz_type == "pie_chart":
            fallback = results.columns[min(1, len(results.columns) - 1)]
            return {
                "labels_column": labels_col,
                "data_column": data_cols[0] if data_cols else fallback,
            }
        if viz_type == "scatter":
            fallback = results.columns[min(1, len(results.columns) - 1)]
            return {
                "x_column": labels_col,
                "y_column": data_cols[0] if data_cols else fallback,
            }
        return {}

    # ------------------------------------------------------------------
    # LLM-based pick
    # ------------------------------------------------------------------

    async def _llm_pick(
        self,
        context: AgentContext,
        results: QueryResult,
        question: str,
        query: str,
    ) -> VizResult:
        results_summary = self._summarize_results(results)

        system_prompt = build_viz_system_prompt(
            current_datetime=get_current_datetime_str(),
        )
        messages = [
            Message(role="system", content=system_prompt),
            Message(
                role="user",
                content=f"Question: {question}\nQuery: {query}\nResults:\n{results_summary}",
            ),
        ]

        try:
            llm_resp = await context.llm_router.complete(
                messages=messages,
                tools=[RECOMMEND_VISUALIZATION_TOOL],
                preferred_provider=context.preferred_provider,
                model=context.model,
            )
        except Exception:
            logger.exception("VizAgent LLM call failed, falling back to table")
            return VizResult(viz_type="table", summary="Visualization selection failed")

        total_usage = dict(llm_resp.usage) if llm_resp.usage else {}

        if llm_resp.tool_calls:
            for tc in llm_resp.tool_calls:
                if tc.name == "recommend_visualization":
                    config = tc.arguments.get("config", "{}")
                    if isinstance(config, str):
                        try:
                            config = _json.loads(config)
                        except _json.JSONDecodeError:
                            config = {}
                    viz_type = tc.arguments.get("viz_type", "table")
                    summary = tc.arguments.get("summary", llm_resp.content or "")

                    valid_cfg = config if isinstance(config, dict) else None
                    viz_type = self._post_validate(viz_type, results, valid_cfg)
                    config = config if isinstance(config, dict) else {}
                    config = self._validate_and_fix_config(config, viz_type, results)

                    return VizResult(
                        viz_type=viz_type,
                        viz_config=config,
                        summary=summary,
                        token_usage=total_usage,
                    )

        return VizResult(
            viz_type="table",
            summary=llm_resp.content or "",
            token_usage=total_usage,
        )

    # ------------------------------------------------------------------
    # Post-validation
    # ------------------------------------------------------------------

    def _post_validate(
        self,
        viz_type: str,
        results: QueryResult,
        viz_config: dict | None = None,  # noqa: ARG002
    ) -> str:
        if viz_type == "pie_chart" and len(results.rows) > settings.max_pie_categories:
            return "bar_chart"
        if viz_type in ("line_chart", "bar_chart", "scatter") and len(results.columns) < 2:
            return "table"
        return viz_type

    @staticmethod
    def _validate_and_fix_config(
        viz_config: dict,
        viz_type: str,
        results: QueryResult,
    ) -> dict:
        """Verify column references exist in results; regenerate if broken."""
        if viz_type in ("table", "text", "number") or not viz_config:
            return viz_config

        col_keys = ("labels_column", "data_column", "x_column", "y_column", "group_by")
        list_keys = ("data_columns",)

        has_invalid = False
        for key in col_keys:
            val = viz_config.get(key)
            if val and _resolve_col_idx(val, results, -1) == -1:
                logger.debug("viz_config key '%s' references missing column '%s'", key, val)
                has_invalid = True
                break

        if not has_invalid:
            for key in list_keys:
                vals = viz_config.get(key, [])
                if isinstance(vals, list):
                    for v in vals:
                        if v and _resolve_col_idx(v, results, -1) == -1:
                            logger.debug(
                                "viz_config key '%s' references missing column '%s'",
                                key,
                                v,
                            )
                            has_invalid = True
                            break

        if has_invalid:
            labels_col, data_cols = _auto_detect_columns(results, viz_type)
            if viz_type in ("bar_chart", "line_chart"):
                return {"labels_column": labels_col, "data_columns": data_cols}
            if viz_type == "pie_chart":
                fb = results.columns[min(1, len(results.columns) - 1)]
                return {
                    "labels_column": labels_col,
                    "data_column": data_cols[0] if data_cols else fb,
                }
            if viz_type == "scatter":
                fb = results.columns[min(1, len(results.columns) - 1)]
                return {
                    "x_column": labels_col,
                    "y_column": data_cols[0] if data_cols else fb,
                }

        return viz_config

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _summarize_results(results: QueryResult, max_rows: int = 20) -> str:
        if not results.rows:
            return "No rows returned."
        lines = [
            f"Columns ({len(results.columns)}): {', '.join(results.columns)}",
            f"Total rows: {results.row_count}",
        ]
        for row in results.rows[:max_rows]:
            lines.append(" | ".join(str(v) for v in row))
        if results.row_count > max_rows:
            lines.append(f"... and {results.row_count - max_rows} more rows")
        return "\n".join(lines)
