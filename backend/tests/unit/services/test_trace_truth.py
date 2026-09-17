"""PRJ-04: every request leaves exactly one trace row, and the row says what happened.

Production, measured 2026-09-17 before this change:

* **242 rows for 177 workflows** — two writers (the buffer flush at ``pipeline_end``
  and the chat route's ``finalize_trace``) raced a ``SELECT … LIMIT 1``;
* **10 of 12 failed traces** in 30 days with ``route='unknown'`` — routing reached the
  trace only through a response, and a crash or timeout has none;
* **26 ``Stale: …`` rows**, one on a run later reported completed — the buffer was
  evicted at 300 s, below every transport ceiling a live request runs under;
* REST timeouts finalized under ``unknown-{session}``, 44 characters for a
  ``String(36)`` column, so the row was refused and the failure went unrecorded.

These tests run the real service against a real SQLite database: the defects were
all in how two writes interleave, which a mocked session cannot show.
"""

from __future__ import annotations

import asyncio
import time
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core import failure_kind as fk
from app.core.trace_meta import TraceMeta
from app.core.workflow_tracker import WorkflowEvent
from app.models.base import Base
from app.models.request_trace import RequestTrace, TraceSpan
from app.services import trace_persistence_service as tps

PROJECT = "p" * 36
USER = "u" * 36


@pytest.fixture()
async def session_factory(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'traces.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[RequestTrace.__table__, TraceSpan.__table__],
        )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(tps, "async_session_factory", factory)
    yield factory
    await engine.dispose()


@pytest.fixture()
def service():
    tracker = type("T", (), {"_external_rebroadcast": False})()
    return tps.TracePersistenceService(tracker)  # type: ignore[arg-type]


def _event(wf: str, step: str, status: str = "completed", detail: str = "", **extra):
    return WorkflowEvent(
        workflow_id=wf, step=step, status=status, detail=detail, pipeline="agent", extra=extra
    )


async def _run_workflow(service, wf: str, *, end_status: str, end_detail: str = "", route=True):
    await service._on_event(
        _event(wf, "pipeline_start", "started", project_id=PROJECT, user_id=USER, question="q?")
    )
    if route:
        await service._on_event(
            _event(
                wf,
                "thinking",
                "in_progress",
                "Route: query (complex)",
                route="query",
                complexity="complex",
                estimated_queries=3,
            )
        )
    await service._on_event(_event(wf, "sql:llm_call", "completed", "llm", elapsed_ms=12.0))
    await service._on_event(_event(wf, "pipeline_end", end_status, end_detail))


async def _rows(factory, wf: str) -> list[RequestTrace]:
    async with factory() as s:
        return list(
            (await s.execute(sa.select(RequestTrace).where(RequestTrace.workflow_id == wf)))
            .scalars()
            .all()
        )


async def _span_count(factory, trace_id: str) -> int:
    async with factory() as s:
        return (
            await s.execute(
                sa.select(sa.func.count())
                .select_from(TraceSpan)
                .where(TraceSpan.trace_id == trace_id)
            )
        ).scalar_one()


def _finalize_kwargs(**over):
    kw = dict(
        project_id=PROJECT,
        user_id=USER,
        session_id=None,
        question="q?",
        response_type="text",
        status="completed",
        meta=TraceMeta(),
        total_tokens=120,
        llm_model="m",
        llm_provider="openrouter",
    )
    kw.update(over)
    return kw


async def test_flush_racing_finalize_leaves_one_row_carrying_both_halves(session_factory, service):
    """The race production lost 65 rows to: finalize called while the flush is in flight."""
    wf = str(uuid.uuid4())
    await _run_workflow(service, wf, end_status="completed")
    # No await between the end event and the finalize: the flush task has only
    # been scheduled. This is the ordering that duplicated rows.
    await service.finalize_trace(wf, **_finalize_kwargs())

    rows = await _rows(session_factory, wf)
    assert len(rows) == 1
    row = rows[0]
    assert row.total_tokens == 120, "finalize's half is on the row"
    assert row.total_duration_ms is not None, "the flush's half is on the row"
    assert (row.route, row.complexity, row.estimated_queries) == ("query", "complex", 3)
    assert await _span_count(session_factory, row.id) == 1


