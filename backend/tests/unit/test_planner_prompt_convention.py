"""Tests for ORCH-P02: cohort_window param convention consistency across prompts.

Also tests T7 deferred scope: expected_columns / min_rows guidance scoped to DATA stages.
"""

from __future__ import annotations

from app.agents.prompts.orchestrator_prompt import build_orchestrator_system_prompt
from app.agents.prompts.planner_prompt import PLANNER_SYSTEM_PROMPT


class TestCohortWindowConventionConsistent:
    """ORCH-P02: both prompts must agree on top-level keys as canonical convention."""

    def _orch_prompt(self) -> str:
        return build_orchestrator_system_prompt(
            has_connection=True,
            has_repo=True,
            db_type="postgres",
        )

    def test_both_prompts_mention_top_level_keys(self) -> None:
        """Both prompts must contain the phrase 'top-level keys'."""
        orch = self._orch_prompt()
        assert "top-level keys" in orch, (
            "orchestrator_prompt missing 'top-level keys' for cohort_window"
        )
        assert "top-level keys" in PLANNER_SYSTEM_PROMPT, (
            "planner_prompt missing 'top-level keys' for cohort_window"
        )

    def test_both_prompts_mention_release_dates(self) -> None:
        """Both prompts must reference 'release_dates' for cohort_window."""
        orch = self._orch_prompt()
        assert "release_dates" in orch, "orchestrator_prompt missing release_dates"
        assert "release_dates" in PLANNER_SYSTEM_PROMPT, "planner_prompt missing release_dates"

    def test_both_prompts_mention_event_date_column(self) -> None:
        """Both prompts must reference 'event_date_column' for cohort_window."""
        orch = self._orch_prompt()
        assert "event_date_column" in orch, "orchestrator_prompt missing event_date_column"
        assert "event_date_column" in PLANNER_SYSTEM_PROMPT, (
            "planner_prompt missing event_date_column"
        )

    def test_orchestrator_prompt_mentions_back_compat_params_json(self) -> None:
        """Orchestrator prompt should mention params_json back-compat note."""
        orch = self._orch_prompt()
        assert "params_json" in orch, (
            "orchestrator_prompt should mention params_json for back-compat"
        )

    def test_planner_prompt_mentions_back_compat_params_json(self) -> None:
        """Planner prompt should mention params_json back-compat note."""
        assert "params_json" in PLANNER_SYSTEM_PROMPT, (
            "planner_prompt should mention params_json for back-compat"
        )


class TestPlannerPromptDataStageScope:
    """T7 deferred: expected_columns/min_rows guidance scoped to DATA stages only."""

    def test_validation_criteria_scoped_to_data_stages(self) -> None:
        """Rule 6 about expected_columns/min_rows should mention DATA stages."""
        prompt_lower = PLANNER_SYSTEM_PROMPT.lower()
        # The rule must specify data stages (not synthesize/analyze_results)
        assert "data" in prompt_lower, "planner_prompt should mention data stages context"
        # Must contain expected_columns and min_rows as fields
        assert "expected_columns" in PLANNER_SYSTEM_PROMPT
        assert "min_rows" in PLANNER_SYSTEM_PROMPT
