"""PRJ-03 remainder (T02b): the request deadline reaches the pipeline, and nothing eats it.

T02 bounded the flat tool loop. Three gaps stayed open, each measured in the audit:

* **O-05** — a pipeline batch was checked against the deadline only BETWEEN batches, so
  one SQL stage whose agent retries, or three parallel stages, ran past the limit by its
  whole duration;
* **O-08** — viz and ``localize`` caught ``CancelledError``, so a request cancelled by
  its deadline (or by REST's ``wait_for``) swallowed the cancellation and kept running;
* **O-07** — the per-workflow cache sweep evicted anything first seen 300 s ago, below
  every transport ceiling, so a live request lost its SQL results mid-answer.
"""

from __future__ import annotations

import ast
import asyncio
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.base import AgentContext
from app.agents.request_clock import _REQUEST_START_KEY
from app.agents.stage_context import ExecutionPlan, PlanStage
from app.agents.stage_executor import StageExecutor
from app.core.request_lifetime import longest_request_seconds
from app.core.workflow_tracker import WorkflowTracker

APP = Path(__file__).resolve().parents[3] / "app"


def _tracker() -> WorkflowTracker:
    t = MagicMock(spec=WorkflowTracker)
    t.emit = AsyncMock()
    t.step = MagicMock()
    t.step.return_value.__aenter__ = AsyncMock(return_value=None)
    t.step.return_value.__aexit__ = AsyncMock(return_value=False)
    return t


def _context(limit_spent_fraction: float, limit: float) -> AgentContext:
    ctx = AgentContext(
        project_id="p",
        connection_config=None,
        user_question="q",
        chat_history=[],
        llm_router=MagicMock(),
        tracker=_tracker(),
        workflow_id="wf-1",
    )
    # The request began long enough ago that only a sliver of the hard limit is left.
    ctx.extra[_REQUEST_START_KEY] = time.monotonic() - limit * 1.2 * limit_spent_fraction
    return ctx


def _stage(stage_id: str) -> PlanStage:
    return PlanStage(stage_id=stage_id, description="s", tool="query_database", max_retries=0)


@pytest.mark.parametrize("n_parallel", [1, 3])
async def test_a_hanging_batch_is_cut_at_the_hard_deadline(monkeypatch, n_parallel):
    from app.config import settings

    limit = 2.0
    monkeypatch.setattr(settings, "pipeline_max_wall_seconds", limit)
    monkeypatch.setattr(settings, "pipeline_max_parallel_stages", 3)
    executor = StageExecutor(
        sql_agent=MagicMock(),
        knowledge_agent=MagicMock(),
        llm_router=MagicMock(),
        tracker=_tracker(),
    )
    cancelled: list[str] = []

    async def hang(stage, *_a: Any, **_kw: Any):
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.append(stage.stage_id)
            raise

    monkeypatch.setattr(executor, "_process_one_stage", hang)
    plan = ExecutionPlan(
        plan_id="p", question="q", stages=[_stage(f"s{i}") for i in range(n_parallel)]
    )
    ctx = _context(limit_spent_fraction=0.5, limit=limit)  # ~1.2 s of hard budget left

    started = time.monotonic()
    # An outer bound of its own, so a regression FAILS here instead of hanging the suite.
    result = await asyncio.wait_for(
        executor.execute(plan, ctx, deadline=time.monotonic() + 3600), timeout=10
    )
    elapsed = time.monotonic() - started

    assert elapsed < 3.0, f"the batch ran {elapsed:.1f}s past a ~1.2s remaining budget"
    assert result.status == "stage_failed"
    assert result.replan_eligible is False, "a spent budget must not buy a replan"
    assert sorted(cancelled) == [f"s{i}" for i in range(n_parallel)], "every stage is cancelled"


async def test_localize_lets_a_cancellation_through():
    """REST's `wait_for` cancels the run; a translator that swallows it keeps it alive."""
    from app.agents.localize import localize

    llm = MagicMock()

    async def hang(*_a: Any, **_kw: Any):
        await asyncio.sleep(3600)

    llm.complete = hang
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(
            localize("Request timed out", "Сколько было заказов?", llm, timeout=60), 0.2
        )


def test_no_agent_handler_swallows_cancellation():
    """Structural: any `except` naming `CancelledError` in the agents must re-raise.

    Checked on the parse tree, not the text, so a reformatted handler cannot slip past.
    Verified by restoring the viz handler's `(Exception, asyncio.CancelledError)`.
    """
    offenders: list[str] = []
    for path in sorted((APP / "agents").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler) or node.type is None:
                continue
            names = {
                n.attr if isinstance(n, ast.Attribute) else getattr(n, "id", "")
                for n in ast.walk(node.type)
            }
            if "CancelledError" not in names:
                continue
            if not any(isinstance(n, ast.Raise) for n in ast.walk(node)):
                offenders.append(f"{path.relative_to(APP)}:{node.lineno}")
    assert offenders == [], f"handlers that swallow a cancellation: {offenders}"


def test_the_cache_sweep_spares_a_request_that_is_merely_slow():
    """O-07: a request first seen 301 s ago is live; only one past every ceiling is gone."""
    from app.agents.orchestrator import OrchestratorAgent

    orch = OrchestratorAgent.__new__(OrchestratorAgent)
    now = time.time()
    orch._wf_seen = {"slow": now - 301, "gone": now - longest_request_seconds() - 1}
    orch._wf_enriched = {}
    orch._wf_sql_results = {"slow": ["rows"], "gone": ["rows"]}
    orch._wf_correction_counts = {}
    orch._wf_suspicious = {}
    orch._wf_routing = {"slow": ("query", "simple", 1)}
    orch._wf_plan = {}

    orch._cleanup_stale_results(longest_request_seconds())

    assert "slow" in orch._wf_sql_results and "slow" in orch._wf_routing
    assert "gone" not in orch._wf_sql_results


def test_the_orchestrator_sweeps_on_the_derived_horizon_not_a_typed_one():
    source = (APP / "agents" / "orchestrator.py").read_text(encoding="utf-8")
    assert "self._cleanup_stale_results(longest_request_seconds())" in source
    assert "stale_seconds = 300" not in source


def test_the_lifetime_outlives_every_ceiling():
    from app.config import settings

    horizon = longest_request_seconds()
    assert horizon > settings.stream_timeout_seconds
    assert horizon > settings.ws_event_relay_timeout_seconds
    assert horizon > settings.agent_wall_clock_timeout_seconds * 1.2