async def test_finalize_first_then_flush_fills_measurements_and_keeps_the_verdict(
    session_factory, service
):
    """A route can finalize before the flush exists; the flush must merge, not add."""
    wf = str(uuid.uuid4())
    await service.finalize_trace(
        wf, **_finalize_kwargs(status="failed", error_message="boom", response_type="error")
    )
    await _run_workflow(service, wf, end_status="failed", end_detail="LLMAllProvidersFailedError")
    await asyncio.gather(*service._persist_tasks)

    rows = await _rows(session_factory, wf)
    assert len(rows) == 1
    row = rows[0]
    assert (row.status, row.error_message) == ("failed", "boom"), "the caller's verdict stands"
    assert row.total_duration_ms is not None
    assert row.route == "query"
    assert row.failure_kind == fk.TRANSIENT
    assert await _span_count(session_factory, row.id) == 1


async def test_a_crashed_run_carries_its_routing_and_a_kind(session_factory, service):
    """No response ever reached `pop_routing`; the run's own events still name the route."""
    wf = str(uuid.uuid4())
    await _run_workflow(service, wf, end_status="failed", end_detail="LLMAllProvidersFailedError")
    await asyncio.gather(*service._persist_tasks)

    (row,) = await _rows(session_factory, wf)
    assert row.status == "failed"
    assert row.route == "query"
    assert row.failure_kind == fk.TRANSIENT


async def test_checkpoint_is_its_own_status(session_factory, service):
    wf = str(uuid.uuid4())
    await _run_workflow(service, wf, end_status="checkpoint", end_detail="Review the plan")
    await asyncio.gather(*service._persist_tasks)

    (row,) = await _rows(session_factory, wf)
    assert row.status == "checkpoint"
    assert row.failure_kind is None
    assert row.error_message is None


async def test_a_stale_eviction_is_provisional_and_a_completed_run_sheds_it(
    session_factory, service, monkeypatch
):
    """The eviction guesses; the chat route knows. A completed run never says `Stale`."""
    wf = str(uuid.uuid4())
    await service._on_event(
        _event(wf, "pipeline_start", "started", project_id=PROJECT, user_id=USER, question="q")
    )
    service._buffers[wf].started_at = time.time() - tps.stale_buffer_seconds() - 1

    real_sleep = asyncio.sleep
    calls = {"n": 0}

    async def one_sweep(_seconds):
        calls["n"] += 1
        if calls["n"] > 1:
            raise asyncio.CancelledError
        await real_sleep(0)

    monkeypatch.setattr(tps.asyncio, "sleep", one_sweep)
    with pytest.raises(asyncio.CancelledError):
        await service._cleanup_stale_buffers()

    (row,) = await _rows(session_factory, wf)
    assert row.status == tps.PROVISIONAL_STATUS
    assert row.failure_kind is None
    assert row.error_message == tps.STALE_DETAIL

    await service.finalize_trace(wf, **_finalize_kwargs())
    (row,) = await _rows(session_factory, wf)
    assert row.status == "completed"
    assert row.error_message is None
    assert row.failure_kind is None


async def test_workflow_id_is_unique_in_the_schema(session_factory):
    async with session_factory() as s:
        s.add(RequestTrace(project_id=PROJECT, user_id=USER, workflow_id="w" * 36))
        await s.commit()
        s.add(RequestTrace(project_id=PROJECT, user_id=USER, workflow_id="w" * 36))
        with pytest.raises(sa.exc.IntegrityError):
            await s.commit()


def test_the_buffer_outlives_every_transport_ceiling():
    from app.config import settings

    horizon = tps.stale_buffer_seconds()
    assert horizon > settings.stream_timeout_seconds
    assert horizon > settings.ws_event_relay_timeout_seconds
    assert horizon > settings.agent_wall_clock_timeout_seconds * 1.2


