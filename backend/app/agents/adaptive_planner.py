"""AdaptivePlanner — generates quick or full execution plans.

Quick plans: deterministic, instant (no LLM call).
Full plans: LLM-based decomposition for complex/mixed queries.
Replan: LLM-based re-planning when a stage fails after retries.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from app.agents.intent_classifier import IntentType
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

_COMPLEXITY_KEYWORDS = [
    # English
    "summary table",
    "pivot",
    "breakdown",
    "cross-reference",
    "compare",
    "for each",
    "match",
    "correlate",
    " then ",
    "step 1",
    "step 2",
    "first find",
    "after that",
    # Russian
    "сводная таблица",
    "разбивка по",
    "сравни",
    "для каждого",
    "затем ",
    "шаг 1",
    "шаг 2",
    "сначала найди",
    "после этого",
    "перекрёстн",
    "корреляц",
    # Spanish
    "tabla resumen",
    "desglose",
    "comparar",
    "para cada",
    "paso 1",
    "paso 2",
    "primero encuentra",
    "después de",
    # German
    "zusammenfassung",
    "aufschlüsselung",
    "vergleich",
    "für jede",
    "schritt 1",
    "schritt 2",
    "zuerst find",
    "danach",
    # Portuguese
    "tabela resumo",
    "detalhamento",
    "comparar",
    "para cada",
    "passo 1",
    "passo 2",
    "primeiro encontr",
    "depois disso",
]


class AdaptivePlanner:
    """Generates execution plans adaptively based on intent and complexity."""

    def __init__(self, llm_router: LLMRouter) -> None:
        self._llm = llm_router

    async def plan(
        self,
        question: str,
        intent: IntentType,
        *,
        table_map: str = "",
        db_type: str | None = None,
        preferred_provider: str | None = None,
        model: str | None = None,
        project_overview: str | None = None,
        current_datetime: str | None = None,
        recent_learnings: str | None = None,
    ) -> ExecutionPlan:
        if intent == IntentType.DIRECT_RESPONSE:
            return self._quick_direct_plan(question)

        if intent == IntentType.DATA_QUERY and not self._is_complex(question):
            return self._quick_data_plan(question)

        if intent == IntentType.KNOWLEDGE_QUERY:
            return self._quick_knowledge_plan(question)

        if intent == IntentType.MCP_QUERY:
            return self._quick_mcp_plan(question)

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
    def _quick_direct_plan(question: str) -> ExecutionPlan:
        return ExecutionPlan(
            plan_id=str(uuid.uuid4()),
            question=question,
            plan_type="quick",
            stages=[
                PlanStage(
                    stage_id="respond",
                    description=question,
                    tool="synthesize",
                    max_retries=0,
                    replan_on_failure=False,
                ),
            ],
        )

    @staticmethod
    def _quick_data_plan(question: str) -> ExecutionPlan:
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

    @staticmethod
    def _quick_knowledge_plan(question: str) -> ExecutionPlan:
        return ExecutionPlan(
            plan_id=str(uuid.uuid4()),
            question=question,
            plan_type="quick",
            stages=[
                PlanStage(
                    stage_id="search",
                    description=question,
                    tool="search_codebase",
                    max_retries=1,
                ),
            ],
        )

    @staticmethod
    def _quick_mcp_plan(question: str) -> ExecutionPlan:
        return ExecutionPlan(
            plan_id=str(uuid.uuid4()),
            question=question,
            plan_type="quick",
            stages=[
                PlanStage(
                    stage_id="query",
                    description=question,
                    tool="query_mcp_source",
                    max_retries=1,
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
    # Complexity heuristic
    # ------------------------------------------------------------------

    _CONJUNCTION_WORDS = [
        "and",
        "also",
        "plus",
        "и",
        "также",
        "плюс",  # Russian
        "y",
        "también",
        "además",  # Spanish
        "und",
        "auch",
        "außerdem",  # German
        "e",
        "também",
        "além disso",  # Portuguese
    ]

    @staticmethod
    def _is_complex(question: str) -> bool:
        q_lower = question.lower()
        indicators = [
            len(question) > 300,
            any(kw in q_lower for kw in _COMPLEXITY_KEYWORDS),
            question.count("?") > 1,
            question.count(",") > 3
            and any(v in q_lower for v in AdaptivePlanner._CONJUNCTION_WORDS),
        ]
        return sum(indicators) >= 2

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
