"""The planner must know which sources this project actually has (A1).

Two halves, and each was broken on its own.

``PLANNER_SYSTEM_PROMPT`` is the vocabulary — a static constant listing the tools
a stage may name. ``query_analytics_source`` was absent, so the planner never
emitted an analytics stage and the pipeline's missing dispatch branch was never
even reached: the source was invisible rather than unreachable.

The per-project half is the reason listing it is not enough. The system prompt is
static, so a tool named there is offered to **every** project — and a stage
naming a source the project has not connected fails
``error_category="configuration"``, which is deliberately non-retryable and
short-circuits the run. ``query_mcp_source`` has had that shape all along; the
availability line closes it for both.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from app.agents.prompts.planner_prompt import (
    PLANNER_SYSTEM_PROMPT,
    build_planner_user_prompt,
    build_replan_prompt,
)

# ------------------------------------------------------------------
# REQ-4 — the vocabulary names the tool
# ------------------------------------------------------------------


class TestTheVocabulary:
    def test_the_system_prompt_names_query_analytics_source(self):
        assert "query_analytics_source" in PLANNER_SYSTEM_PROMPT, (
            "a tool absent from the planner's vocabulary is never planned, so "
            "the stage branch behind it can never run"
        )

    def test_the_tool_name_is_spelled_as_the_orchestrator_offers_it(self):
        from app.agents.tools.analytics_tools import QUERY_ANALYTICS_SOURCE_TOOL

        assert QUERY_ANALYTICS_SOURCE_TOOL.name in PLANNER_SYSTEM_PROMPT

    def test_the_entry_says_the_data_is_already_collected(self):
        """The distinguishing fact about this source, and the planner needs it.

        An analytics stage reads local fact tables filled on a schedule. A
        planner that thinks it calls the vendor live will plan windows nobody
        has collected, and the honest "not collected" answer reads as a failure.
        """
        start = PLANNER_SYSTEM_PROMPT.index("query_analytics_source")
        entry = PLANNER_SYSTEM_PROMPT[start : start + 700].lower()
        assert "collect" in entry, (
            "the analytics entry must say the data is read from what was "
            f"already collected; got: {entry[:300]!r}"
        )


# ------------------------------------------------------------------
# REQ-5 / REQ-6 — availability is per project, and it covers both tools
# ------------------------------------------------------------------


class TestAvailabilityReachesThePlanner:
    def test_connected_sources_are_listed(self):
        prompt = build_planner_user_prompt(
            "compare sessions with signups",
            db_type="postgres",
            available_sources=["database", "analytics (ga4)"],
        )
        assert "Connected sources:" in prompt
        assert "analytics (ga4)" in prompt
        assert "database" in prompt

    def test_an_absent_source_is_not_advertised(self):
        prompt = build_planner_user_prompt(
            "how many users signed up?",
            db_type="postgres",
            available_sources=["database"],
        )
        assert "Connected sources:" in prompt
        assert "analytics" not in prompt.lower(), (
            "a project with no analytics connection must not be told analytics "
            "exists — the stage would fail configuration, which is non-retryable"
        )

    def test_mcp_gets_the_same_protection(self):
        """Not a new rule — the same rule, applied to the tool that predates it."""
        prompt = build_planner_user_prompt(
            "what do our external sources say?",
            db_type="postgres",
            available_sources=["database"],
        )
        assert "mcp" not in prompt.lower(), (
            "query_mcp_source has always been offered unconditionally; the "
            "availability line is what stops it being planned for a project "
            "that has no MCP source"
        )

    def test_omitting_the_argument_keeps_the_old_prompt(self):
        """Back-compat: every existing caller must keep working unchanged."""
        prompt = build_planner_user_prompt("q", db_type="postgres", table_map="users(id)")
        assert "Connected sources:" not in prompt
        assert "Database type: postgres" in prompt

    def test_an_empty_list_says_nothing_rather_than_saying_none(self):
        prompt = build_planner_user_prompt("q", available_sources=[])
        assert "Connected sources:" not in prompt, (
            "an empty list is 'not stated', not 'no sources' — a probe that "
            "degraded to False must not be reported to the model as a fact"
        )


class TestAvailabilityReachesTheReplan:
    def test_the_replan_prompt_carries_the_same_line(self):
        prompt = build_replan_prompt(
            "q",
            completed_summaries=[],
            failed_stage_id="s1",
            failed_stage_desc="d",
            failed_stage_tool="query_database",
            error="boom",
            available_sources=["database", "analytics (ga4)"],
        )
        assert "Connected sources:" in prompt
        assert "analytics (ga4)" in prompt

    def test_a_replan_cannot_invent_a_source_the_project_lacks(self):
        prompt = build_replan_prompt(
            "q",
            completed_summaries=[],
            failed_stage_id="s1",
            failed_stage_desc="d",
            failed_stage_tool="query_database",
            error="boom",
            available_sources=["database"],
        )
        assert "analytics" not in prompt.lower(), (
            "a replan is where the LLM is explicitly told to take a different "
            "approach — the most likely place to reach for a source that is "
            "named in the vocabulary but not connected"
        )


# ------------------------------------------------------------------
# The seam: the planner API must actually forward it
# ------------------------------------------------------------------


class TestThePlannerForwardsIt:
    def test_plan_accepts_available_sources(self):
        from app.agents.adaptive_planner import AdaptivePlanner

        assert "available_sources" in inspect.signature(AdaptivePlanner.plan).parameters, (
            "a prompt argument nothing can pass is dead"
        )

    def test_replan_accepts_available_sources(self):
        from app.agents.adaptive_planner import AdaptivePlanner

        assert "available_sources" in inspect.signature(AdaptivePlanner.replan).parameters

    def test_the_orchestrator_passes_it_at_the_planner_call_site(self):
        from app.agents import orchestrator

        src = Path(inspect.getfile(orchestrator)).read_text(encoding="utf-8")
        assert "available_sources=" in src, (
            "the orchestrator is the only caller that knows has_analytics / "
            "has_mcp; if it does not pass them the line is never populated"
        )


# ------------------------------------------------------------------
# REQ-11 / REQ-12 — the workaround and the ladder that outlived it
# ------------------------------------------------------------------


class TestTheWorkaroundIsGone:
    def test_the_fallback_ladder_has_an_analytics_branch(self):
        """``_fallback_tool`` ended at ``query_mcp_source`` unconditionally.

        A project whose only source is analytics therefore got a last-resort
        quick plan naming a tool it has no source for.
        """
        from app.agents import orchestrator

        src = Path(inspect.getfile(orchestrator)).read_text(encoding="utf-8")
        start = src.index("_fallback_tool = ")
        ladder = src[start - 400 : start + 400]
        assert '_fallback_tool = "query_analytics_source"' in ladder, (
            "the ladder must be able to land on analytics; found:\n" + ladder
        )

    def test_the_pipeline_no_longer_bounces_an_analytics_only_project(self):
        """T13's workaround described a limitation this change removes.

        Kept as a source assertion rather than a behavioural one because the
        bounce was an early return inside ``_run_complex_pipeline``: its absence
        is what must be true, and an absence has no call to observe.
        """
        from app.agents import orchestrator

        src = Path(inspect.getfile(orchestrator)).read_text(encoding="utf-8")
        assert "cannot execute analytics stages" not in src, (
            "the pipeline can execute analytics stages now; a bounce that says "
            "otherwise sends every analytics-only project down the flat loop"
        )


@pytest.mark.parametrize(
    "tool",
    ["query_database", "search_codebase", "process_data", "query_mcp_source", "analyze_git"],
)
def test_no_existing_tool_lost_its_entry(tool):
    """A guard on the edit itself: adding a paragraph must not drop one."""
    assert tool in PLANNER_SYSTEM_PROMPT
