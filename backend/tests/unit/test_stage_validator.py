"""Unit tests for StageValidator."""

import pytest

from app.agents.stage_context import (
    ExecutionPlan,
    PlanStage,
    StageContext,
    StageResult,
    StageValidation,
)
from app.agents.stage_validator import StageValidationOutcome, StageValidator
from app.connectors.base import QueryResult


@pytest.fixture
def validator():
    return StageValidator()


def _make_plan(*stages: PlanStage) -> ExecutionPlan:
    return ExecutionPlan(
        plan_id="test-plan",
        question="test question",
        stages=list(stages),
    )


def _make_stage(stage_id="s1", validation=None, **kwargs) -> PlanStage:
    return PlanStage(
        stage_id=stage_id,
        description="test stage",
        tool="query_database",
        validation=validation or StageValidation(),
        **kwargs,
    )


def _make_result(stage_id="s1", status="success", qr=None, error=None) -> StageResult:
    return StageResult(
        stage_id=stage_id,
        status=status,
        query_result=qr,
        error=error,
    )


class TestStageValidationOutcome:
    def test_initial_state(self):
        outcome = StageValidationOutcome()
        assert outcome.passed is True
        assert outcome.warnings == []
        assert outcome.errors == []
        assert outcome.error_summary == ""

    def test_fail(self):
        outcome = StageValidationOutcome()
        outcome.fail("something broke")
        assert outcome.passed is False
        assert "something broke" in outcome.error_summary

    def test_warn(self):
        outcome = StageValidationOutcome()
        outcome.warn("just a warning")
        assert outcome.passed is True
        assert "just a warning" in outcome.warnings

    def test_to_dict(self):
        outcome = StageValidationOutcome()
        outcome.warn("w1")
        outcome.fail("e1")
        d = outcome.to_dict()
        assert d["passed"] is False
        assert "w1" in d["warnings"]
        assert "e1" in d["errors"]


class TestValidateBasic:
    def test_error_stage_fails(self, validator):
        stage = _make_stage()
        result = _make_result(status="error", error="SQL syntax error")
        ctx = StageContext(plan=_make_plan(stage))

        outcome = validator.validate(stage, result, ctx)
        assert outcome.passed is False
        assert "SQL syntax error" in outcome.error_summary

    def test_success_with_no_validation(self, validator):
        stage = _make_stage()
        qr = QueryResult(columns=["id", "name"], rows=[[1, "a"]], row_count=1)
        result = _make_result(qr=qr)
        ctx = StageContext(plan=_make_plan(stage))

        outcome = validator.validate(stage, result, ctx)
        assert outcome.passed is True
        assert outcome.warnings == []

    def test_missing_expected_columns(self, validator):
        stage = _make_stage(
            validation=StageValidation(expected_columns=["id", "missing_col"]),
        )
        qr = QueryResult(columns=["id", "name"], rows=[[1, "a"]], row_count=1)
        result = _make_result(qr=qr)
        ctx = StageContext(plan=_make_plan(stage))

        outcome = validator.validate(stage, result, ctx)
        assert outcome.passed is False
        assert "missing_col" in outcome.error_summary


class TestMinMaxRows:
    def test_min_rows_warning(self, validator):
        stage = _make_stage(validation=StageValidation(min_rows=5))
        qr = QueryResult(columns=["id"], rows=[[1]], row_count=1)
        result = _make_result(qr=qr)
        ctx = StageContext(plan=_make_plan(stage))

        outcome = validator.validate(stage, result, ctx)
        assert outcome.passed is True
        assert any("at least 5 rows" in w for w in outcome.warnings)

    def test_max_rows_warning(self, validator):
        stage = _make_stage(validation=StageValidation(max_rows=2))
        qr = QueryResult(columns=["id"], rows=[[1], [2], [3]], row_count=3)
        result = _make_result(qr=qr)
        ctx = StageContext(plan=_make_plan(stage))

        outcome = validator.validate(stage, result, ctx)
        assert outcome.passed is True
        assert any("at most 2" in w for w in outcome.warnings)


