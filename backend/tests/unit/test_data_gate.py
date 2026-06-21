"""Unit tests for DataGate, focused on the C4 (v1.13.0) hard-vs-soft
classification: hard data-quality errors must invoke ``fail()`` so the
stage retries; soft anomalies remain warnings.

Parametrized to cover the matrix of column kinds × value-range outcomes."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.agents.data_gate import DataGate, DataGateOutcome
from app.agents.stage_context import ExecutionPlan, PlanStage, StageContext, StageResult
from app.connectors.base import QueryResult


def _make_stage_ctx(plan: ExecutionPlan) -> StageContext:
    return StageContext(plan=plan)


def _sql_stage(stage_id: str = "s1") -> PlanStage:
    return PlanStage(stage_id=stage_id, description="x", tool="query_database")


class TestOutcomeMechanics:
    def test_warn_keeps_passed_true(self):
        out = DataGateOutcome()
        out.warn("soft issue")
        assert out.passed is True
        assert out.warnings == ["soft issue"]

    def test_fail_flips_passed_false(self):
        out = DataGateOutcome()
        out.fail("hard issue", suggestion="fix it")
        assert out.passed is False
        assert out.errors == ["hard issue"]
        assert out.suggestions == ["fix it"]


class TestHardChecksValueRange:
    @pytest.mark.parametrize(
        "col_name, value, expected_fail",
        [
            # Hard: percent value clearly out of range
            ("revenue_pct", 9999.0, True),
            ("share_ratio", -50.0, True),
            # Soft: percent within bounds
            ("growth_rate", 25.0, False),
            # Hard: date in obviously wrong year
            ("created_date", "1800-01-01", True),
            ("updated_at", "2300-12-31", True),
            # Soft: date within bounds
            ("event_date", "2024-06-15", False),
            # Non-classified column — never fails
            ("user_count", 1_000_000, False),
        ],
    )
    def test_out_of_range_classification(self, col_name, value, expected_fail):
        gate = DataGate()
        qr = QueryResult(
            columns=[col_name],
            rows=[[value]],
            row_count=1,
        )
        stage = _sql_stage()
        plan = ExecutionPlan(plan_id="p", question="q", stages=[stage])
        ctx = _make_stage_ctx(plan)
        result = StageResult(stage_id=stage.stage_id, status="success", query_result=qr)

        out = gate.check(stage, result, ctx)

        if expected_fail:
            assert out.passed is False
            assert out.errors, "expected hard failure but got no errors"
        else:
            assert out.passed is True


class TestSoftChecksRemainWarn:
    def test_high_null_ratio_only_warns(self):
        """Soft signal — could be legitimate data shape."""
        gate = DataGate(null_threshold=0.5)
        qr = QueryResult(
            columns=["maybe_null"],
            rows=[[None], [None], [None], ["x"]],
            row_count=4,
        )
        stage = _sql_stage()
        plan = ExecutionPlan(plan_id="p", question="q", stages=[stage])
        ctx = _make_stage_ctx(plan)
        result = StageResult(stage_id=stage.stage_id, status="success", query_result=qr)

        out = gate.check(stage, result, ctx)

        assert out.passed is True
        assert any("null/empty" in w for w in out.warnings)

    def test_duplicate_ratio_only_warns(self):
        gate = DataGate(duplicate_threshold=0.5)
        qr = QueryResult(
            columns=["x"],
            rows=[[1], [1], [1], [2]],
            row_count=4,
        )
        stage = _sql_stage()
        plan = ExecutionPlan(plan_id="p", question="q", stages=[stage])
        ctx = _make_stage_ctx(plan)
        result = StageResult(stage_id=stage.stage_id, status="success", query_result=qr)

        out = gate.check(stage, result, ctx)

        assert out.passed is True
        assert any("duplicate" in w for w in out.warnings)


class TestHardChecksToggle:
    def test_setting_disabled_reverts_to_warn(self):
        """C4: when DATA_GATE_HARD_CHECKS_ENABLED=false, the previously-hard
        cases must revert to warn() — guarantees a safe rollback path."""
        from app.agents import data_gate as dg_mod

        gate = DataGate()
        qr = QueryResult(
            columns=["revenue_pct"],
            rows=[[9999.0]],
            row_count=1,
        )
        stage = _sql_stage()
        plan = ExecutionPlan(plan_id="p", question="q", stages=[stage])
        ctx = _make_stage_ctx(plan)
        result = StageResult(stage_id=stage.stage_id, status="success", query_result=qr)

        with patch.object(dg_mod.settings, "data_gate_hard_checks_enabled", False):
            out = gate.check(stage, result, ctx)

        assert out.passed is True
        assert any("out of range" in w for w in out.warnings)


class TestStageRetryIntegration:
    """Confirms the wiring: DataGate.fail() → StageExecutor sees
    gate_outcome.passed == False → triggers retry path."""

    def test_failed_outcome_flips_passed_to_false(self):
        out = DataGateOutcome()
        out.fail("bad data")
        assert out.passed is False
        # error_summary is what StageExecutor surfaces in the replan error
        assert out.error_summary == "bad data"

    def test_merge_failed_outcome_propagates(self):
        a = DataGateOutcome()
        b = DataGateOutcome()
        b.fail("bad")
        a.merge(b)
        assert a.passed is False


class TestEpochIntDates:
    """I7: epoch timestamps arriving as int/float must be range-checked too."""

    def test_nonsense_epoch_int_is_flagged(self):
        # 10**20 is implausible as both epoch seconds and epoch ms.
        qr = QueryResult(columns=["created_at"], rows=[[10**20]], row_count=1)
        gate = DataGate()
        outcome = DataGateOutcome()
        gate._check_value_ranges(qr, outcome)
        assert outcome.errors or outcome.warnings

    def test_valid_epoch_seconds_not_flagged(self):
        # 1700000000 -> 2023-11, a plausible epoch-seconds timestamp.
        qr = QueryResult(columns=["created_at"], rows=[[1700000000]], row_count=1)
        gate = DataGate()
        outcome = DataGateOutcome()
        gate._check_value_ranges(qr, outcome)
        assert not outcome.errors and not outcome.warnings
