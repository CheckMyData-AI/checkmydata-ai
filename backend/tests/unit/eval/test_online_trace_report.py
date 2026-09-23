"""PRJ-13 T08c — the reference-free trace report counts what production did, once."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.eval.online.trace_report import build_report, request_budget_ms
from app.models.base import Base
from app.models.request_trace import RequestTrace, TraceSpan

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    s = async_sessionmaker(engine, expire_on_commit=False)()
    try:
        yield s
    finally:
        await s.close()
        await engine.dispose()


def _trace(i, *, status="completed", route="query", ms=1000.0, kind=None, age_days=1):
    return RequestTrace(
        id=f"t{i}",
        project_id="p",
        user_id="u",
        workflow_id=f"w{i}",
        status=status,
        route=route,
        failure_kind=kind,
        total_duration_ms=ms,
        total_tokens=100,
        created_at=NOW - timedelta(days=age_days),
    )


def _span(i, trace, kind, ms):
    return TraceSpan(
        id=f"s{i}", trace_id=trace, span_type=kind, name=kind, duration_ms=ms, started_at=NOW
    )


async def test_the_report_counts_outcomes_latency_and_where_time_went(session) -> None:
    budget = request_budget_ms()
    session.add_all(
        [
            _trace(1, ms=1000.0),
            _trace(2, ms=budget + 1),
            _trace(3, status="failed", kind="deadline", route="unknown", ms=3000.0),
            _trace(4, age_days=40),  # outside the window
            _span(1, "t1", "llm_call", 600.0),
            _span(2, "t1", "db_query", 200.0),
            _span(3, "t1", "tool_call", 900.0),  # an envelope: never summed
            _span(4, "t1", "validation", 5000.0),  # an envelope: never summed
            TraceSpan(
                id="s5",
                trace_id="t1",
                span_type="llm_call",
                name="orchestrator:replan",
                duration_ms=0.0,
                started_at=NOW,
            ),
            TraceSpan(
                id="s6",
                trace_id="t3",
                span_type="llm_call",
                name="orchestrator:replan",
                duration_ms=0.0,
                started_at=NOW,
            ),
            TraceSpan(
                id="s7",
                trace_id="t3",
                span_type="llm_call",
                name="orchestrator:llm_retry",
                duration_ms=0.0,
                started_at=NOW,
            ),
        ]
    )
    await session.commit()

    report = await build_report(session, days=30, now=NOW)

    assert report["traces"] == 3
    assert report["status"] == {"completed": 2, "failed": 1}
    assert report["failure_kind"] == {"deadline": 1}
    assert report["unrouted_share"] == pytest.approx(33.3)
    assert report["latency_ms"]["over_budget"] == 1
    assert report["latency_ms"]["p50"] == 3000.0
    # The replan/retry spans are `llm_call` too but carry 0 ms, so the split holds.
    assert report["time_split_pct"] == {"llm_call": 75.0, "db_query": 25.0}
    assert report["replans"] == {"total": 2, "traces_with_replan": 2}
    assert report["llm_retries"] == 1


async def test_an_empty_window_is_a_report_not_an_error(session) -> None:
    report = await build_report(session, days=7, now=NOW)
    assert report["traces"] == 0 and report["latency_ms"]["p50"] is None