class TestBusinessRules:
    def test_no_negative_detects_violation(self, validator):
        stage = _make_stage(
            validation=StageValidation(business_rules=["Ensure no negative values"]),
        )
        qr = QueryResult(
            columns=["amount", "count"],
            rows=[[100, 5], [-50, 3]],
            row_count=2,
        )
        result = _make_result(qr=qr)
        ctx = StageContext(plan=_make_plan(stage))

        outcome = validator.validate(stage, result, ctx)
        assert any("negative" in w.lower() for w in outcome.warnings)

    def test_no_negative_passes_clean_data(self, validator):
        stage = _make_stage(
            validation=StageValidation(business_rules=["Ensure no negative values"]),
        )
        qr = QueryResult(
            columns=["amount"],
            rows=[[100], [200], [0]],
            row_count=3,
        )
        result = _make_result(qr=qr)
        ctx = StageContext(plan=_make_plan(stage))

        outcome = validator.validate(stage, result, ctx)
        assert outcome.warnings == []

    def test_no_negative_skips_ragged_row(self, validator):
        stage = _make_stage(
            validation=StageValidation(business_rules=["Ensure no negative values"]),
        )
        qr = QueryResult(
            columns=["a", "b"],
            rows=[[1, 2], [3]],
            row_count=2,
        )
        result = _make_result(qr=qr)
        ctx = StageContext(plan=_make_plan(stage))
        outcome = validator.validate(stage, result, ctx)
        assert outcome.passed is True

    def test_no_rows_skips_business_rules(self, validator):
        stage = _make_stage(
            validation=StageValidation(business_rules=["Ensure no negative values"]),
        )
        qr = QueryResult(columns=["amount"], rows=[], row_count=0)
        result = _make_result(qr=qr)
        ctx = StageContext(plan=_make_plan(stage))

        outcome = validator.validate(stage, result, ctx)
        assert outcome.warnings == []


class TestCrossStageChecks:
    def test_unrecognised_format(self, validator):
        stage = _make_stage(
            validation=StageValidation(cross_stage_checks=["not a valid pattern"]),
        )
        result = _make_result()
        ctx = StageContext(plan=_make_plan(stage))

        outcome = validator.validate(stage, result, ctx)
        assert outcome.passed is True
        assert outcome.warnings == []

    def test_missing_referenced_stage(self, validator):
        stage = _make_stage(
            validation=StageValidation(
                cross_stage_checks=["row_count <= other_stage.row_count"],
            ),
        )
        qr = QueryResult(columns=["id"], rows=[[1]], row_count=1)
        result = _make_result(qr=qr)
        ctx = StageContext(plan=_make_plan(stage))

        outcome = validator.validate(stage, result, ctx)
        assert outcome.passed is True

    def test_cross_check_passes(self, validator):
        s1 = _make_stage(stage_id="s1")
        s2 = _make_stage(
            stage_id="s2",
            validation=StageValidation(
                cross_stage_checks=["row_count <= s1.row_count"],
            ),
        )
        qr1 = QueryResult(columns=["id"], rows=[[1], [2]], row_count=2)
        qr2 = QueryResult(columns=["id"], rows=[[1]], row_count=1)

        ctx = StageContext(plan=_make_plan(s1, s2))
        ctx.set_result("s1", _make_result(stage_id="s1", qr=qr1))

        result = _make_result(stage_id="s2", qr=qr2)
        outcome = validator.validate(s2, result, ctx)
        assert outcome.passed is True
        assert outcome.warnings == []

    def test_cross_check_fails(self, validator):
        s1 = _make_stage(stage_id="s1")
        s2 = _make_stage(
            stage_id="s2",
            validation=StageValidation(
                cross_stage_checks=["row_count <= s1.row_count"],
            ),
        )
        qr1 = QueryResult(columns=["id"], rows=[[1]], row_count=1)
        qr2 = QueryResult(columns=["id"], rows=[[1], [2], [3]], row_count=3)

        ctx = StageContext(plan=_make_plan(s1, s2))
        ctx.set_result("s1", _make_result(stage_id="s1", qr=qr1))

        result = _make_result(stage_id="s2", qr=qr2)
        outcome = validator.validate(s2, result, ctx)
        assert any("Cross-stage check failed" in w for w in outcome.warnings)

    def test_cross_check_with_multiplier(self, validator):
        s1 = _make_stage(stage_id="s1")
        s2 = _make_stage(
            stage_id="s2",
            validation=StageValidation(
                cross_stage_checks=["row_count <= s1.row_count * 2"],
            ),
        )
        qr1 = QueryResult(columns=["id"], rows=[[1]], row_count=1)
        qr2 = QueryResult(columns=["id"], rows=[[1], [2], [3]], row_count=3)

        ctx = StageContext(plan=_make_plan(s1, s2))
        ctx.set_result("s1", _make_result(stage_id="s1", qr=qr1))

        result = _make_result(stage_id="s2", qr=qr2)
        outcome = validator.validate(s2, result, ctx)
        assert any("Cross-stage check failed" in w for w in outcome.warnings)
