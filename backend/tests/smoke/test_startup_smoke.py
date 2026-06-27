"""STARTUP SMOKE suite — fast, deterministic confirmation that the core
machine works on the canonical billing/subscriptions business scenario.

Run at server boot / in CI via ``make smoke``. Every numeric assertion is
hand-computed from the seed in ``conftest.py`` (see the module constants
there) and checked against the REAL production code paths:

  - the seeded billing SQL (revenue-by-method, weekly cohorts);
  - ``app.core.safety.SafetyGuard`` read-only enforcement;
  - ``app.agents.data_gate.DataGate`` impossible-value gate;
  - ``app.agents.query_planner._validate_plan_structure`` plan validation;
  - ``app.agents.router.route_request`` with a mocked LLM (no network).
"""

from __future__ import annotations

from collections import defaultdict
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.data_gate import DataGate
from app.agents.query_planner import _validate_plan_structure
from app.agents.router import route_request
from app.agents.stage_context import (
    ExecutionPlan,
    PlanStage,
    StageContext,
    StageResult,
)
from app.connectors.base import QueryResult
from app.core.safety import SafetyGuard, SafetyLevel
from app.llm.base import Message

from .conftest import (
    EXPECTED_GRAND_TOTAL_CENTS,
    EXPECTED_IN_WINDOW_COUNT,
    EXPECTED_REVENUE_BY_METHOD,
    IN_WINDOW_ROWS,
    WINDOW_CUTOFF,
    SmokeConnector,
)

pytestmark = pytest.mark.smoke


# ---------------------------------------------------------------------------
# 1. Revenue for the last 3 months broken down by payment method.
# ---------------------------------------------------------------------------
async def test_revenue_by_payment_method_last_3_months(run_sql: SmokeConnector) -> None:
    sql = f"""
        SELECT payment_method, SUM(amount_cents) AS revenue_cents
        FROM orders
        WHERE created_at >= '{WINDOW_CUTOFF}'
        GROUP BY payment_method
        ORDER BY payment_method
    """
    result = await run_sql(sql)

    actual = {method: revenue for method, revenue in result.rows}

    # Hand-computed from the seed: apple=18000, card=7500, google=5500.
    assert actual == EXPECTED_REVENUE_BY_METHOD
    assert actual == {"apple": 18_000, "card": 7_500, "google": 5_500}

    # Grand total across all methods, and the pre-cutoff row is excluded.
    assert sum(actual.values()) == EXPECTED_GRAND_TOTAL_CENTS == 31_000

    count_row = await run_sql(f"SELECT COUNT(*) FROM orders WHERE created_at >= '{WINDOW_CUTOFF}'")
    assert count_row.rows[0][0] == EXPECTED_IN_WINDOW_COUNT == 11

    # The big pre-cutoff order (99_999) must not leak into the window.
    assert 99_999 not in actual.values()


# ---------------------------------------------------------------------------
# 2. Weekly cohort analysis: avg order value, purchase count, total revenue.
# ---------------------------------------------------------------------------
async def test_weekly_cohort_metrics_last_3_months(run_sql: SmokeConnector) -> None:
    sql = f"""
        SELECT
            strftime('%Y-%W', created_at) AS cohort_week,
            COUNT(*) AS purchases,
            SUM(amount_cents) AS total_revenue_cents,
            AVG(amount_cents) AS avg_order_value_cents
        FROM orders
        WHERE created_at >= '{WINDOW_CUTOFF}'
        GROUP BY cohort_week
        ORDER BY cohort_week
    """
    result = await run_sql(sql)

    actual = {
        week: {
            "purchases": purchases,
            "total_cents": total,
            "avg_cents": avg,
        }
        for week, purchases, total, avg in result.rows
    }

    # Recompute the expected cohorts in Python using the SAME SQLite %W label,
    # so the assertion is self-verifying rather than a copied magic table.
    week_labels = await run_sql(
        f"SELECT id, strftime('%Y-%W', created_at) FROM orders "
        f"WHERE created_at >= '{WINDOW_CUTOFF}' ORDER BY id"
    )
    label_by_amount: list[tuple[str, int]] = []
    for (_id, label), (_date, amount, _method) in zip(
        week_labels.rows, IN_WINDOW_ROWS, strict=True
    ):
        label_by_amount.append((label, amount))

    buckets: dict[str, list[int]] = defaultdict(list)
    for label, amount in label_by_amount:
        buckets[label].append(amount)

    expected = {
        week: {
            "purchases": len(amounts),
            "total_cents": sum(amounts),
            "avg_cents": sum(amounts) / len(amounts),
        }
        for week, amounts in buckets.items()
    }

    assert actual == expected

    # Explicit hand-computed spot checks (week label -> metrics):
    #   2026-04-06 & 2026-04-08 -> %W=14 : 2 purchases, 4000 total, 2000 avg
    #   2026-04-20             -> %W=16 : 1 purchase,  5000 total, 5000 avg
    #   2026-06-15             -> %W=24 : 1 purchase,  6000 total, 6000 avg
    assert actual["2026-14"] == {"purchases": 2, "total_cents": 4_000, "avg_cents": 2_000.0}
    assert actual["2026-16"] == {"purchases": 1, "total_cents": 5_000, "avg_cents": 5_000.0}
    assert actual["2026-24"] == {"purchases": 1, "total_cents": 6_000, "avg_cents": 6_000.0}

    # 9 distinct weekly cohorts in the window; total revenue ties out to (1).
    assert len(actual) == 9
    assert sum(c["total_cents"] for c in actual.values()) == 31_000


