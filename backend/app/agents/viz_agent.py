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
from app.agents.prompts.viz_prompt import VIZ_SYSTEM_PROMPT
from app.agents.tools.viz_tools import RECOMMEND_VISUALIZATION_TOOL
from app.config import settings
from app.connectors.base import QueryResult
from app.llm.base import Message

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

        if preferred_viz and preferred_viz in (
            "table",
            "bar_chart",
            "line_chart",
            "pie_chart",
            "scatter",
            "text",
            "number",
        ):
            if preferred_viz == "pie_chart" and len(rows) > settings.max_pie_categories:
                preferred_viz = "bar_chart"
            return VizResult(viz_type=preferred_viz)

        return None

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

        messages = [
            Message(role="system", content=VIZ_SYSTEM_PROMPT),
            Message(
                role="user",
                content=f"Question: {question}\nQuery: {query}\nResults:\n{results_summary}",
            ),
        ]

        llm_resp = await context.llm_router.complete(
            messages=messages,
            tools=[RECOMMEND_VISUALIZATION_TOOL],
            preferred_provider=context.preferred_provider,
            model=context.model,
        )

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

                    viz_type = self._post_validate(viz_type, results)

                    return VizResult(
                        viz_type=viz_type,
                        viz_config=config if isinstance(config, dict) else {},
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

    def _post_validate(self, viz_type: str, results: QueryResult) -> str:
        if viz_type == "pie_chart" and len(results.rows) > settings.max_pie_categories:
            return "bar_chart"
        if viz_type in ("line_chart", "bar_chart", "scatter") and len(results.columns) < 2:
            return "table"
        return viz_type

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
