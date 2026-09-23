"""Reference-free report over production traces (PRJ-13 T08c)."""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.request_trace import RequestTrace, TraceSpan

#: Only these span types measure where time went; `validation`, `sub_agent` and
#: `tool_call` are envelopes around them (PRJ-04), and summing envelopes counts twice.
_WORK_SPANS = ("llm_call", "db_query")


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, round(q * (len(ordered) - 1))))
    return ordered[k]


def request_budget_ms() -> float:
    """The hard cutoff a request is held to: `agent_wall_clock_timeout_seconds × 1.2`
    (`app/agents/request_clock.py`, PRJ-03)."""
    from app.config import settings

    return settings.agent_wall_clock_timeout_seconds * 1.2 * 1000


async def build_report(
    session: AsyncSession, *, days: int = 30, now: datetime | None = None
) -> dict[str, Any]:
    since = (now or datetime.now(UTC)) - timedelta(days=days)
    traces = (
        await session.scalars(select(RequestTrace).where(RequestTrace.created_at >= since))
    ).all()
    ids = [t.id for t in traces]
    spans = (
        (
            await session.scalars(
                select(TraceSpan).where(
                    TraceSpan.trace_id.in_(ids), TraceSpan.span_type.in_(_WORK_SPANS)
                )
            )
        ).all()
        if ids
        else []
    )

    # T08d (Ш0b): the counters `MetricsCollector` keeps in memory — and loses on every
    # restart — are derivable from what IS persisted: each replan is an
    # `orchestrator:replan` span (REQ-6), each provider retry an `*:llm_retry` span
    # (PRJ-04), so history needs a query, not a second store.
    marker_spans = (
        (
            await session.scalars(
                select(TraceSpan).where(
                    TraceSpan.trace_id.in_(ids),
                    (TraceSpan.name == "orchestrator:replan") | TraceSpan.name.like("%:llm_retry"),
                )
            )
        ).all()
        if ids
        else []
    )
    replans = [s for s in marker_spans if s.name == "orchestrator:replan"]
    retries = [s for s in marker_spans if s.name.endswith(":llm_retry")]

    budget = request_budget_ms()
    durations = [t.total_duration_ms for t in traces if t.total_duration_ms is not None]
    by_type: dict[str, float] = {k: 0.0 for k in _WORK_SPANS}
    for s in spans:
        by_type[s.span_type] += s.duration_ms or 0.0
    work = sum(by_type.values())

    return {
        "window_days": days,
        "since": since.date().isoformat(),
        "traces": len(traces),
        "status": dict(Counter(t.status for t in traces)),
        "failure_kind": dict(
            Counter(t.failure_kind or "unclassified" for t in traces if t.status == "failed")
        ),
        "route": dict(Counter(t.route for t in traces)),
        "unrouted_share": round(100.0 * sum(t.route == "unknown" for t in traces) / len(traces), 1)
        if traces
        else None,
        "latency_ms": {
            "p50": _percentile(durations, 0.5),
            "p95": _percentile(durations, 0.95),
            "max": max(durations) if durations else None,
            "mean": round(statistics.fmean(durations), 1) if durations else None,
            "budget": budget,
            "over_budget": sum(d > budget for d in durations),
        },
        "time_split_pct": {k: round(100.0 * v / work, 1) for k, v in by_type.items()}
        if work
        else {},
        "tokens": sum(t.total_tokens or 0 for t in traces),
        "replans": {
            "total": len(replans),
            "traces_with_replan": len({s.trace_id for s in replans}),
        },
        "llm_retries": len(retries),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.eval.online.trace_report")
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args(argv)

    async def _run() -> dict[str, Any]:
        from app.models.base import async_session_factory

        async with async_session_factory() as session:
            return await build_report(session, days=args.days)

    print(json.dumps(asyncio.run(_run()), ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