def test_routing_is_the_first_verdict_not_the_last():
    """ORCH-07: a pipeline→loop bounce re-enters with a synthetic route."""
    events = [
        _event("w", "thinking", route="query", complexity="complex", estimated_queries=4),
        _event("w", "thinking", route="explore", complexity="moderate", estimated_queries=2),
    ]
    assert tps.routing_from_events(events) == ("query", "complex", 4)
    assert tps.routing_from_events([_event("w", "thinking")]) is None


@pytest.mark.parametrize(
    ("detail", "kind"),
    [
        ("LLMAllProvidersFailedError", fk.TRANSIENT),
        ("WallClockExceeded", fk.TRANSIENT),
        ("Request timed out", fk.TRANSIENT),
        ("LLMAuthError", fk.CONFIGURATION),
        ("Daily token budget exceeded", fk.CONFIGURATION),
        ("AgentFatalError", fk.FATAL),
        ("pipeline_end never emitted", fk.FATAL),
        ("", fk.FATAL),
        (None, fk.FATAL),
    ],
)
def test_terminal_details_classify_into_the_shared_vocabulary(detail, kind):
    assert fk.kind_for_terminal_detail(detail) == kind


async def test_the_agent_tells_the_caller_its_workflow_id_even_when_it_crashes():
    """A timed-out REST run has no response; the caller's own dict must hold the id."""
    from unittest.mock import AsyncMock, MagicMock

    from app.api.routes.chat import _abnormal_trace_id
    from app.core.agent import ConversationalAgent

    agent = ConversationalAgent.__new__(ConversationalAgent)
    tracker = MagicMock()
    tracker.begin = AsyncMock(return_value="wf-" + "1" * 33)
    tracker.has_ended = MagicMock(return_value=True)
    agent._tracker = tracker
    agent._orchestrator = MagicMock()
    agent._orchestrator._llm = MagicMock()
    agent._orchestrator.run = AsyncMock(side_effect=RuntimeError("boom"))

    extra: dict = {"session_id": "s"}
    with pytest.raises(RuntimeError):
        await agent.run(question="q", project_id=PROJECT, extra=extra)

    assert extra["_workflow_id"] == "wf-" + "1" * 33
    assert _abnormal_trace_id("s" * 36, "timeout", extra) == "wf-" + "1" * 33
    fallback = _abnormal_trace_id("s" * 36, "timeout", {})
    assert len(fallback) == 36, "a fallback id must fit the column it is written to"


async def test_the_orchestrator_emits_its_route_once_on_the_event_stream():
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.agents.base import AgentContext
    from app.agents.orchestrator import OrchestratorAgent
    from app.agents.router import RouteResult
    from app.core.workflow_tracker import WorkflowTracker
    from app.llm.base import LLMResponse

    tracker = MagicMock(spec=WorkflowTracker)
    tracker.begin = AsyncMock(return_value="wf-test")
    tracker.end = AsyncMock()
    tracker.emit = AsyncMock()
    tracker.has_ended = MagicMock(return_value=False)

    @asynccontextmanager
    async def fake_step(wf_id, step, detail="", **kwargs):
        yield

    tracker.step = MagicMock(side_effect=fake_step)
    llm = MagicMock()
    llm.complete = AsyncMock(return_value=LLMResponse(content="42."))
    llm.get_context_window = MagicMock(return_value=128_000)
    llm._sink = None
    vs = MagicMock()
    vs.get_or_create_collection = MagicMock(return_value=MagicMock(count=MagicMock(return_value=0)))
    orch = OrchestratorAgent(llm_router=llm, vector_store=vs, workflow_tracker=tracker)
    ctx = AgentContext(
        project_id="proj-1",
        connection_config=None,
        user_question="How many users?",
        chat_history=[],
        llm_router=llm,
        tracker=tracker,
        workflow_id="wf-test",
    )
    route = RouteResult(
        route="query",
        complexity="complex",
        approach="x",
        estimated_queries=4,
        needs_multiple_data_sources=False,
    )
    loader = orch._ctx_loader
    with (
        patch("app.agents.orchestrator.route_request", new=AsyncMock(return_value=route)),
        patch.object(loader, "has_knowledge_base", return_value=False),
        patch.object(loader, "has_mcp_sources", new=AsyncMock(return_value=False)),
        patch.object(loader, "has_repo", return_value=False),
        patch.object(loader, "check_staleness", new=AsyncMock(return_value=None)),
        patch.object(loader, "load_project_overview", new=AsyncMock(return_value=None)),
        patch.object(loader, "load_recent_learnings", new=AsyncMock(return_value="")),
        patch.object(loader, "load_relevant_insights", new=AsyncMock(return_value="")),
    ):
        await orch.run(ctx)

    routed = [c for c in tracker.emit.await_args_list if "route" in c.kwargs]
    assert len(routed) == 1
    assert (
        routed[0].kwargs["route"],
        routed[0].kwargs["complexity"],
        routed[0].kwargs["estimated_queries"],
    ) == ("query", "complex", 4)


