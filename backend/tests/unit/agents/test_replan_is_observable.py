"""Replanning must leave a trace, not only a counter (Ш0b · REQ-6).

`MetricsCollector` counts `orchestrator_replans_total` and holds it in the
process. `/api/metrics` serves it, and every dyno restart resets it — a deploy,
a reap, a scale event. Measured 2026-09-03 over the whole production history:
**48 distinct span names and not one matching `replan`.** The nearest was
`stage_retry`, five occurrences.

So *"how often does the pipeline replan, and does replanning help?"* was
unanswerable over history, while replanning is one of the mechanisms the
pipeline's claimed reliability rests on. A counter that survives nothing cannot
answer a question about the past.

The fix is a span, not a column: a span says *when* and *against which failed
stage*, which is what makes the second half of the question ("does it help")
answerable at all. `RequestTrace` already stores spans and keeps them for the
trace's 90-day retention.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.workflow_tracker import WorkflowTracker


class _StepRecorder:
    """Records every `tracker.step(...)` opened, with its arguments."""

    def __init__(self) -> None:
        self.steps: list[dict[str, Any]] = []

    def build(self) -> MagicMock:
        t = MagicMock(spec=WorkflowTracker)
        t.emit = AsyncMock()
        t.end = AsyncMock()
        t.has_ended = MagicMock(return_value=False)

        recorder = self

        @asynccontextmanager
        async def _step(wf_id: str, name: str, detail: str = "", **kwargs: Any):
            recorder.steps.append({"name": name, "detail": detail, **kwargs})
            yield

        t.step = MagicMock(side_effect=_step)
        return t

    def named(self, name: str) -> list[dict[str, Any]]:
        return [s for s in self.steps if s["name"] == name]


@pytest.fixture
def recorder() -> _StepRecorder:
    return _StepRecorder()


def _orch(tracker):
    from app.agents.orchestrator import OrchestratorAgent

    llm = MagicMock()
    llm.complete = AsyncMock()
    llm.get_context_window = MagicMock(return_value=128_000)
    vs = MagicMock()
    return OrchestratorAgent(llm_router=llm, vector_store=vs, workflow_tracker=tracker)


def _failed_exec_result(stage_id: str = "s1"):
    """A `stage_failed` outcome, the only input that starts a replan."""
    from app.agents.stage_context import ExecutionPlan, PlanStage, StageContext

    stage = PlanStage(stage_id=stage_id, description="d", tool="query_database")
    plan = ExecutionPlan(plan_id="p", question="q", stages=[stage])
    ctx = StageContext(plan=plan)
    return MagicMock(
        status="stage_failed",
        stage_ctx=ctx,
        failed_stage=stage,
        failed_validation=MagicMock(errors=["boom"]),
        replan_eligible=True,
        data_gate_outcome=None,
    )


class TestTheReplanIsVisible:
    @pytest.mark.asyncio
    async def test_a_replan_opens_a_named_span(self, recorder):
        """Not `emit` — a step. An emit is a feed line; a step becomes a row."""
        from app.agents.base import AgentContext
        from app.connectors.base import ConnectionConfig

        tracker = recorder.build()
        orch = _orch(tracker)
        adaptive = MagicMock()
        adaptive.replan = AsyncMock(return_value=None)  # give up after one attempt

        ctx = AgentContext(
            project_id="p",
            connection_config=ConnectionConfig(db_type="postgres"),
            user_question="q",
            chat_history=[],
            llm_router=orch._llm,
            tracker=tracker,
            workflow_id="wf-1",
        )

        await orch._run_pipeline_replans(
            executor=MagicMock(),
            exec_result=_failed_exec_result(),
            pipeline_ctx=ctx,
            context=ctx,
            adaptive=adaptive,
            table_map="",
            db_type="postgres",
            staleness_warning=None,
            run_id="r1",
            wf_id="wf-1",
        )

        spans = recorder.named("orchestrator:replan")
        opened = sorted({s["name"] for s in recorder.steps})
        assert spans, (
            "a replan must open a span; production carried 48 distinct span "
            f"names and none matched 'replan'. Opened here: {opened}"
        )

    @pytest.mark.asyncio
    async def test_the_span_names_the_attempt_and_the_failed_stage(self, recorder):
        """ "Did it help?" needs to know which failure each attempt answered."""
        from app.agents.base import AgentContext
        from app.connectors.base import ConnectionConfig

        tracker = recorder.build()
        orch = _orch(tracker)
        adaptive = MagicMock()
        adaptive.replan = AsyncMock(return_value=None)

        ctx = AgentContext(
            project_id="p",
            connection_config=ConnectionConfig(db_type="postgres"),
            user_question="q",
            chat_history=[],
            llm_router=orch._llm,
            tracker=tracker,
            workflow_id="wf-1",
        )
        await orch._run_pipeline_replans(
            executor=MagicMock(),
            exec_result=_failed_exec_result("find_renewals"),
            pipeline_ctx=ctx,
            context=ctx,
            adaptive=adaptive,
            table_map="",
            db_type="postgres",
            staleness_warning=None,
            run_id="r1",
            wf_id="wf-1",
        )

        span = recorder.named("orchestrator:replan")[0]
        blob = f"{span.get('detail', '')} {span.get('step_data', {})}"
        assert "find_renewals" in blob, f"the failed stage must be named; got {span}"
        assert "1" in blob, f"the attempt number must be recorded; got {span}"

    @pytest.mark.asyncio
    async def test_it_is_classified_as_an_llm_call(self, recorder):
        """`adaptive.replan` calls the model, so the span type is not cosmetic —
        it is what makes the replan show up in the llm_call cost breakdown."""
        from app.agents.base import AgentContext
        from app.connectors.base import ConnectionConfig

        tracker = recorder.build()
        orch = _orch(tracker)
        adaptive = MagicMock()
        adaptive.replan = AsyncMock(return_value=None)

        ctx = AgentContext(
            project_id="p",
            connection_config=ConnectionConfig(db_type="postgres"),
            user_question="q",
            chat_history=[],
            llm_router=orch._llm,
            tracker=tracker,
            workflow_id="wf-1",
        )
        await orch._run_pipeline_replans(
            executor=MagicMock(),
            exec_result=_failed_exec_result(),
            pipeline_ctx=ctx,
            context=ctx,
            adaptive=adaptive,
            table_map="",
            db_type="postgres",
            staleness_warning=None,
            run_id="r1",
            wf_id="wf-1",
        )
        assert recorder.named("orchestrator:replan")[0].get("span_type") == "llm_call"


class TestTheCounterIsStillThere:
    def test_the_in_memory_counter_was_not_removed(self):
        """The span answers questions about the past; the counter answers
        "what is happening now" on the Prometheus endpoint. Adding one is not a
        reason to drop the other, and a reader of this change might assume it was.
        """
        from pathlib import Path

        src = Path("app/core/metrics.py").read_text(encoding="utf-8")
        assert "orchestrator_replans_total" in src
