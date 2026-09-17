"""A multi-stage question with no chat session runs instead of failing (V1 finding).

Production, 2026-09-17 11:52 (`c8d6726d`): an MCP `query_database` call planned a
pipeline, `_create_pipeline_run` inserted `pipeline_runs.session_id = ""`, the
foreign key to `chat_sessions` refused it, and `_run_complex_pipeline` raised
`AgentFatalError("Pipeline initialisation failed")`. MCP requests never carry a
session, so every multi-stage question over MCP failed before its first stage.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.agents.base import AgentContext
from app.agents.orchestrator import OrchestratorAgent
from app.agents.stage_context import ExecutionPlan, PlanStage


def _ctx(extra: dict) -> AgentContext:
    return AgentContext(
        project_id="p",
        connection_config=None,
        user_question="q",
        chat_history=[],
        llm_router=MagicMock(),
        tracker=MagicMock(),
        workflow_id="wf-1",
        extra=extra,
    )


def _plan() -> ExecutionPlan:
    return ExecutionPlan(
        plan_id="p",
        question="q",
        stages=[
            PlanStage(stage_id="a", description="a", tool="query_database"),
            PlanStage(stage_id="b", description="b", tool="query_database", checkpoint=True),
        ],
    )


@pytest.mark.parametrize("extra", [{}, {"session_id": ""}, {"session_id": None}])
async def test_no_session_means_no_resume_record_and_no_database_write(monkeypatch, extra):
    import app.models.base as base

    def refuse():
        raise AssertionError("a session-less run must not touch pipeline_runs")

    monkeypatch.setattr(base, "async_session_factory", refuse)
    orch = OrchestratorAgent.__new__(OrchestratorAgent)
    plan = _plan()

    run = await orch._create_pipeline_run(_ctx(extra), plan)

    assert len(run.id) == 36, "the run still has an id the trace and response can carry"
    assert run.persisted is False
    assert not any(s.checkpoint for s in plan.stages), (
        "a pause no request can continue is a dead end, so it is removed"
    )


async def test_a_session_still_gets_its_resume_record(monkeypatch):
    import app.models.base as base

    added: list = []

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def add(self, obj):
            added.append(obj)

        async def commit(self):
            pass

        async def refresh(self, obj):
            pass

    monkeypatch.setattr(base, "async_session_factory", lambda: _Session())
    orch = OrchestratorAgent.__new__(OrchestratorAgent)
    plan = _plan()

    await orch._create_pipeline_run(_ctx({"session_id": "s" * 36}), plan)

    assert len(added) == 1 and added[0].session_id == "s" * 36
    assert plan.stages[1].checkpoint is True, "a chat session can resume, so it keeps its pause"
