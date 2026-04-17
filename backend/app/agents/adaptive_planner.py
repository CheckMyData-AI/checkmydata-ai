"""AdaptivePlanner — generates execution plans for complex queries.

Full plans: LLM-based decomposition for complex/mixed queries.
Replan: LLM-based re-planning when a stage fails after retries.

Complexity detection is now handled by the unified router (router.py).
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from app.agents.prompts.planner_prompt import (
    PLANNER_SYSTEM_PROMPT,
    build_planner_user_prompt,
    build_replan_prompt,
)
from app.agents.query_planner import _CREATE_PLAN_TOOL, _validate_plan_structure
from app.agents.stage_context import (
    ExecutionPlan,
    PlanStage,
    StageResult,
    StageValidation,
)
from app.llm.base import Message
from app.llm.router import LLMRouter

logger = logging.getLogger(__name__)


class AdaptivePlanner:
    """Generates execution plans via LLM-based decomposition."""

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
        recent_learnings: str | None = None,
    ) -> ExecutionPlan:
        """Generate an LLM-based execution plan for the question."""
        plan = await self._llm_plan(
            question,
            table_map=table_map,
            db_type=db_type,
            preferred_provider=preferred_provider,
            model=model,
            project_overview=project_overview,
            current_datetime=current_datetime,
            recent_learnings=recent_learnings,
        )
        if plan is None:
            logger.warning("LLM planning failed, falling back to quick data plan")
            return self._quick_data_plan(question)

        plan = self._ensure_validation_criteria(plan)
        return plan

    async def replan(
        self,
        question: str,
        *,
        completed_stages: dict[str, StageResult],
        failed_stage: PlanStage,
        error: str,
        table_map: str = "",
        db_type: str | None = None,
        preferred_provider: str | None = None,
        model: str | None = None,
        replan_history: list[dict[str, str]] | None = None,
    ) -> ExecutionPlan | None:
        """Generate a new plan after a stage failure, keeping completed stages."""
        completed_summaries = []
        for stage_id, result in completed_stages.items():
            summary_parts = [f"Stage '{stage_id}': {result.status}"]
            if result.query:
                summary_parts.append(f"  Query: {result.query[:200]}")
            if result.query_result:
                summary_parts.append(
                    f"  Result: {result.query_result.row_count} rows, "
                    f"columns: {', '.join(result.query_result.columns[:10])}"
                )
            if result.summary:
                summary_parts.append(f"  Summary: {result.summary[:200]}")
            completed_summaries.append("\n".join(summary_parts))

        prompt = build_replan_prompt(
            question=question,
            completed_summaries=completed_summaries,
            failed_stage_id=failed_stage.stage_id,
            failed_stage_desc=failed_stage.description,
            failed_stage_tool=failed_stage.tool,
            error=error,
            table_map=table_map,
            db_type=db_type,
            replan_history=replan_history,
        )

        for attempt in range(2):
            try:
                resp = await self._llm.complete(
                    messages=[
                        Message(role="system", content=PLANNER_SYSTEM_PROMPT),
                        Message(role="user", content=prompt),
                    ],
                    tools=[_CREATE_PLAN_TOOL],  # type: ignore[list-item]
                    preferred_provider=preferred_provider,
                    model=model,
                )
            except Exception:
                logger.exception("Replan LLM call failed (attempt %d)", attempt + 1)
                continue

            if not resp.tool_calls:
                logger.warning("Replan did not produce a tool call (attempt %d)", attempt + 1)
                continue

            tc = resp.tool_calls[0]
            if tc.name != "create_execution_plan":
                continue

            args = tc.arguments
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    continue

            stages_raw = args.get("stages", [])
            errors = _validate_plan_structure(stages_raw)
            if errors:
                logger.warning("Replan validation failed (attempt %d): %s", attempt + 1, errors)
                continue

            stages = [PlanStage.from_dict(s) for s in stages_raw]
            plan = ExecutionPlan(
                plan_id=str(uuid.uuid4()),
                question=question,
                stages=stages,
                complexity_reason=args.get("complexity_reason", "replan"),
                plan_type="full",
            )
            return self._ensure_validation_criteria(plan)

        logger.error("Replan failed after 2 attempts")
        return None

    # ------------------------------------------------------------------
    # Quick plan builders (no LLM call)
    # ------------------------------------------------------------------

    @staticmethod
    def _quick_data_plan(question: str) -> ExecutionPlan:
        """Last-resort single-stage plan when LLM planning fails entirely."""
        return ExecutionPlan(
            plan_id=str(uuid.uuid4()),
            question=question,
            plan_type="quick",
            stages=[
                PlanStage(
                    stage_id="fetch",
                    description=question,
                    tool="query_database",
                    validation=StageValidation(min_rows=0),
                ),
            ],
        )

    # ------------------------------------------------------------------
    # LLM-based full planning
    # ------------------------------------------------------------------

    async def _llm_plan(
        self,
        question: str,
        *,
        table_map: str,
        db_type: str | None,
        preferred_provider: str | None,
        model: str | None,
        project_overview: str | None = None,
        current_datetime: str | None = None,
        recent_learnings: str | None = None,
    ) -> ExecutionPlan | None:
        for attempt in range(2):
            raw = await self._call_planner_llm(
                question,
                table_map=table_map,
                db_type=db_type,
                preferred_provider=preferred_provider,
                model=model,
                project_overview=project_overview,
                current_datetime=current_datetime,
                recent_learnings=recent_learnings,
            )
            if raw is None:
                continue

            stages_raw = raw.get("stages", [])
            errors = _validate_plan_structure(stages_raw)
            if errors:
                logger.warning("Plan validation failed (attempt %d): %s", attempt + 1, errors)
                continue

            stages = [PlanStage.from_dict(s) for s in stages_raw]
            return ExecutionPlan(
                plan_id=str(uuid.uuid4()),
                question=question,
                stages=stages,
                complexity_reason=raw.get("complexity_reason", ""),
                plan_type="full",
            )

        return None

    async def _call_planner_llm(
        self,
        question: str,
        *,
        table_map: str,
        db_type: str | None,
        preferred_provider: str | None,
        model: str | None,
        project_overview: str | None = None,
        current_datetime: str | None = None,
        recent_learnings: str | None = None,
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
                    recent_learnings=recent_learnings,
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

    # ------------------------------------------------------------------
    # Auto-inject validation criteria
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_validation_criteria(plan: ExecutionPlan) -> ExecutionPlan:
        """Auto-inject minimum validation criteria when the LLM omitted them."""
        for stage in plan.stages:
            v = stage.validation
            if stage.tool == "query_database":
                if v.min_rows is None and v.expected_columns is None:
                    v.min_rows = 0
                    v.auto_injected = True
            if stage.tool == "process_data":
                if v.min_rows is None:
                    for dep_id in stage.depends_on:
                        dep_stage = plan.get_stage(dep_id)
                        if dep_stage and dep_stage.validation.min_rows is not None:
                            v.min_rows = 1
                            v.auto_injected = True
                            break
        return plan
