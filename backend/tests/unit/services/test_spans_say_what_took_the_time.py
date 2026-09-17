"""PRJ-04 remainder (T03b): a span's type says what the time was spent on.

One production trace (2026-09-16, 337 s, 12 "DB queries", 11 LLM calls) read:

* ``sql:tool:execute_query`` **60 s** typed ``db_query`` around an ``execute_query`` of
  **22 s** — the envelope held a 20 s ``query_repair`` and the learning extraction, and
  both levels counted, so every query was two in ``total_db_queries``;
* ``query_repair`` **20 s** typed ``validation`` — an LLM call missing from
  ``total_llm_calls``;
* provider retries dropped from the trace entirely.

These tests drive the real flush over a real event sequence of that shape.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.workflow_tracker import WorkflowEvent
from app.models.base import Base
from app.models.request_trace import RequestTrace, TraceSpan
from app.services import trace_persistence_service as tps

PROJECT = "p" * 36
USER = "u" * 36


@pytest.fixture()
async def factory(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'spans.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all, tables=[RequestTrace.__table__, TraceSpan.__table__]
        )
    f = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(tps, "async_session_factory", f)
    yield f
    await engine.dispose()


def _evt(wf, step, status="completed", elapsed=None, span_type=None, **extra):
    return WorkflowEvent(
        workflow_id=wf,
        step=step,
        status=status,
        detail=step,
        pipeline="agent",
        extra=extra,
        elapsed_ms=elapsed,
        span_type=span_type,
    )


async def test_one_query_counts_once_and_its_repair_is_an_llm_call(factory):
    service = tps.TracePersistenceService(type("T", (), {"_external_rebroadcast": False})())
    wf = str(uuid.uuid4())
    events = [
        _evt(wf, "pipeline_start", "started", project_id=PROJECT, user_id=USER, question="q"),
        _evt(wf, "sql:llm_call", elapsed=3000.0, span_type="llm_call"),
        _evt(wf, "orchestrator:llm_retry", "retrying", span_type="llm_call", backoff_seconds=2.0),
        _evt(wf, "query_repair", elapsed=20000.0, span_type="llm_call"),
        _evt(wf, "execute_query", elapsed=22000.0, span_type="db_query"),
        _evt(wf, "sql:learning_analysis", elapsed=4000.0, span_type="llm_call"),
        _evt(wf, "sql:tool:execute_query", elapsed=60000.0, span_type="tool_call"),
        _evt(wf, "pipeline_end", "completed"),
    ]
    for e in events:
        await service._on_event(e)
    await asyncio.gather(*service._persist_tasks)

    async with factory() as s:
        trace = (await s.execute(sa.select(RequestTrace))).scalar_one()
        spans = {
            r.name: r.span_type for r in (await s.execute(sa.select(TraceSpan))).scalars().all()
        }
    assert trace.total_db_queries == 1, "the envelope must not count the query a second time"
    assert trace.total_llm_calls == 4, "call, retry, repair and learning extraction are all LLM"
    assert spans["orchestrator:llm_retry"] == "llm_call", "a retry is recorded, not dropped"
    assert spans["sql:tool:execute_query"] == "tool_call"


def test_producers_emit_the_types_the_trace_counts():
    """The producer sets the type explicitly (T14), so the map alone is not enough."""
    from pathlib import Path

    app = Path(__file__).resolve().parents[3] / "app"
    sql_agent = (app / "agents" / "sql_agent.py").read_text(encoding="utf-8")
    loop = (app / "core" / "validation_loop.py").read_text(encoding="utf-8")
    orchestrator = (app / "agents" / "orchestrator.py").read_text(encoding="utf-8")

    assert '_tool_span_type = "tool_call"' in sql_agent
    assert '"sql:learning_analysis"' in sql_agent
    flat_loop = "".join(loop.split())
    assert '"query_repair",f"Repairingquery' in flat_loop
    repair = flat_loop[flat_loop.index('"query_repair",f"Repairingquery') :][:400]
    assert 'span_type="llm_call"' in repair
    flat_orch = "".join(orchestrator.split())
    retry = flat_orch[flat_orch.index('"orchestrator:llm_retry"') :][:400]
    assert 'span_type="llm_call"' in retry
