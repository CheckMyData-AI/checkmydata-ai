"""StageExecutor — runs pipeline stages sequentially with validation,
retry, checkpoint pauses, and resume-from-stage capability.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import replace
from typing import Any

from app.agents.base import AgentContext, BaseAgent
from app.agents.data_gate import DataGate, DataGateOutcome
from app.agents.errors import AgentError, AgentFatalError, AgentRetryableError
from app.agents.result_validation import ResultValidation
from app.agents.stage_context import (
    ExecutionPlan,
    PlanStage,
    StageContext,
    StageResult,
)
from app.agents.stage_validator import StageValidationOutcome, StageValidator
from app.config import settings
from app.connectors.base import QueryResult
from app.core.workflow_tracker import WorkflowTracker
from app.llm.base import Message
from app.llm.errors import LLMError
from app.llm.retry import llm_call_with_retry
from app.llm.router import LLMRouter
from app.services.data_processor import get_data_processor

logger = logging.getLogger(__name__)


def _stage_error_message(exc: BaseException) -> str:
    """Convert a sub-agent exception into a user-friendly stage error string.

    Prefers ``LLMError.user_message`` (typed-friendly); falls back to ``str(exc)``
    truncated to keep stage records compact.
    """
    if isinstance(exc, LLMError):
        return exc.user_message
    msg = str(exc).strip()
    if not msg:
        msg = type(exc).__name__
    return msg[:500]


def _classify_stage_error(exc: BaseException) -> str:
    """Map an exception into a stage ``error_category``.

    Returns one of ``transient | configuration | data_missing | fatal``.
    Used by :class:`StageExecutor` to decide whether retry is sensible.
    """
    from app.agents.errors import AgentFatalError, AgentRetryableError
    from app.llm.errors import LLMAllProvidersFailedError, LLMError

    if isinstance(exc, AgentRetryableError):
        return "transient"
    if isinstance(exc, AgentFatalError):
        return "fatal"
    if isinstance(exc, LLMAllProvidersFailedError):
        return "configuration"
    if isinstance(exc, LLMError):
        return "transient" if getattr(exc, "is_retryable", False) else "configuration"
    # Known-transient infrastructure errors are safe to retry. ``TimeoutError``
    # is the canonical alias for ``asyncio.TimeoutError`` on 3.11+, and
    # ``ConnectionError`` covers reset/refused/aborted.
    # OSError covers TimeoutError, ConnectionError (reset/refused/aborted) and
    # socket/DNS errors (gaierror) — all genuinely transient infra blips.
    if isinstance(exc, OSError):
        return "transient"
    # Everything else is almost certainly a deterministic bug (KeyError,
    # TypeError, ValueError, connector misuse). Retrying just burns budget and
    # latency and masks the root cause — classify non-retryable and log so the
    # fallthrough is observable.
    logger.warning(
        "Stage error classified non-retryable (configuration): %s: %s",
        type(exc).__name__,
        exc,
    )
    return "configuration"


class StageExecutor:
    """Executes an ``ExecutionPlan`` stage-by-stage."""

    def __init__(
        self,
        *,
        sql_agent: BaseAgent,
        knowledge_agent: BaseAgent,
        llm_router: LLMRouter,
        tracker: WorkflowTracker,
        validator: StageValidator | None = None,
        data_gate: DataGate | None = None,
        mcp_source_agent: BaseAgent | None = None,
        git_agent: BaseAgent | None = None,
    ) -> None:
        self._sql = sql_agent
        self._knowledge = knowledge_agent
        self._llm = llm_router
        self._tracker = tracker
        self._validator = validator or StageValidator(llm_router=llm_router)
        self._data_gate = data_gate or DataGate()
        self._mcp_source = mcp_source_agent
        self._git = git_agent
        self._staleness_warning: str | None = None
        # ORCH-A01 / T10: shared result-quality gate (C-B).  Built lazily and
        # cached so callers can inject a pre-built instance in tests.  The gate
        # is always constructed with ``skip_data_gate=True`` at the _run_sql_stage
        # call-site; the broader DataGate.check() still runs in _process_one_stage.
        self._result_validation: ResultValidation | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(
        self,
        plan: ExecutionPlan,
        context: AgentContext,
        *,
        resume_from: int = 0,
        stage_ctx: StageContext | None = None,
        staleness_warning: str | None = None,
    ) -> _StageExecutorResult:
        """Run stages topologically — parallel where dependencies allow.

        Stages whose ``depends_on`` is empty (or already satisfied) and that
        are not yet present in ``stage_ctx.results`` form a "ready batch" and
        are dispatched concurrently (capped by
        ``settings.pipeline_max_parallel_stages``). The first failure in a
        batch short-circuits the pipeline. Checkpoints pause execution after
        the batch in which they appear completes.

        ``staleness_warning`` (V3, vision §7 #7) — when non-empty, prepended to
        each stage's enriched-question and to the synthesis system prompt so
        every LLM-touching surface in the complex path is freshness-aware.
        """
        import asyncio as _asyncio

        wf_id = context.workflow_id

        if stage_ctx is None:
            stage_ctx = StageContext(plan=plan, pipeline_run_id="")

        self._staleness_warning = staleness_warning

        await self._emit_plan(wf_id, plan)

        n_stages = len(plan.stages)
        stage_idx_map = {s.stage_id: i for i, s in enumerate(plan.stages)}
        max_parallel = max(1, settings.pipeline_max_parallel_stages)

        # B4: per-pipeline wall-clock budget. Bounds the compounded retry
        # surface (per-stage × validation × data-gate) by refusing to dispatch a
        # new batch once the budget is spent. 0 → fall back to the per-request
        # agent wall-clock limit.
        budget_seconds = (
            settings.pipeline_max_wall_seconds or settings.agent_wall_clock_timeout_seconds
        )
        deadline = time.monotonic() + budget_seconds if budget_seconds > 0 else None

        while True:
            completed_ids = set(stage_ctx.results.keys())
            if len(completed_ids) >= n_stages:
                break

            if deadline is not None and time.monotonic() > deadline:
                remaining = [s for s in plan.stages if s.stage_id not in completed_ids]
                logger.warning(
                    "Pipeline wall-clock budget (%ss) exhausted with %d stage(s) "
                    "remaining — stopping before next batch",
                    budget_seconds,
                    len(remaining),
                )
                if remaining:
                    await self._tracker.emit(
                        wf_id,
                        "stage_failed",
                        "failed",
                        f"Pipeline time budget exhausted ({budget_seconds}s) — "
                        f"{len(remaining)} stage(s) not run",
                        stage_id=remaining[0].stage_id,
                        remaining_stage_ids=[s.stage_id for s in remaining],
                    )
                    # Not replan-eligible: replanning would only consume more of
                    # an already-spent budget. Surface honest partial results.
                    return _StageExecutorResult(
                        status="stage_failed",
                        stage_ctx=stage_ctx,
                        failed_stage=remaining[0],
                        replan_eligible=False,
                    )
                break

            ready: list[PlanStage] = [
                s
                for s in plan.stages
                if s.stage_id not in completed_ids
                and stage_idx_map[s.stage_id] >= resume_from
                and all(dep in completed_ids for dep in s.depends_on)
            ]
            if not ready:
                remaining = [s for s in plan.stages if s.stage_id not in completed_ids]
                logger.warning(
                    "Pipeline stuck: %d stage(s) remain with unmet dependencies",
                    n_stages - len(completed_ids),
                )
                # R5-6: a stuck dependency graph previously fell through to
                # synthesize partial results and returned ``completed`` — the
                # caller could not tell a stuck pipeline from a clean one.
                # Surface it as ``stage_failed`` (replan-eligible) so the
                # orchestrator can replan around the unsatisfiable stage instead
                # of silently presenting partial data as authoritative.
                if remaining:
                    # Tell SSE consumers the pipeline is stuck (previously the
                    # status flipped to stage_failed with no tracker event, so
                    # the UI kept showing the last stage as in-progress).
                    await self._tracker.emit(
                        wf_id,
                        "stage_failed",
                        "failed",
                        f"Pipeline stuck: {len(remaining)} stage(s) have unmet dependencies",
                        stage_id=remaining[0].stage_id,
                        remaining_stage_ids=[s.stage_id for s in remaining],
                    )
                    return _StageExecutorResult(
                        status="stage_failed",
                        stage_ctx=stage_ctx,
                        failed_stage=remaining[0],
                        replan_eligible=True,
                    )
                break

            batch = ready[:max_parallel]
            for i, s in enumerate(batch):
                if s.checkpoint:
                    batch = batch[: i + 1]
                    break

            for s in batch:
                stage_ctx.current_stage_idx = stage_idx_map[s.stage_id]
                await self._emit_stage_start(wf_id, s, stage_idx_map[s.stage_id], n_stages)

            if len(batch) == 1:
                outcomes: list[_StageExecutorResult | None] = [
                    await self._process_one_stage(batch[0], stage_ctx, context)
                ]
            else:
                # return_exceptions=True so one stage raising does NOT propagate
                # immediately and orphan its siblings (which keep running with
                # dangling sessions). Wait for all, then convert any raised
                # exception into a graceful stage_failed outcome.
                gathered = await _asyncio.gather(
                    *(self._process_one_stage(s, stage_ctx, context) for s in batch),
                    return_exceptions=True,
                )
                outcomes = []
                for stage, res in zip(batch, gathered):
                    if isinstance(res, BaseException):
                        if isinstance(res, _asyncio.CancelledError):
                            raise res
                        logger.error(
                            "Parallel stage %s raised; converting to stage_failed",
                            stage.stage_id,
                            exc_info=res,
                        )
                        outcomes.append(
                            _StageExecutorResult(
                                status="stage_failed",
                                stage_ctx=stage_ctx,
                                failed_stage=stage,
                                failed_validation=StageValidationOutcome(
                                    passed=False, errors=[str(res)]
                                ),
                                replan_eligible=stage.replan_on_failure,
                            )
                        )
                    else:
                        outcomes.append(res)

            for stage, outcome in zip(batch, outcomes):
                if outcome is not None and outcome.status == "stage_failed":
                    return outcome

            for stage, outcome in zip(batch, outcomes):
                if outcome is not None and outcome.status == "checkpoint":
                    return outcome

        last_stage = plan.stages[-1] if plan.stages else None
        if last_stage and last_stage.tool == "synthesize":
            last_result = stage_ctx.results.get(last_stage.stage_id)
            if last_result and last_result.summary:
                return _StageExecutorResult(
                    status="completed", stage_ctx=stage_ctx, final_answer=last_result.summary
                )

        final_answer, _degraded_reason = await self._synthesize(stage_ctx, context)
        return _StageExecutorResult(
            status="completed", stage_ctx=stage_ctx, final_answer=final_answer
        )

    async def _process_one_stage(
        self,
        stage: PlanStage,
        stage_ctx: StageContext,
        context: AgentContext,
    ) -> _StageExecutorResult | None:
        """Run a single stage end-to-end (dispatch, validate, data-gate, persist).

        Returns ``None`` when the stage succeeded and the pipeline should
        continue, a ``_StageExecutorResult`` with status ``"stage_failed"`` on
        failure, or status ``"checkpoint"`` when this stage paused the
        pipeline.
        """
        wf_id = context.workflow_id
        idx = next(
            (i for i, s in enumerate(stage_ctx.plan.stages) if s.stage_id == stage.stage_id), 0
        )

        result = await self._execute_with_retries(stage, stage_ctx, context)

        if result.status == "error":
            await self._emit_stage_result(wf_id, stage, result)
            return _StageExecutorResult(
                status="stage_failed",
                stage_ctx=stage_ctx,
                failed_stage=stage,
                failed_validation=StageValidationOutcome(
                    passed=False, errors=[result.error or "unknown"]
                ),
                replan_eligible=stage.replan_on_failure,
            )

        validation = await self._validator.validate_async(stage, result, stage_ctx)
        await self._emit_stage_validation(wf_id, stage, validation)

        if not validation.passed:
            retried = await self._retry_failed_validation(stage, stage_ctx, context, validation)
            if retried is None:
                await self._emit_stage_result(wf_id, stage, result)
                return _StageExecutorResult(
                    status="stage_failed",
                    stage_ctx=stage_ctx,
                    failed_stage=stage,
                    failed_validation=validation,
                    replan_eligible=stage.replan_on_failure,
                )
            result = retried

        await self._tracker.emit(
            wf_id,
            "data_gate",
            "checking",
            "Validating stage output…",
            stage_id=stage.stage_id,
        )
        gate_outcome = self._data_gate.check(stage, result, stage_ctx)
        await self._emit_data_gate(wf_id, stage, gate_outcome)

        if not gate_outcome.passed:
            retried = await self._retry_failed_data_gate(stage, stage_ctx, context, gate_outcome)
            if retried is None:
                await self._emit_stage_result(wf_id, stage, result)
                return _StageExecutorResult(
                    status="stage_failed",
                    stage_ctx=stage_ctx,
                    failed_stage=stage,
                    failed_validation=StageValidationOutcome(
                        passed=False, errors=gate_outcome.errors
                    ),
                    data_gate_outcome=gate_outcome,
                    replan_eligible=stage.replan_on_failure,
                )
            result = retried

        stage_ctx.set_result(stage.stage_id, result)
        await self._emit_stage_complete(wf_id, stage, result, idx)
        await self._emit_stage_result(wf_id, stage, result)

        if stage.checkpoint:
            await self._emit_checkpoint(wf_id, stage, result)
            return _StageExecutorResult(
                status="checkpoint",
                stage_ctx=stage_ctx,
                checkpoint_stage=stage,
                checkpoint_result=result,
            )

        return None

    # ------------------------------------------------------------------
    # Shared result-quality gate (ORCH-A01 / T10)
    # ------------------------------------------------------------------

    def _get_result_validation(self) -> ResultValidation:
        """Return the cached :class:`ResultValidation` gate, building it on first call.

        Callers in tests may pre-assign ``self._result_validation`` to inject a
        spy or mock before calling ``_run_sql_stage``.
        """
        if self._result_validation is None:
            from app.agents.validation import AgentResultValidator

            self._result_validation = ResultValidation(self._data_gate, AgentResultValidator())
        return self._result_validation

    # ------------------------------------------------------------------
    # Stage dispatch
    # ------------------------------------------------------------------

    async def _execute_stage(
        self,
        stage: PlanStage,
        stage_ctx: StageContext,
        context: AgentContext,
        error_context: str | None = None,
    ) -> StageResult:
        enriched_q = self._build_stage_question(stage, stage_ctx, error_context)

        try:
            match stage.tool:
                case "query_database":
                    return await self._run_sql_stage(enriched_q, stage, context)
                case "search_codebase":
                    return await self._run_knowledge_stage(enriched_q, stage, context)
                case "analyze_results":
                    return await self._run_analysis_stage(enriched_q, stage, stage_ctx, context)
                case "process_data":
                    return await self._run_process_data_stage(stage, stage_ctx, context)
                case "query_mcp_source":
                    return await self._run_mcp_stage(enriched_q, stage, context)
                case "analyze_git":
                    return await self._run_git_stage(enriched_q, stage, context)
                case "synthesize":
                    return await self._synthesize_stage(stage, stage_ctx, context)
                case _:
                    return StageResult(
                        stage_id=stage.stage_id,
                        status="error",
                        error=f"Unknown tool: {stage.tool}",
                        error_category="fatal",
                    )
        except Exception as exc:
            logger.exception("Stage '%s' raised an exception", stage.stage_id)
            return StageResult(
                stage_id=stage.stage_id,
                status="error",
                error=_stage_error_message(exc),
                error_category=_classify_stage_error(exc),
            )

    async def _execute_with_retries(
        self,
        stage: PlanStage,
        stage_ctx: StageContext,
        context: AgentContext,
    ) -> StageResult:
        """Execute a stage, retrying on retryable sub-agent errors.

        Uses per-stage ``max_retries`` (falls back to global setting).
        """
        wf_id = context.workflow_id
        max_retries = stage.max_retries if stage.max_retries >= 0 else settings.max_stage_retries
        for attempt in range(max_retries + 1):
            result = await self._execute_stage(stage, stage_ctx, context)
            if result.status != "error":
                return result
            if not result.retryable:
                logger.info(
                    "Stage '%s' failed with non-retryable error_category=%s; skipping retry",
                    stage.stage_id,
                    result.error_category,
                )
                return result
            if attempt < max_retries:
                await self._tracker.emit(
                    wf_id,
                    "stage_retry",
                    "retrying",
                    f"Stage '{stage.stage_id}' attempt {attempt + 2}",
                    stage_id=stage.stage_id,
                    attempt=attempt + 2,
                    reason=result.error or "",
                )
        return result

    async def _retry_failed_validation(
        self,
        stage: PlanStage,
        stage_ctx: StageContext,
        context: AgentContext,
        validation: StageValidationOutcome,
    ) -> StageResult | None:
        """Retry the stage with error context (uses per-stage max_retries)."""
        wf_id = context.workflow_id
        max_retries = stage.max_retries if stage.max_retries >= 0 else settings.max_stage_retries
        for retry in range(max_retries):
            await self._tracker.emit(
                wf_id,
                "stage_retry",
                "retrying",
                f"Stage '{stage.stage_id}' validation failed, retry {retry + 1}",
                stage_id=stage.stage_id,
                attempt=retry + 2,
                reason=validation.error_summary,
            )
            result = await self._execute_stage(
                stage, stage_ctx, context, error_context=validation.error_summary
            )
            if result.status == "error":
                continue
            validation = await self._validator.validate_async(stage, result, stage_ctx)
            await self._emit_stage_validation(wf_id, stage, validation)
            if validation.passed:
                return result
        return None

    async def _retry_failed_data_gate(
        self,
        stage: PlanStage,
        stage_ctx: StageContext,
        context: AgentContext,
        gate_outcome: DataGateOutcome,
    ) -> StageResult | None:
        """Retry after DataGate failure, feeding suggestions as error context."""
        wf_id = context.workflow_id
        max_retries = stage.max_retries if stage.max_retries >= 0 else settings.max_stage_retries
        error_ctx = gate_outcome.error_summary
        if gate_outcome.suggestions:
            error_ctx += " Suggestions: " + "; ".join(gate_outcome.suggestions)
        for retry in range(max_retries):
            await self._tracker.emit(
                wf_id,
                "stage_retry",
                "retrying",
                f"Stage '{stage.stage_id}' data-gate failed, retry {retry + 1}",
                stage_id=stage.stage_id,
                attempt=retry + 2,
                reason=error_ctx,
            )
            result = await self._execute_stage(
                stage,
                stage_ctx,
                context,
                error_context=error_ctx,
            )
            if result.status == "error":
                continue
            validation = await self._validator.validate_async(stage, result, stage_ctx)
            if not validation.passed:
                continue
            new_gate = self._data_gate.check(stage, result, stage_ctx)
            await self._emit_data_gate(wf_id, stage, new_gate)
            if new_gate.passed:
                return result
        return None

    # ------------------------------------------------------------------
    # Stage question builder
    # ------------------------------------------------------------------

    def _build_stage_question(
        self,
        stage: PlanStage,
        stage_ctx: StageContext,
        error_context: str | None = None,
    ) -> str:
        parts: list[str] = []

        if self._staleness_warning:
            parts.append(f"KNOWLEDGE FRESHNESS WARNINGS:\n{self._staleness_warning}")

        prev_context = stage_ctx.build_context_for_stage(stage.stage_id)
        if prev_context:
            parts.append(prev_context)

        parts.append(f"Task: {stage.description}")

        if stage.input_context:
            parts.append(f"Required input: {stage.input_context}")

        if error_context:
            parts.append(
                f"IMPORTANT: The previous attempt failed validation: {error_context}. "
                "Please adjust your approach."
            )

        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Stage runners
    # ------------------------------------------------------------------

    async def _run_sql_stage(
        self,
        question: str,
        stage: PlanStage,
        context: AgentContext,
    ) -> StageResult:
        scoped = replace(
            context,
            chat_history=context.chat_history[-settings.history_tail_messages :]
            if context.chat_history
            else [],
        )
        try:
            sql_result = await self._sql.run(scoped, question=question)
        except (AgentRetryableError, AgentFatalError, AgentError) as e:
            return StageResult(
                stage_id=stage.stage_id,
                status="error",
                error=_stage_error_message(e),
                error_category=_classify_stage_error(e),
            )
        except LLMError as e:
            return StageResult(
                stage_id=stage.stage_id,
                status="error",
                error=e.user_message,
                error_category=_classify_stage_error(e),
            )

        if sql_result.status == "error":
            return StageResult(
                stage_id=stage.stage_id,
                status="error",
                error=sql_result.error or "SQL agent error",
                token_usage=sql_result.token_usage,
            )

        qr: QueryResult | None = getattr(sql_result, "results", None)
        query: str | None = getattr(sql_result, "query", None)

        # ORCH-A01 / T10: apply the shared result-quality gate so the pipeline
        # SQL path gets the same error/requery/warn/accept assurance as the flat
        # loop.  ``skip_data_gate=True`` prevents double-invocation:
        # ``_process_one_stage`` runs ``DataGate.check()`` (comprehensive null/
        # dup/type/range/cross-stage checks) on the StageResult afterwards.
        _rv_warning_suffix: str = ""
        if qr is not None and query:
            try:
                gate = self._get_result_validation()
                question = getattr(context, "user_question", "") or stage.description
                directive = gate.evaluate(
                    qr,
                    question=question,
                    sql=query,
                    truncated=qr.truncated,
                    skip_data_gate=True,
                )
                if directive.action in ("block", "requery"):
                    return StageResult(
                        stage_id=stage.stage_id,
                        status="error",
                        error=directive.reason,
                        error_category="data_missing"
                        if directive.action == "requery"
                        else "configuration",
                        token_usage=sql_result.token_usage,
                    )
                if directive.action == "warn":
                    _rv_warning_suffix = f"\n\n**DATA QUALITY WARNING:** {directive.reason}"
            except Exception:
                # Gate failure is non-critical — log and proceed so a gate bug
                # never silently kills a valid pipeline stage.
                logger.debug(
                    "pipeline result-validation gate failed (non-critical)",
                    exc_info=True,
                )

        summary = self._summarize_query_result(query, qr)
        if _rv_warning_suffix:
            summary = (summary or "") + _rv_warning_suffix

        return StageResult(
            stage_id=stage.stage_id,
            status="success",
            query=query,
            query_result=qr,
            summary=summary,
            token_usage=sql_result.token_usage,
        )

    async def _run_knowledge_stage(
        self,
        question: str,
        stage: PlanStage,
        context: AgentContext,
    ) -> StageResult:
        scoped = replace(
            context,
            chat_history=context.chat_history[-settings.history_tail_messages :]
            if context.chat_history
            else [],
        )
        try:
            kb_result = await self._knowledge.run(scoped, question=question)
        except (AgentRetryableError, AgentFatalError, AgentError) as e:
            return StageResult(
                stage_id=stage.stage_id,
                status="error",
                error=_stage_error_message(e),
                error_category=_classify_stage_error(e),
            )
        except LLMError as e:
            return StageResult(
                stage_id=stage.stage_id,
                status="error",
                error=e.user_message,
                error_category=_classify_stage_error(e),
            )

        answer = getattr(kb_result, "answer", "")
        return StageResult(
            stage_id=stage.stage_id,
            status="success" if answer else "error",
            summary=answer,
            error=None if answer else "Knowledge agent returned empty answer",
            token_usage=kb_result.token_usage,
        )

    async def _run_git_stage(
        self,
        question: str,
        stage: PlanStage,
        context: AgentContext,
    ) -> StageResult:
        """Run a Git-history analysis stage via the GitAgent."""
        if self._git is None:
            return StageResult(
                stage_id=stage.stage_id,
                status="error",
                error="Git analysis is not available (no GitAgent wired).",
                error_category="fatal",
            )
        scoped = replace(
            context,
            chat_history=context.chat_history[-settings.history_tail_messages :]
            if context.chat_history
            else [],
        )
        try:
            git_result = await self._git.run(scoped, question=question)
        except (AgentRetryableError, AgentFatalError, AgentError) as e:
            return StageResult(
                stage_id=stage.stage_id,
                status="error",
                error=_stage_error_message(e),
                error_category=_classify_stage_error(e),
            )
        except LLMError as e:
            return StageResult(
                stage_id=stage.stage_id,
                status="error",
                error=e.user_message,
                error_category=_classify_stage_error(e),
            )

        answer = getattr(git_result, "answer", "")
        return StageResult(
            stage_id=stage.stage_id,
            status="success" if answer else "error",
            summary=answer,
            error=None if answer else "Git agent returned empty answer",
            token_usage=git_result.token_usage,
        )

    async def _run_analysis_stage(
        self,
        question: str,
        stage: PlanStage,
        stage_ctx: StageContext,
        context: AgentContext,
    ) -> StageResult:
        """Use the LLM to analyse data from previous stages."""
        messages = [
            Message(
                role="system",
                content=(
                    "You are a data analysis assistant. Analyse the data provided "
                    "from previous pipeline stages and produce the requested output. "
                    "Reason in English; this is an intermediate analysis step."
                ),
            ),
            Message(role="user", content=question),
        ]
        try:
            resp = await llm_call_with_retry(
                self._llm,
                messages=messages,
                tools=None,
                preferred_provider=context.preferred_provider,
                model=context.model,
                component="analysis_stage",
            )
        except Exception as exc:
            logger.warning("Analysis stage '%s' LLM call failed", stage.stage_id, exc_info=True)
            return StageResult(
                stage_id=stage.stage_id,
                status="error",
                error=_stage_error_message(exc),
                error_category=_classify_stage_error(exc),
            )

        return StageResult(
            stage_id=stage.stage_id,
            status="success",
            summary=resp.content or "",
            token_usage=resp.usage or {},
        )

    async def _run_mcp_stage(
        self,
        question: str,
        stage: PlanStage,
        context: AgentContext,
    ) -> StageResult:
        """Query an external MCP data source."""
        if self._mcp_source is None:
            return StageResult(
                stage_id=stage.stage_id,
                status="error",
                error="MCP source agent not configured for this pipeline",
                error_category="configuration",
            )
        try:
            result = await self._mcp_source.run(
                replace(
                    context,
                    chat_history=context.chat_history[-settings.history_tail_messages :]
                    if context.chat_history
                    else [],
                ),
                question=question,
            )
            answer = getattr(result, "answer", "") or ""
            mcp_status = getattr(result, "status", "")
            if mcp_status == "success":
                return StageResult(
                    stage_id=stage.stage_id,
                    status="success",
                    summary=answer,
                    token_usage=getattr(result, "token_usage", {}),
                )
            # Anything else (error / no_result / iteration-exhausted placeholder)
            # is a stage failure — do NOT surface the placeholder as a real
            # answer. "no_result" is data_missing (recoverable via replan);
            # an explicit "error" carries the agent's own classification.
            return StageResult(
                stage_id=stage.stage_id,
                status="error",
                error=getattr(result, "error", None) or answer or "MCP source returned no result",
                error_category="configuration" if mcp_status == "error" else "data_missing",
                token_usage=getattr(result, "token_usage", {}),
            )
        except Exception as exc:
            logger.exception("MCP stage '%s' failed", stage.stage_id)
            return StageResult(
                stage_id=stage.stage_id,
                status="error",
                error=_stage_error_message(exc),
                error_category=_classify_stage_error(exc),
            )

    @staticmethod
    def _select_process_data_source(
        stage: PlanStage, stage_ctx: StageContext
    ) -> QueryResult | None:
        """Pick the source dataset for a ``process_data`` stage.

        Honors the declared ``depends_on`` contract: a process_data stage with
        explicit dependencies pulls ONLY from those (most recent first). If the
        declared deps produced no rows we return ``None`` (→ ``data_missing``)
        rather than silently scavenging an unrelated prior stage's dataset,
        which previously let a transform run on the wrong data and present it
        as the dependency's result. Only when there are NO declared deps do we
        best-effort fall back to the most recent prior stage with rows.
        """
        for dep_id in reversed(stage.depends_on):
            dep_result = stage_ctx.get_result(dep_id)
            if dep_result and dep_result.query_result and dep_result.query_result.rows:
                return dep_result.query_result

        if stage.depends_on:
            # Declared deps exist but none produced rows — do not scavenge.
            return None

        # No declared deps: best-effort fall back to the most recent PRIOR
        # stage (earlier in plan order) that produced rows.
        prior_stages: list[PlanStage] = []
        for st in stage_ctx.plan.stages:
            if st.stage_id == stage.stage_id:
                break
            prior_stages.append(st)
        for prev in reversed(prior_stages):
            sr = stage_ctx.get_result(prev.stage_id)
            if sr and sr.query_result and sr.query_result.rows:
                logger.warning(
                    "process_data stage '%s' has no declared depends_on; "
                    "falling back to prior stage '%s'",
                    stage.stage_id,
                    prev.stage_id,
                )
                return sr.query_result
        return None

    async def _run_process_data_stage(
        self,
        stage: PlanStage,
        stage_ctx: StageContext,
        context: AgentContext | None = None,
    ) -> StageResult:
        """Apply a data-processing operation to its declared source stage."""
        wf_id = context.workflow_id if context else ""

        source_qr = self._select_process_data_source(stage, stage_ctx)

        if source_qr is None:
            return StageResult(
                stage_id=stage.stage_id,
                status="error",
                error="No query result available from the declared source stage(s) to process.",
                error_category="data_missing",
            )

        params = self._parse_process_data_params(stage, source_qr)
        operation = params.get("operation", "unknown")

        await self._tracker.emit(
            wf_id,
            "thinking",
            "in_progress",
            f"Processing data: {operation} on {source_qr.row_count} rows…",
        )

        try:
            processor = get_data_processor()
            processed = processor.process(source_qr, params.pop("operation"), params)
        except Exception as exc:
            return StageResult(
                stage_id=stage.stage_id,
                status="error",
                error=_stage_error_message(exc),
                error_category=_classify_stage_error(exc),
            )

        await self._tracker.emit(
            wf_id,
            "thinking",
            "completed",
            processed.summary[:120],
        )

        return StageResult(
            stage_id=stage.stage_id,
            status="success",
            query_result=processed.query_result,
            summary=processed.summary,
        )

    @staticmethod
    def _parse_process_data_params(stage: PlanStage, source_qr: QueryResult) -> dict[str, Any]:
        """Extract operation params from ``input_context`` (JSON).

        The planner must specify the operation explicitly. No keyword-based
        inference is performed.

        ORCH-P02: accepts both the canonical top-level key convention and the
        legacy ``params_json`` wrapper for back-compat. When ``params_json``
        is present and is a dict, its keys are merged in (top-level keys win
        on overlap) and the ``params_json`` key itself is removed.
        """
        params: dict[str, Any] = {}
        if stage.input_context:
            try:
                parsed = json.loads(stage.input_context)
                if isinstance(parsed, dict):
                    params = parsed
            except (json.JSONDecodeError, TypeError):
                pass

        # Unwrap params_json wrapper if present (back-compat with orchestrator
        # prompt convention that placed cohort_window params inside params_json).
        if "params_json" in params and isinstance(params["params_json"], dict):
            inner = params.pop("params_json")
            # Top-level keys win; inner fills anything not already present.
            for k, v in inner.items():
                if k not in params:
                    params[k] = v

        if "operation" not in params:
            # R5-8: don't guess a concrete transform (the old default,
            # ``filter_data``, either errors out on a missing column or silently
            # drops rows). Forward the source rows unchanged instead.
            logger.warning(
                "process_data stage '%s' missing 'operation' in input_context, "
                "defaulting to passthrough (forward rows unchanged)",
                stage.stage_id,
            )
            params["operation"] = "passthrough"

        if "aggregations" in params and isinstance(params["aggregations"], dict):
            params["aggregations"] = list(params["aggregations"].items())

        return params

    async def _synthesize_stage(
        self,
        stage: PlanStage,
        stage_ctx: StageContext,
        context: AgentContext,
    ) -> StageResult:
        """Produce the final user-facing answer from all stages."""
        answer, degraded_reason = await self._synthesize(stage_ctx, context)
        return StageResult(
            stage_id=stage.stage_id,
            status="degraded" if degraded_reason else "success",
            summary=answer,
            degraded_reason=degraded_reason,
        )

    async def _synthesize(
        self,
        stage_ctx: StageContext,
        context: AgentContext,
    ) -> tuple[str, str | None]:
        """Combine all stage results into a final answer.

        Returns ``(answer, degraded_reason)``. ``degraded_reason`` is ``None``
        on success and a short user-facing string when synthesis had to fall
        back (LLM call failed) so the caller can flag the response as degraded.
        """
        parts: list[str] = [
            f"Original question: {stage_ctx.plan.question}\n",
        ]
        for stage in stage_ctx.plan.stages:
            sr = stage_ctx.get_result(stage.stage_id)
            if not sr:
                continue
            parts.append(f"Stage '{stage.stage_id}' ({stage.description}):")
            parts.append(f"  Status: {sr.status}")
            if sr.query:
                parts.append(f"  SQL: {sr.query}")
            if sr.query_result:
                parts.append(f"  Columns: {sr.query_result.columns}")
                parts.append(f"  Rows: {sr.query_result.row_count}")
                if sr.query_result.rows:
                    parts.append(f"  Data sample: {sr.query_result.rows[:10]}")
            if sr.summary:
                parts.append(f"  Summary: {sr.summary}")
            parts.append("")

        for fb in stage_ctx.user_feedback:
            fb_stage = fb.get("stage_id")
            fb_text = fb.get("feedback_text", "")
            parts.append(f"User feedback (stage {fb_stage}): {fb_text}")

        synthesis_system = (
            "You are a data analyst. Synthesise the stage results below into "
            "a clear, complete answer. Include a summary table if the user "
            "requested one. Provide analytical commentary where appropriate. "
            "When stage SQL totals reconcile, do NOT claim an earlier query was "
            "wrong or under-counted without a numeric mismatch. "
            "Reason internally in English, but write the final answer in the "
            "SAME language as the original question."
        )
        if self._staleness_warning:
            synthesis_system = (
                f"KNOWLEDGE FRESHNESS WARNINGS:\n{self._staleness_warning}\n\n" + synthesis_system
            )

        messages = [
            Message(role="system", content=synthesis_system),
            Message(role="user", content="\n".join(parts)),
        ]
        try:
            resp = await llm_call_with_retry(
                self._llm,
                messages=messages,
                tools=None,
                preferred_provider=context.preferred_provider,
                model=context.model,
                component="synthesis_stage",
            )
            return resp.content or "", None
        except Exception as exc:
            logger.exception("Synthesis LLM call failed")
            lines = []
            for s in stage_ctx.plan.stages:
                sr = stage_ctx.get_result(s.stage_id)
                lines.append(f"Stage {s.stage_id}: {sr.summary if sr else 'N/A'}")
            fallback = (
                "Pipeline completed all stages but the final synthesis step failed. "
                "Showing per-stage results:\n" + "\n".join(lines)
            )
            return fallback, _stage_error_message(exc)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _summarize_query_result(query: str | None, qr: QueryResult | None) -> str:
        if not qr:
            return "No results."
        parts = []
        if query:
            parts.append(f"Query: {query}")
        parts.append(f"Columns: {qr.columns}")
        parts.append(f"Rows returned: {qr.row_count}")
        if qr.rows:
            parts.append(f"Sample (first 5): {qr.rows[:5]}")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # SSE event emitters
    # ------------------------------------------------------------------

    async def _emit_plan(self, wf_id: str, plan: ExecutionPlan) -> None:
        await self._tracker.emit(
            wf_id,
            "plan",
            "started",
            f"Execution plan with {len(plan.stages)} stages",
            stages=[
                {
                    "id": s.stage_id,
                    "description": s.description,
                    "tool": s.tool,
                    "checkpoint": s.checkpoint,
                }
                for s in plan.stages
            ],
        )

    async def _emit_stage_start(self, wf_id: str, stage: PlanStage, idx: int, total: int) -> None:
        await self._tracker.emit(
            wf_id,
            "stage_start",
            "started",
            stage.description,
            stage_id=stage.stage_id,
            index=idx,
            total=total,
        )

    async def _emit_stage_result(self, wf_id: str, stage: PlanStage, result: StageResult) -> None:
        # ``status`` is delivered as the positional ``status`` arg of ``emit`` (and
        # surfaced as the top-level ``WorkflowEvent.status``); never put it in
        # ``extra`` too, or ``**extra`` collides with the positional parameter.
        extra: dict[str, Any] = {
            "stage_id": stage.stage_id,
        }
        if result.query_result:
            extra["row_count"] = result.query_result.row_count
            extra["columns"] = result.query_result.columns
            extra["sample_rows"] = result.query_result.rows[:5]
        await self._tracker.emit(
            wf_id, "stage_result", result.status, result.summary[:200], **extra
        )

    async def _emit_stage_validation(
        self, wf_id: str, stage: PlanStage, validation: StageValidationOutcome
    ) -> None:
        await self._tracker.emit(
            wf_id,
            "stage_validation",
            "passed" if validation.passed else "failed",
            validation.error_summary or "OK",
            stage_id=stage.stage_id,
            passed=validation.passed,
            warnings=validation.warnings,
            errors=validation.errors,
        )

    async def _emit_stage_complete(
        self, wf_id: str, stage: PlanStage, result: StageResult, idx: int
    ) -> None:
        await self._tracker.emit(
            wf_id,
            "stage_complete",
            "completed",
            f"Stage {idx + 1} complete",
            stage_id=stage.stage_id,
            index=idx,
        )

    async def _emit_data_gate(self, wf_id: str, stage: PlanStage, outcome: DataGateOutcome) -> None:
        await self._tracker.emit(
            wf_id,
            "data_gate",
            "passed" if outcome.passed else "failed",
            outcome.error_summary
            or ("warnings: " + "; ".join(outcome.warnings) if outcome.warnings else "OK"),
            span_type="validation",
            stage_id=stage.stage_id,
            passed=outcome.passed,
            warnings=outcome.warnings,
            errors=outcome.errors,
            suggestions=outcome.suggestions,
        )
        if outcome.errors:
            # Hard data-gate block → catalog it so the logs/errors screen surfaces it.
            try:
                from app.models.base import async_session_factory
                from app.services.error_log_service import ErrorLogService

                owner = self._tracker.get_owner(wf_id)
                async with async_session_factory() as db:
                    await ErrorLogService().upsert_validation_failure(
                        db,
                        project_id=owner.get("project_id") or None,
                        kind="data_gate",
                        message=outcome.error_summary,
                        sample_ref=wf_id,
                    )
            except Exception:  # noqa: BLE001 — observability must never break the stage
                logger.debug("data_gate error_log upsert failed", exc_info=True)

    async def _emit_checkpoint(self, wf_id: str, stage: PlanStage, result: StageResult) -> None:
        preview: dict[str, Any] = {"stage_id": stage.stage_id}
        if result.query_result:
            preview["columns"] = result.query_result.columns
            preview["row_count"] = result.query_result.row_count
            preview["sample_rows"] = result.query_result.rows[:10]
        preview["summary"] = result.summary

        await self._tracker.emit(
            wf_id,
            "checkpoint",
            "waiting",
            f"Checkpoint: {stage.description}",
            **preview,
        )


# ------------------------------------------------------------------
# Result container
# ------------------------------------------------------------------


class _StageExecutorResult:
    """Returned by ``StageExecutor.execute()``."""

    def __init__(
        self,
        *,
        status: str,
        stage_ctx: StageContext,
        final_answer: str = "",
        checkpoint_stage: PlanStage | None = None,
        checkpoint_result: StageResult | None = None,
        failed_stage: PlanStage | None = None,
        failed_validation: StageValidationOutcome | None = None,
        data_gate_outcome: DataGateOutcome | None = None,
        replan_eligible: bool = True,
    ) -> None:
        self.status = status  # completed | checkpoint | stage_failed
        self.stage_ctx = stage_ctx
        self.final_answer = final_answer
        self.checkpoint_stage = checkpoint_stage
        self.checkpoint_result = checkpoint_result
        self.failed_stage = failed_stage
        self.failed_validation = failed_validation
        self.data_gate_outcome = data_gate_outcome
        self.replan_eligible = replan_eligible
