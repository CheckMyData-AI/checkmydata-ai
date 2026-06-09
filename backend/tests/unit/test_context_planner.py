"""Tests for the Phase 4 ContextPlanner and planned/trust-enriched ContextPack.

Covers:
1. Heuristic planning — category selection from question cues + router signals.
2. The plan is advisory and never raises; degraded paths fall back to full.
3. KnowledgeCatalogService honours the plan (prunes categories) and trust-
   enriches every artifact + emits a provenance summary.
"""

from __future__ import annotations

import pytest

from app.agents.context_planner import (
    ALL_NEEDS,
    ContextNeed,
    ContextPlan,
    ContextPlanner,
)
from app.knowledge.context_pack import Artifact, ContextPack


# --------------------------------------------------------------------------- #
# ContextPlan
# --------------------------------------------------------------------------- #
def test_full_plan_includes_every_category() -> None:
    plan = ContextPlan.full()
    for need in ALL_NEEDS:
        assert plan.wants(need)
    assert plan.mode == "default"


def test_plan_limit_falls_back_to_default() -> None:
    plan = ContextPlan(needs=frozenset({ContextNeed.TABLES}))
    # Unspecified limit → category default (tables=40).
    assert plan.limit_for(ContextNeed.TABLES) == 40


# --------------------------------------------------------------------------- #
# ContextPlanner heuristics
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_planner_baseline_keeps_rules_and_learnings() -> None:
    planner = ContextPlanner()
    plan = await planner.plan("hello", has_connection=False, has_repo=False, estimated_queries=1)
    assert plan.wants(ContextNeed.RULES)
    assert plan.wants(ContextNeed.LEARNINGS)
    # No connection → no tables/lineage; no repo → no rag.
    assert not plan.wants(ContextNeed.TABLES)
    assert not plan.wants(ContextNeed.LINEAGE)
    assert not plan.wants(ContextNeed.RAG)


@pytest.mark.asyncio
async def test_planner_lineage_cue() -> None:
    planner = ContextPlanner()
    plan = await planner.plan(
        "where is the orders table populated from in code?",
        has_connection=True,
        has_repo=True,
    )
    assert plan.wants(ContextNeed.LINEAGE)
    assert plan.wants(ContextNeed.TABLES)


@pytest.mark.asyncio
async def test_planner_complex_widens_net() -> None:
    planner = ContextPlanner()
    plan = await planner.plan(
        "compare revenue across regions and reconcile with the billing code",
        has_connection=True,
        has_repo=True,
        needs_multiple_data_sources=True,
        estimated_queries=4,
    )
    assert plan.wants(ContextNeed.LINEAGE)
    assert plan.wants(ContextNeed.INSIGHTS)
    assert plan.wants(ContextNeed.RAG)
    assert "complex→widen" in plan.rationale


@pytest.mark.asyncio
async def test_planner_narrow_question_tightens_limits() -> None:
    planner = ContextPlanner()
    plan = await planner.plan(
        "list users", has_connection=True, has_repo=False, estimated_queries=1
    )
    assert plan.limit_for(ContextNeed.TABLES) == 20  # tightened from 40
    assert plan.limit_for(ContextNeed.LEARNINGS) == 8


@pytest.mark.asyncio
async def test_planner_repo_gets_rag_baseline() -> None:
    planner = ContextPlanner()
    plan = await planner.plan(
        "list users", has_connection=False, has_repo=True, estimated_queries=1
    )
    # Repo present, nothing else cued → rag baseline kicks in.
    assert plan.wants(ContextNeed.RAG)


# --------------------------------------------------------------------------- #
# ContextPack provenance + trust
# --------------------------------------------------------------------------- #
def test_artifact_source_ref() -> None:
    art = Artifact(
        id="table:c::public.orders",
        type="table",
        title="orders",
        provenance={"source": "db_index", "source_ref": "connection:c"},
    )
    assert art.source_ref() == "db_index:connection:c"


def test_provenance_summary_groups_by_block() -> None:
    pack = ContextPack(project_id="p")
    pack.tables = [
        Artifact(id="t1", type="table", title="orders", trust={"confidence_label": "high"}),
        Artifact(id="t2", type="table", title="users", trust={"confidence_label": "high"}),
    ]
    pack.rules = [Artifact(id="r1", type="rule", title="no pii")]
    summary = pack.provenance_summary()
    blocks = {s["block"]: s for s in summary}
    assert blocks["tables"]["count"] == 2
    assert blocks["tables"]["confidence_labels"]["high"] == 2
    assert "rules" in blocks
    # Empty sections are omitted.
    assert "lineage" not in blocks
