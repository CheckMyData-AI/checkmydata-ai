"""The plan a request actually executed must outlive the resume buffer (Ш0b · REQ-9/10).

`pipeline_runs.plan_json` is the only place a plan has ever been stored, and
`_cleanup_pipeline_runs()` (`main.py`) deletes rows older than
`pipeline_run_ttl_days = 7` **at start-up**. Measured 2026-09-03: the table held
zero rows, and my own deploy of v321 had swept the last four between two probes
half an hour apart.

That matters because the highest-yield procedure in the graph-engineering
doctrine — the fake-edge test, "does data from A actually enter B" — has to run
against plans that really executed. With Path B taking 14% of a traffic of ~17
messages a month, seven days is routinely zero plans. The decision about the
shape of the work would be made without a single example of the shape.

So the plan travels to `RequestTrace`, which `cleanup_old_traces` keeps for 90
days. **`pipeline_run_ttl_days` is deliberately NOT raised**, and a test pins
that: the buffer is resume state, the trace is history, and one number serving
both roles is how a pipeline three months stale becomes resumable.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.core.trace_meta import TraceMeta
from app.models.base import Base


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    s = sm()
    try:
        yield s
    finally:
        await s.close()
        await engine.dispose()


_PLAN = '{"plan_id":"p1","stages":[{"stage_id":"a","tool":"query_database","depends_on":[]}]}'


class TestTheColumnExists:
    async def test_a_trace_can_store_the_plan_it_executed(self, session):
        from app.models.request_trace import RequestTrace

        session.add(
            RequestTrace(
                id="t1",
                workflow_id="wf1",
                project_id="p",
                user_id="u",
                question="q",
                plan_json=_PLAN,
            )
        )
        await session.commit()

        from sqlalchemy import select

        row = (await session.execute(select(RequestTrace))).scalar_one()
        assert row.plan_json == _PLAN

    async def test_it_is_nullable_because_most_requests_have_no_plan(self, session):
        """Path B took 14% of requests. A NOT NULL column would make the other
        86% store `{}`, which reads as "an empty plan ran"."""
        from sqlalchemy import select

        from app.models.request_trace import RequestTrace

        session.add(
            RequestTrace(id="t2", workflow_id="wf2", project_id="p", user_id="u", question="q")
        )
        await session.commit()
        row = (await session.execute(select(RequestTrace))).scalar_one()
        assert row.plan_json is None


class TestItTravelsOnTheRecord:
    def test_trace_meta_carries_it(self):
        assert "plan_json" in {f.name for f in TraceMeta.__dataclass_fields__.values()}

    def test_from_response_reads_it_off_the_response(self):
        meta = TraceMeta.from_response(SimpleNamespace(route="explore", plan_json=_PLAN))
        assert meta.plan_json == _PLAN

    def test_a_request_with_no_plan_carries_none_not_an_empty_object(self):
        """`{}` would be a claim that an empty plan executed."""
        assert TraceMeta.from_response(SimpleNamespace(route="explore")).plan_json is None
        assert TraceMeta.utility().plan_json is None
        assert TraceMeta.aborted("fatal").plan_json is None

    def test_the_orchestrator_exposes_the_plan_for_draining(self):
        """Same shape as `pop_routing`: the orchestrator has many exit points and
        `replace(context, …)` gives the caller a copy, so a drain is the only way
        out that does not mutate a shared context."""
        from app.agents.orchestrator import OrchestratorAgent

        assert hasattr(OrchestratorAgent, "pop_plan_json")

    def test_the_response_carries_it(self):
        from app.agents.orchestrator import AgentResponse

        assert "plan_json" in {f.name for f in AgentResponse.__dataclass_fields__.values()}


class TestItReachesTheRow:
    async def test_finalize_trace_writes_the_plan(self, monkeypatch):
        """A field on the record is not a column in the table. Asserted on the
        emitted statement, the way its neighbour in
        `test_trace_finalization_failure_kind.py` is — that test's own docstring
        records a source-reading version letting a planted defect through.
        """
        from unittest.mock import MagicMock

        from app.models.request_trace import RequestTrace
        from app.services import trace_persistence_service as tps

        captured: dict = {}

        class _Result:
            def scalar_one_or_none(self):
                return RequestTrace(id="t1", workflow_id="wf1", project_id="p", user_id="u")

        class _Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_a):
                return False

            async def execute(self, stmt):
                if stmt.__class__.__name__ == "Update":
                    captured["values"] = {
                        c.name: getattr(v, "value", v) for c, v in stmt._values.items()
                    }
                return _Result()

            async def commit(self):
                return None

        monkeypatch.setattr(tps, "async_session_factory", lambda: _Session())
        svc = tps.TracePersistenceService(tracker=MagicMock())
        await svc.finalize_trace(
            "wf1",
            project_id="p",
            user_id="u",
            meta=TraceMeta.from_response(SimpleNamespace(route="explore", plan_json=_PLAN)),
        )
        assert captured["values"]["plan_json"] == _PLAN


class TestTheTwoRolesStaySeparate:
    def test_the_resume_buffer_ttl_is_unchanged(self):
        """The buffer is resume state; the trace is history. Raising this to keep
        plans for analysis would make a pipeline three months stale resumable —
        one number serving two roles, which is the defect, not the fix."""
        from app.config import settings

        assert settings.pipeline_run_ttl_days == 7, (
            "raise this only for a resume reason. Plans for analysis live on the "
            "trace now (Ш0b · REQ-9)"
        )

    def test_the_cleanup_still_deletes_pipeline_runs(self):
        """A reader might assume the plan moving means the sweep was dropped. It
        was not: leaving resume state forever is its own defect."""
        from app import main

        src = Path(inspect.getfile(main)).read_text(encoding="utf-8")
        assert "delete(PipelineRun)" in src

    def test_traces_are_kept_far_longer_than_the_buffer(self):
        """The whole point: the plan must survive long enough to be analysed."""
        from app.config import settings
        from app.services.trace_persistence_service import TracePersistenceService

        sig = inspect.signature(TracePersistenceService.cleanup_old_traces)
        assert sig.parameters["retention_days"].default > settings.pipeline_run_ttl_days
