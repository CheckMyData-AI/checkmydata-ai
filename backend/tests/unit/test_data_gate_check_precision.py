"""Three DataGate checks that concluded from something other than what they meant.

* **F-DG-05** — the bounded-percent interval was tightened on one side only. The
  upper bound got its own setting (`data_gate_percent_bounded_max = 100.5`, a rounding
  tolerance) while the floor stayed at `-1.0`, so a "conversion_pct" of `-0.9` passed a
  check whose whole premise is that the column is a 0..100 share. A negative share is
  exactly as impossible as 150%.

* **F-DG-06** — the type-consistency check counted distinct type *names* and warned
  above two. That is wrong in both directions: `{int, str}` is two and is precisely the
  pairing that let `"150"` bypass the value-range hard checks, while
  `{int, float, Decimal}` is three and is what any SQL numeric column looks like. The
  question is whether the types are *related*, and a count cannot answer it.

* **F-DG-08** — the cartesian blow-up check divides one stage's `row_count` by its
  dependency's. `row_count` is the number of rows *returned*; `truncated` is the
  separate flag saying more existed. Two capped counts produce a ratio of about 1 and
  the check reports nothing wrong — a reassuring number that was never earned.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest

from app.agents.data_gate import DataGate
from app.agents.stage_context import ExecutionPlan, PlanStage, StageContext, StageResult
from app.connectors.base import QueryResult


def _stage(stage_id: str = "s1", depends_on: list[str] | None = None) -> PlanStage:
    return PlanStage(
        stage_id=stage_id,
        description="x",
        tool="query_database",
        depends_on=depends_on or [],
    )


class TestBoundedPercentFloor:
    @pytest.mark.parametrize("bad", [-0.9, -5.0, -100.0])
    def test_a_negative_share_is_impossible(self, bad):
        qr = QueryResult(columns=["conversion_pct"], rows=[[bad]], row_count=1)
        with patch("app.agents.data_gate.settings") as st:
            st.data_gate_hard_checks_enabled = True
            st.data_gate_percent_min = -0.5
            st.data_gate_percent_max = 200.0
            st.data_gate_percent_bounded_max = 100.5
            st.data_gate_value_range_sample = 0
            st.data_gate_year_min, st.data_gate_year_max = 1900, 2100
            st.data_gate_llm_semantics = False
            out = DataGate().check_query_result(qr)
        assert out.passed is False, f"{bad}% of a 0..100 share must hard-fail"

    @pytest.mark.parametrize("ok", [-0.4, 0.0, 50.0, 100.0, 100.4])
    def test_the_rounding_tolerance_survives_on_both_sides(self, ok):
        """Symmetry is the point: 100.4 passes above, so -0.4 must pass below."""
        qr = QueryResult(columns=["conversion_pct"], rows=[[ok]], row_count=1)
        with patch("app.agents.data_gate.settings") as st:
            st.data_gate_hard_checks_enabled = True
            st.data_gate_percent_min = -0.5
            st.data_gate_percent_max = 200.0
            st.data_gate_percent_bounded_max = 100.5
            st.data_gate_value_range_sample = 0
            st.data_gate_year_min, st.data_gate_year_max = 1900, 2100
            st.data_gate_llm_semantics = False
            out = DataGate().check_query_result(qr)
        assert out.passed is True, f"{ok} is within tolerance and must not fail"

    def test_the_shipped_default_is_symmetric(self):
        """The defect was the asymmetry, so the defaults are what must not drift."""
        from app.config import Settings

        s = Settings()
        above = s.data_gate_percent_bounded_max - 100.0
        below = 0.0 - s.data_gate_percent_min
        assert below == pytest.approx(above), (
            f"tolerance is {above} above 100 but {below} below 0 — a negative share is "
            "as impossible as 150%, so the two must match"
        )

    def test_a_rate_column_keeps_its_loose_signed_range(self):
        """Rates legitimately go negative and past 100 — this must not be tightened."""
        qr = QueryResult(columns=["growth_rate"], rows=[[-50.0], [150.0]], row_count=2)
        with patch("app.agents.data_gate.settings") as st:
            st.data_gate_hard_checks_enabled = True
            st.data_gate_percent_min = -0.5
            st.data_gate_percent_max = 200.0
            st.data_gate_percent_bounded_max = 100.5
            st.data_gate_value_range_sample = 0
            st.data_gate_year_min, st.data_gate_year_max = 1900, 2100
            st.data_gate_llm_semantics = False
            out = DataGate().check_query_result(qr)
        assert out.passed is True
        assert not out.warnings, out.warnings


class TestTypeConsistencyJudgesFamilies:
    @staticmethod
    def _warnings(rows: list[list[object]]) -> list[str]:
        from app.agents.data_gate import DataGateOutcome

        gate = DataGate()

        outcome = DataGateOutcome()
        gate._check_type_consistency(
            QueryResult(columns=["v"], rows=rows, row_count=len(rows)), outcome
        )
        return outcome.warnings

    def test_a_numeric_column_with_three_numeric_types_is_not_mixed(self):
        """`{int, float, Decimal}` is what any SQL numeric column looks like."""
        rows = [[1], [2.5], [Decimal("3.5")]]
        assert self._warnings(rows) == []

    def test_an_int_and_str_pair_is_mixed_even_though_it_is_only_two(self):
        """The pairing that let `"150"` bypass the value-range hard checks."""
        rows = [[1], ["150"]]
        assert self._warnings(rows), "a number-or-string column must be flagged"

    def test_bool_is_not_silently_numeric(self):
        """`bool` is an `int` subclass in Python but not the same column semantically."""
        rows = [[True], [3]]
        assert self._warnings(rows)

    def test_a_single_type_never_warns(self):
        assert self._warnings([[1], [2], [3]]) == []

    def test_nulls_do_not_count_as_a_type(self):
        assert self._warnings([[1], [None], [2]]) == []

    def test_dates_and_strings_are_different_families(self):
        from datetime import date

        assert self._warnings([[date(2026, 1, 1)], ["2026-01-01"]])


class TestCartesianCheckRefusesTruncatedInputs:
    @staticmethod
    def _outcome(qr: QueryResult, dep: QueryResult):
        plan = ExecutionPlan(
            plan_id="p",
            question="q",
            stages=[_stage("dep"), _stage("s1", depends_on=["dep"])],
        )
        ctx = StageContext(plan=plan)
        ctx.set_result("dep", StageResult(stage_id="dep", status="completed", query_result=dep))
        gate = DataGate()
        from app.agents.data_gate import DataGateOutcome

        outcome = DataGateOutcome()
        gate._check_cross_stage_consistency(
            _stage("s1", depends_on=["dep"]),
            StageResult(stage_id="s1", status="completed", query_result=qr),
            ctx,
            outcome,
        )
        return outcome

    def test_a_real_blow_up_is_still_reported(self):
        with patch("app.agents.data_gate.settings") as st:
            st.data_gate_cartesian_multiplier = 100
            out = self._outcome(
                QueryResult(columns=["a"], rows=[], row_count=50_000),
                QueryResult(columns=["a"], rows=[], row_count=10),
            )
        assert out.warnings, "5000x is a blow-up and must be named"

    def test_two_capped_counts_produce_no_verdict_either_way(self):
        """Both sides hit the same cap, so the ratio is ~1 and means nothing.

        Reporting "looks fine" from capped numbers is a reassuring claim that was never
        earned — the true ratio is unknowable from what is in hand.
        """
        with patch("app.agents.data_gate.settings") as st:
            st.data_gate_cartesian_multiplier = 100
            out = self._outcome(
                QueryResult(columns=["a"], rows=[], row_count=1000, truncated=True),
                QueryResult(columns=["a"], rows=[], row_count=1000, truncated=True),
            )
        assert any("truncat" in w.lower() for w in out.warnings), (
            f"the check must say it could not judge, not stay silent: {out.warnings}"
        )

    def test_a_truncated_dependency_alone_is_enough_to_withhold_the_verdict(self):
        with patch("app.agents.data_gate.settings") as st:
            st.data_gate_cartesian_multiplier = 100
            out = self._outcome(
                QueryResult(columns=["a"], rows=[], row_count=20, truncated=False),
                QueryResult(columns=["a"], rows=[], row_count=1000, truncated=True),
            )
        assert any("truncat" in w.lower() for w in out.warnings), out.warnings

    def test_untruncated_and_proportionate_stays_quiet(self):
        with patch("app.agents.data_gate.settings") as st:
            st.data_gate_cartesian_multiplier = 100
            out = self._outcome(
                QueryResult(columns=["a"], rows=[], row_count=30),
                QueryResult(columns=["a"], rows=[], row_count=10),
            )
        assert out.warnings == []
