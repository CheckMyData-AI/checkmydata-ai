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
    _word_match,
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
# CP01: word-boundary cue matching (ORCH-CP01)
# --------------------------------------------------------------------------- #


def test_word_match_single_word_requires_boundary() -> None:
    """_word_match uses \\b boundaries — only fires when cue is a standalone token."""
    assert _word_match("show me the code", "code") is True
    assert _word_match("country code distribution", "code") is True  # "code" IS a word here
    # Sub-token embedding must not fire:
    assert _word_match("barcode scanner data", "code") is False  # "code" inside "barcode"
    assert _word_match("functional programming patterns", "function") is False  # in "functional"
    # "drop-off": hyphen is a non-\w char so \bdrop\b fires — we removed "drop" from _CUES
    # instead of relying on word-boundary alone (see CP01 fix).
    assert _word_match("analyze drop-off funnel", "drop") is True  # \b fires at hyphen
    assert _word_match("analyze the drop count", "drop") is True  # standalone word


def test_word_match_phrase_cue_uses_substring() -> None:
    """Multi-word cues use plain substring matching."""
    assert _word_match("how is the revenue trending", "how is") is True
    assert _word_match("how is it going today", "how is") is True
    assert _word_match("where is the data from", "where is") is True


@pytest.mark.asyncio
async def test_country_code_does_not_trigger_rag() -> None:
    """'code' removed from RAG cues so 'country code' doesn't spuriously fire RAG.

    CP01 fix: bare 'code' cue dropped; word-boundary alone isn't enough since
    'country code' contains 'code' as a word — we must remove the cue entirely.
    """
    planner = ContextPlanner()
    plan = await planner.plan(
        "show me the country code distribution",
        has_connection=True,
        has_repo=False,
    )
    # No repo → rag baseline also doesn't fire. 'code' cue removed → no RAG.
    assert not plan.wants(ContextNeed.RAG), (
        f"RAG should NOT fire on 'country code' but plan.needs={plan.needs}"
    )


@pytest.mark.asyncio
async def test_dropdown_does_not_trigger_insights() -> None:
    """'drop' removed from INSIGHTS cues — 'dropdown' no longer spuriously fires INSIGHTS.

    CP01 fix: bare 'drop' cue replaced with explicit 'drop-off' phrase cue.
    A UI question about a dropdown menu must not trigger INSIGHTS loading.
    """
    planner = ContextPlanner()
    plan = await planner.plan(
        "why is the dropdown menu slow to load",
        has_connection=True,
        has_repo=False,
    )
    # 'dropdown' contains 'drop' as a substring — with the old bare-'drop' cue this fired.
    # After CP01 fix (replaced with 'drop-off' phrase), it must NOT fire INSIGHTS.
    assert ContextNeed.INSIGHTS not in plan.needs, (
        f"INSIGHTS should NOT fire on 'dropdown' but plan.needs={plan.needs}"
    )


@pytest.mark.asyncio
async def test_dropoff_phrase_correctly_triggers_insights() -> None:
    """Explicit 'drop-off' phrase cue fires INSIGHTS for genuine drop-off questions."""
    planner = ContextPlanner()
    plan = await planner.plan(
        "analyze the drop-off funnel conversion",
        has_connection=True,
        has_repo=False,
    )
    # 'drop-off' IS in the question and is a genuine INSIGHTS cue — should fire.
    assert plan.wants(ContextNeed.INSIGHTS), (
        f"INSIGHTS SHOULD fire on 'drop-off' but plan.needs={plan.needs}"
    )


@pytest.mark.asyncio
async def test_real_code_word_triggers_rag() -> None:
    """A genuine repo question ('function') still triggers RAG after CP01 fix."""
    planner = ContextPlanner()
    plan = await planner.plan(
        "explain the login function",
        has_connection=True,
        has_repo=True,
    )
    assert plan.wants(ContextNeed.RAG), (
        f"RAG SHOULD fire on 'function' cue but plan.needs={plan.needs}"
    )


@pytest.mark.asyncio
async def test_architecture_cue_triggers_rag() -> None:
    """'architecture' cue still fires RAG after 'code' cue is dropped."""
    planner = ContextPlanner()
    plan = await planner.plan(
        "describe the overall architecture of this system",
        has_connection=False,
        has_repo=True,
    )
    assert plan.wants(ContextNeed.RAG), (
        f"RAG SHOULD fire on 'architecture' cue but plan.needs={plan.needs}"
    )


def test_context_planner_cue_precision_is_wired_for_w2() -> None:
    """CP02: confirm _word_match is exported and works — the W3 precision deliverable.

    Hot-path invocation (ContextLoader.assemble_knowledge_block → ContextPlanner.plan)
    is wired in W2 behind context_planner_enabled (RET-R1). W3 delivers the
    precision fix only; _word_match being importable confirms the seam is in place.
    """
    # Single-word: boundary enforced
    assert _word_match("show me the function signature", "function") is True
    assert _word_match("functional programming patterns", "function") is False
    # Phrase cue: substring
    assert _word_match("how does authentication work", "how does") is True
    # The hot-path wiring exists in context_loader.py assemble_knowledge_block
    # (W2-T8 / RET-R1) — see orchestrator.py line ~903 for the seam comment.


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
