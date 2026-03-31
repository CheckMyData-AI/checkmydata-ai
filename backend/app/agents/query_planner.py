"""QueryPlanner — decomposes complex queries into an ExecutionPlan.

Two responsibilities:
1. **Complexity detection** — fast heuristic, no LLM call.
2. **Planning** — a single LLM call that produces an ``ExecutionPlan``.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from app.agents.prompts.planner_prompt import (
    PLANNER_SYSTEM_PROMPT,
    build_planner_user_prompt,
)
from app.agents.stage_context import ExecutionPlan, PlanStage, StageValidation
from app.llm.base import Message
from app.llm.router import LLMRouter

logger = logging.getLogger(__name__)

_COMPLEXITY_KEYWORDS = [
    "summary table",
    "pivot",
    "breakdown",
    "cross-reference",
    "compare",
    "for each",
    "match",
    "correlate",
    "then",
    "step 1",
    "step 2",
    "first find",
    "after that",
]


# ------------------------------------------------------------------
# Complexity detection
# ------------------------------------------------------------------


def detect_complexity(question: str) -> bool:
    """Fast heuristic check — no LLM call."""
    q_lower = question.lower()
    indicators = [
        len(question) > 300,
        any(kw in q_lower for kw in _COMPLEXITY_KEYWORDS),
        question.count("?") > 1,
        question.count(",") > 3 and any(v in q_lower for v in ["and", "also", "plus"]),
    ]
    return sum(indicators) >= 2


async def detect_complexity_adaptive(
    question: str,
    llm_router: LLMRouter,
    preferred_provider: str | None = None,
    model: str | None = None,
) -> bool:
    """Heuristic first, LLM fallback for borderline scores."""
    q_lower = question.lower()
    indicators = [
        len(question) > 300,
        any(kw in q_lower for kw in _COMPLEXITY_KEYWORDS),
        question.count("?") > 1,
        question.count(",") > 3 and any(v in q_lower for v in ["and", "also", "plus"]),
    ]
    score = sum(indicators)
    if score >= 2:
        return True
    if score == 0:
        return False
    try:
        resp = await llm_router.complete(
            messages=[
                Message(
                    role="system",
                    content=(
                        "Determine if the user's question requires multiple sequential "
                        "database queries, cross-referencing, or multi-step analysis. "
                        'Reply ONLY with JSON: {"complex": true/false, "reason": "..."}'
                    ),
                ),
                Message(role="user", content=question[:500]),
            ],
            max_tokens=60,
            temperature=0.0,
            preferred_provider=preferred_provider,
            model=model,
        )
        result = json.loads(resp.content.strip())
        return bool(result.get("complex", False))
    except Exception:
        logger.debug("Adaptive complexity classifier failed, defaulting to simple")
        return False


# ------------------------------------------------------------------
# Plan validation helpers
# ------------------------------------------------------------------

_VALID_TOOLS = {
    "query_database",
    "search_codebase",
    "analyze_results",
    "process_data",
    "synthesize",
    "query_mcp_source",
}


def _validate_plan_structure(stages: list[dict[str, Any]]) -> list[str]:
    """Return a list of errors (empty = valid)."""
    errors: list[str] = []
    if not stages:
        return ["Plan has no stages"]

    ids = {s.get("stage_id") for s in stages}

    for s in stages:
        sid = s.get("stage_id", "<missing>")
        tool = s.get("tool", "")
        if tool not in _VALID_TOOLS:
            errors.append(f"Stage '{sid}' has invalid tool '{tool}'")
        for dep in s.get("depends_on", []):
            if dep not in ids:
                errors.append(f"Stage '{sid}' depends on unknown stage '{dep}'")

    if not any(s.get("tool") in ("query_database", "search_codebase") for s in stages):
        errors.append("Plan must include at least one data-retrieval stage")

    # Topological cycle detection (Kahn's algorithm)
    in_deg: dict[str, int] = {s.get("stage_id", ""): 0 for s in stages}
    adj: dict[str, list[str]] = {s.get("stage_id", ""): [] for s in stages}
    for s in stages:
        for dep in s.get("depends_on", []):
            if dep in adj:
                adj[dep].append(s.get("stage_id", ""))
                in_deg[s.get("stage_id", "")] = in_deg.get(s.get("stage_id", ""), 0) + 1

    queue = [n for n, d in in_deg.items() if d == 0]
    visited = 0
    while queue:
        node = queue.pop(0)
        visited += 1
        for neighbor in adj.get(node, []):
            in_deg[neighbor] -= 1
            if in_deg[neighbor] == 0:
                queue.append(neighbor)

    if visited != len(stages):
        errors.append("Plan has circular dependencies")

    return errors


# ------------------------------------------------------------------
# Planner tool definition
# ------------------------------------------------------------------

_CREATE_PLAN_TOOL = {
    "type": "function",
    "function": {
        "name": "create_execution_plan",
        "description": "Create a multi-stage execution plan for a complex query.",
        "parameters": {
            "type": "object",
            "required": ["stages", "complexity_reason"],
            "properties": {
                "stages": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["stage_id", "description", "tool"],
                        "properties": {
                            "stage_id": {"type": "string"},
                            "description": {"type": "string"},
                            "tool": {
                                "type": "string",
                                "enum": list(_VALID_TOOLS),
                            },
                            "depends_on": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "input_context": {"type": "string"},
                            "validation": {
                                "type": "object",
                                "properties": {
                                    "expected_columns": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "min_rows": {"type": "integer"},
                                    "max_rows": {"type": "integer"},
                                    "business_rules": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "cross_stage_checks": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                },
                            },
                            "checkpoint": {"type": "boolean"},
                        },
                    },
                },
                "complexity_reason": {"type": "string"},
            },
        },
    },
}


# ------------------------------------------------------------------
# QueryPlanner class
# ------------------------------------------------------------------


class QueryPlanner:
    """Calls the LLM once to produce an ``ExecutionPlan``."""

    def __init__(self, llm_router: LLMRouter) -> None:
        self._llm = llm_router

    async def plan(
        self,
        question: str,
        *,
        table_map: str = "",
        db_type: str | None = None,
        preferred_provider: str | None = None,
        model: str | None = None,
        project_overview: str | None = None,
        current_datetime: str | None = None,
    ) -> ExecutionPlan | None:
        """Return an ``ExecutionPlan`` or ``None`` on unrecoverable failure."""
        for attempt in range(2):
            raw = await self._call_llm(
                question,
                table_map=table_map,
                db_type=db_type,
                preferred_provider=preferred_provider,
                model=model,
                project_overview=project_overview,
                current_datetime=current_datetime,
            )
            if raw is None:
                continue

            stages_raw = raw.get("stages", [])
            errors = _validate_plan_structure(stages_raw)
            if errors:
                logger.warning("Plan validation failed (attempt %d): %s", attempt + 1, errors)
                continue

            stages = [
                PlanStage(
                    stage_id=s["stage_id"],
                    description=s["description"],
                    tool=s["tool"],
                    depends_on=s.get("depends_on", []),
                    input_context=s.get("input_context", ""),
                    validation=StageValidation.from_dict(s.get("validation", {})),
                    checkpoint=s.get("checkpoint", False),
                )
                for s in stages_raw
            ]

            return ExecutionPlan(
                plan_id=str(uuid.uuid4()),
                question=question,
                stages=stages,
                complexity_reason=raw.get("complexity_reason", ""),
            )

        logger.error("QueryPlanner failed after 2 attempts — falling back to flat loop")
        return None

    async def _call_llm(
        self,
        question: str,
        *,
        table_map: str,
        db_type: str | None,
        preferred_provider: str | None,
        model: str | None,
        project_overview: str | None = None,
        current_datetime: str | None = None,
    ) -> dict[str, Any] | None:
        messages = [
            Message(role="system", content=PLANNER_SYSTEM_PROMPT),
            Message(
                role="user",
                content=build_planner_user_prompt(
                    question,
                    table_map,
                    db_type,
                    project_overview=project_overview,
                    current_datetime=current_datetime,
                ),
            ),
        ]
        try:
            resp = await self._llm.complete(
                messages=messages,
                tools=[_CREATE_PLAN_TOOL],  # type: ignore[list-item]
                preferred_provider=preferred_provider,
                model=model,
            )
        except Exception:
            logger.exception("Planner LLM call failed")
            return None

        if not resp.tool_calls:
            logger.warning("Planner did not call create_execution_plan tool")
            return None

        tc = resp.tool_calls[0]
        if tc.name != "create_execution_plan":
            logger.warning("Planner called unexpected tool: %s", tc.name)
            return None

        args = tc.arguments
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                logger.warning("Planner returned invalid JSON arguments")
                return None

        return args
