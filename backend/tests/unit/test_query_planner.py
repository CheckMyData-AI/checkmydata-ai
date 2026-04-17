"""Unit tests for app.agents.query_planner helpers (post-S1 cleanup).

The legacy ``QueryPlanner`` class was removed; AdaptivePlanner is now the only
entry point. Only structural plan-validation helpers remain in ``query_planner``.
"""

from __future__ import annotations

from app.agents.query_planner import _CREATE_PLAN_TOOL, _VALID_TOOLS, _validate_plan_structure

VALID_STAGES = [
    {
        "stage_id": "s1",
        "description": "Fetch revenue",
        "tool": "query_database",
        "depends_on": [],
    },
    {
        "stage_id": "s2",
        "description": "Summarize",
        "tool": "synthesize",
        "depends_on": ["s1"],
    },
]


class TestValidatePlanStructure:
    def test_empty_stages(self):
        errors = _validate_plan_structure([])
        assert errors == ["Plan has no stages"]

    def test_invalid_tool(self):
        stages = [{"stage_id": "s1", "tool": "hack_database", "depends_on": []}]
        errors = _validate_plan_structure(stages)
        assert any("invalid tool" in e for e in errors)

    def test_unknown_dependency(self):
        stages = [
            {"stage_id": "s1", "tool": "query_database", "depends_on": ["ghost"]},
        ]
        errors = _validate_plan_structure(stages)
        assert any("unknown stage 'ghost'" in e for e in errors)

    def test_no_data_retrieval_stage(self):
        stages = [
            {"stage_id": "s1", "tool": "synthesize", "depends_on": []},
        ]
        errors = _validate_plan_structure(stages)
        assert any("data-retrieval" in e for e in errors)

    def test_circular_dependency(self):
        stages = [
            {"stage_id": "s1", "tool": "query_database", "depends_on": ["s2"]},
            {"stage_id": "s2", "tool": "synthesize", "depends_on": ["s1"]},
        ]
        errors = _validate_plan_structure(stages)
        assert any("circular" in e.lower() for e in errors)

    def test_valid_plan(self):
        errors = _validate_plan_structure(VALID_STAGES)
        assert errors == []

    def test_search_codebase_counts_as_retrieval(self):
        stages = [
            {"stage_id": "s1", "tool": "search_codebase", "depends_on": []},
            {"stage_id": "s2", "tool": "synthesize", "depends_on": ["s1"]},
        ]
        assert _validate_plan_structure(stages) == []


class TestPlanSchema:
    def test_create_plan_tool_present(self):
        assert _CREATE_PLAN_TOOL["function"]["name"] == "create_execution_plan"

    def test_valid_tools_set(self):
        assert "query_database" in _VALID_TOOLS
        assert "synthesize" in _VALID_TOOLS