def test_the_migration_merges_duplicates_into_the_row_with_spans(tmp_path):
    """Production's 65 duplicates: each half has what the other lacks, so merge, not drop."""
    import importlib.util
    from pathlib import Path

    path = next(
        Path(__file__)
        .resolve()
        .parents[3]
        .glob("alembic/versions/d6e7f8a9b0c1_request_traces_one_row_per_workflow.py")
    )
    spec = importlib.util.spec_from_file_location("mig_d6e7", path)
    assert spec and spec.loader
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'mig.db'}")
    traces = RequestTrace.__table__
    spans = TraceSpan.__table__
    with engine.begin() as conn:
        # The pre-migration shape: workflow_id NOT unique.
        meta = sa.MetaData()
        columns = [c._copy() for c in traces.columns]
        for col in columns:
            col.unique = False
            col.index = False
        loose = sa.Table("request_traces", meta, *columns)
        meta.create_all(conn)
        spans.metadata.create_all(conn, tables=[spans])
        wf = "w" * 36
        from datetime import UTC, datetime, timedelta

        t0 = datetime(2026, 9, 1, tzinfo=UTC)
        conn.execute(
            loose.insert().values(
                id="flush",
                project_id=PROJECT,
                user_id=USER,
                workflow_id=wf,
                status="failed",
                error_message="Stale: pipeline_end never received",
                total_duration_ms=305_000.0,
                created_at=t0,
            )
        )
        conn.execute(
            loose.insert().values(
                id="final",
                project_id=PROJECT,
                user_id=USER,
                workflow_id=wf,
                status="completed",
                session_id="s" * 36,
                total_tokens=900,
                route="query",
                response_type="sql_result",
                created_at=t0 + timedelta(seconds=1),
            )
        )
        conn.execute(
            spans.insert(),
            [
                {"id": f"sp{i}", "trace_id": "flush", "span_type": "llm_call", "name": "x"}
                for i in range(3)
            ]
            + [{"id": "sp-final", "trace_id": "final", "span_type": "tool_call", "name": "y"}],
        )

        mig._merge_duplicates(conn)

        rows = conn.execute(sa.select(loose)).mappings().all()
        assert len(rows) == 1
        row = rows[0]
        assert row["id"] == "flush", "the row with the measured spans is kept"
        assert row["status"] == "completed"
        assert row["error_message"] is None, "a completed run does not say Stale"
        assert (row["session_id"], row["total_tokens"], row["route"]) == ("s" * 36, 900, "query")
        assert row["response_type"] == "sql_result"
        assert row["total_duration_ms"] == 305_000.0
        assert conn.execute(sa.select(sa.func.count()).select_from(spans)).scalar_one() == 3