# ---------------------------------------------------------------------------
# 3. Read-only enforcement: SafetyGuard blocks writes, allows reads.
# ---------------------------------------------------------------------------
def test_safetyguard_blocks_writes_in_readonly() -> None:
    guard = SafetyGuard(level=SafetyLevel.READ_ONLY)

    # A real read query for the scenario is allowed.
    select_sql = (
        "SELECT payment_method, SUM(amount_cents) FROM orders "
        f"WHERE created_at >= '{WINDOW_CUTOFF}' GROUP BY payment_method"
    )
    assert guard.validate_sql(select_sql).is_safe is True

    # Writes / DDL are rejected.
    for write_sql in (
        "UPDATE orders SET amount_cents = 0 WHERE id = 1",
        "DELETE FROM orders WHERE id = 1",
        "DROP TABLE orders",
        "INSERT INTO orders (user_id, amount_cents) VALUES (1, 100)",
    ):
        res = guard.validate_sql(write_sql)
        assert res.is_safe is False, f"expected block for: {write_sql}"
        assert res.reason

    # Stacked statement (SELECT then DROP) is also blocked in read-only mode.
    stacked = guard.validate_sql("SELECT 1; DROP TABLE orders")
    assert stacked.is_safe is False


# ---------------------------------------------------------------------------
# 4. DataGate blocks impossible values; passes a clean revenue result.
# ---------------------------------------------------------------------------
def _stage_and_ctx(stage_id: str = "s1") -> tuple[PlanStage, StageContext]:
    stage = PlanStage(stage_id=stage_id, description="check", tool="query_database")
    plan = ExecutionPlan(plan_id="p1", question="q", stages=[stage])
    return stage, StageContext(plan=plan)


def test_datagate_blocks_impossible_values() -> None:
    gate = DataGate()

    # (a) Impossible bounded percentage: conversion_pct = 150 (>100.5 bound).
    stage, ctx = _stage_and_ctx()
    bad_pct = StageResult(
        stage_id="s1",
        status="success",
        query_result=QueryResult(
            columns=["payment_method", "conversion_pct"],
            rows=[["apple", 12.5], ["card", 150.0], ["google", 9.0]],
            row_count=3,
        ),
    )
    pct_outcome = gate.check(stage, bad_pct, ctx)
    assert pct_outcome.passed is False
    assert any("conversion_pct" in e for e in pct_outcome.errors)

    # (b) Negative count is impossible for a purchase count.
    stage, ctx = _stage_and_ctx()
    bad_count = StageResult(
        stage_id="s1",
        status="success",
        query_result=QueryResult(
            columns=["cohort_week", "purchase_count"],
            rows=[["2026-14", 2], ["2026-15", -3], ["2026-16", 1]],
            row_count=3,
        ),
    )
    count_outcome = gate.check(stage, bad_count, ctx)
    assert count_outcome.passed is False
    assert any("purchase_count" in e for e in count_outcome.errors)

    # (c) A clean revenue-by-method result passes (matches the real seed).
    stage, ctx = _stage_and_ctx()
    clean = StageResult(
        stage_id="s1",
        status="success",
        query_result=QueryResult(
            columns=["payment_method", "revenue_cents"],
            rows=[["apple", 18_000], ["card", 7_500], ["google", 5_500]],
            row_count=3,
        ),
    )
    clean_outcome = gate.check(stage, clean, ctx)
    assert clean_outcome.passed is True
    assert clean_outcome.errors == []


# ---------------------------------------------------------------------------
# 5. Planner accepts a well-formed multi-stage cohort plan.
# ---------------------------------------------------------------------------
def test_planner_accepts_cohort_plan() -> None:
    stages = [
        {
            "stage_id": "fetch_orders",
            "description": "Query orders for the last 3 months by payment method and week.",
            "tool": "query_database",
            "depends_on": [],
        },
        {
            "stage_id": "compute_cohorts",
            "description": "Aggregate avg order value, purchase count, revenue per weekly cohort.",
            "tool": "process_data",
            "depends_on": ["fetch_orders"],
        },
        {
            "stage_id": "answer",
            "description": "Synthesize the cohort table and revenue-by-method breakdown.",
            "tool": "synthesize",
            "depends_on": ["compute_cohorts"],
        },
    ]
    errors = _validate_plan_structure(stages)
    assert errors == []


# ---------------------------------------------------------------------------
# 6. Router classifies the revenue question (mocked LLM, no network).
# ---------------------------------------------------------------------------
async def test_router_classifies_revenue_question() -> None:
    canned = MagicMock()
    canned.content = (
        '{"route": "query", "complexity": "complex", '
        '"approach": "Aggregate revenue by payment method and weekly cohort.", '
        '"estimated_queries": 2, "needs_multiple_data_sources": false}'
    )
    llm = MagicMock()
    llm.complete = AsyncMock(return_value=canned)

    result = await route_request(
        "Show revenue for the last 3 months by payment method and weekly cohorts.",
        llm,
        has_connection=True,
        chat_history=[Message(role="user", content="hi")],
    )

    # Parsed the canned route — NOT the unparseable-fallback default ("explore").
    assert result.route == "query"
    assert result.complexity == "complex"
    assert result.estimated_queries == 2
    assert result.use_complex_pipeline is True
    assert result.is_direct is False
    assert result.raw is not None
    llm.complete.assert_awaited_once()
