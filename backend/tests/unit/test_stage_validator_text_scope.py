"""Tests for ORCH-P01: text stages validated on non-empty summary.

Data criteria (expected_columns/min_rows/max_rows) must be ignored for
text-producing stages; those stages are validated on non-empty summary instead.
"""

from __future__ import annotations

import pytest

from app.agents.stage_context import (
    ExecutionPlan,
    PlanStage,
    StageContext,
    StageResult,
    StageValidation,
)
from app.agents.stage_validator import (
    _TEXT_STAGE_TOOLS,
    StageValidator,
)
from app.connectors.base import QueryResult


@pytest.fixture
def validator() -> StageValidator:
    return StageValidator()


def _make_ctx(plan_id: str = "p1") -> StageContext:
    plan = ExecutionPlan(plan_id=plan_id, question="q", stages=[])
    ctx = StageContext(plan=plan)
    return ctx


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _text_stage(
    stage_id: str = "s1",
    tool: str = "search_codebase",
    validation: StageValidation | None = None,
) -> PlanStage:
    return PlanStage(
        stage_id=stage_id,
        description="text stage",
        tool=tool,
        validation=validation or StageValidation(),
    )


def _text_result(
    stage_id: str = "s1",
    summary: str = "",
    status: str = "success",
) -> StageResult:
    return StageResult(
        stage_id=stage_id,
        status=status,
        query_result=None,
        summary=summary,
    )


def _data_stage(
    stage_id: str = "d1",
    tool: str = "query_database",
    validation: StageValidation | None = None,
) -> PlanStage:
    return PlanStage(
        stage_id=stage_id,
        description="data stage",
        tool=tool,
        validation=validation or StageValidation(),
    )


def _data_result(
    stage_id: str = "d1",
    rows: list | None = None,
    columns: list[str] | None = None,
) -> StageResult:
    columns = columns or ["id", "value"]
    rows = rows or [[1, "a"]]
    qr = QueryResult(columns=columns, rows=rows)
    return StageResult(stage_id=stage_id, status="success", query_result=qr)


# ---------------------------------------------------------------------------
# _TEXT_STAGE_TOOLS module-level constant
# ---------------------------------------------------------------------------


def test_text_stage_tools_constant_exists() -> None:
    """_TEXT_STAGE_TOOLS must be a frozenset/set at module scope."""
    assert _TEXT_STAGE_TOOLS, "constant must not be empty"
    assert "search_codebase" in _TEXT_STAGE_TOOLS
    assert "analyze_git" in _TEXT_STAGE_TOOLS
    assert "analyze_results" in _TEXT_STAGE_TOOLS
    assert "synthesize" in _TEXT_STAGE_TOOLS


# ---------------------------------------------------------------------------
# Text stage: empty summary → FAIL (regression — today this passes silently)
# ---------------------------------------------------------------------------


def test_text_stage_empty_summary_fails(validator: StageValidator) -> None:
    """A text stage with an empty summary must not pass validation."""
    stage = _text_stage(
        tool="search_codebase",
        validation=StageValidation(min_rows=5),  # planner-invited data criterion
    )
    result = _text_result(summary="", status="success")
    ctx = _make_ctx()

    outcome = validator.validate(stage, result, ctx)

    assert outcome.passed is False, "empty-summary text stage should FAIL"
    assert any("empty" in err.lower() for err in outcome.errors), (
        f"error should mention 'empty'; got errors={outcome.errors}"
    )


# ---------------------------------------------------------------------------
# Text stage: non-empty summary → PASS; data criteria ignored
# ---------------------------------------------------------------------------


def test_text_stage_nonempty_summary_passes(validator: StageValidator) -> None:
    """A text stage with a non-empty summary passes; min_rows is ignored."""
    stage = _text_stage(
        tool="search_codebase",
        validation=StageValidation(min_rows=5),  # data criterion — must be IGNORED
    )
    result = _text_result(summary="Found the caching module.", status="success")
    ctx = _make_ctx()

    outcome = validator.validate(stage, result, ctx)

    assert outcome.passed is True, "non-empty summary text stage should PASS"
    # min_rows=5 must NOT generate a spurious "expected at least 5 rows" warning
    assert not any("row" in w.lower() for w in outcome.warnings), (
        f"data-criteria warnings must be absent for text stage; got warnings={outcome.warnings}"
    )
    assert not any("row" in e.lower() for e in outcome.errors), (
        f"data-criteria errors must be absent for text stage; got errors={outcome.errors}"
    )


# ---------------------------------------------------------------------------
# All text tools are covered
# ---------------------------------------------------------------------------


_ALL_TEXT_TOOLS = ["search_codebase", "analyze_git", "analyze_results", "synthesize"]


@pytest.mark.parametrize("tool", _ALL_TEXT_TOOLS)
def test_all_text_tools_empty_summary_fails(validator: StageValidator, tool: str) -> None:
    """Every tool in _TEXT_STAGE_TOOLS must fail on empty summary."""
    stage = _text_stage(tool=tool)
    result = _text_result(summary="", status="success")
    ctx = _make_ctx()

    outcome = validator.validate(stage, result, ctx)

    assert outcome.passed is False, f"tool={tool}: empty summary should FAIL"


@pytest.mark.parametrize("tool", _ALL_TEXT_TOOLS)
def test_all_text_tools_nonempty_summary_passes(validator: StageValidator, tool: str) -> None:
    """Every tool in _TEXT_STAGE_TOOLS must pass with a non-empty summary."""
    stage = _text_stage(tool=tool, validation=StageValidation(min_rows=10, max_rows=1))
    result = _text_result(summary="Some analysis here.", status="success")
    ctx = _make_ctx()

    outcome = validator.validate(stage, result, ctx)

    assert outcome.passed is True, f"tool={tool}: non-empty summary should PASS"


# ---------------------------------------------------------------------------
# Data stage path unchanged (regression guard)
# ---------------------------------------------------------------------------


def test_data_stage_still_uses_row_criteria(validator: StageValidator) -> None:
    """query_database stage with min_rows=5 and 2-row result → warns (not fails by default)."""
    stage = _data_stage(
        tool="query_database",
        validation=StageValidation(min_rows=5),
    )
    result = _data_result(rows=[[1, "a"], [2, "b"]])  # only 2 rows
    ctx = _make_ctx()

    outcome = validator.validate(stage, result, ctx)

    # Non-strict mode → warning not hard fail
    assert any("row" in w.lower() for w in outcome.warnings), (
        f"data stage should WARN about row count; got warnings={outcome.warnings}"
    )


def test_data_stage_strict_row_criteria_fails() -> None:
    """In strict mode a query_database stage with too few rows hard-fails."""
    strict_validator = StageValidator(strict_row_bounds=True)
    stage = _data_stage(
        tool="query_database",
        validation=StageValidation(min_rows=5),
    )
    result = _data_result(rows=[[1, "a"]])  # 1 row
    ctx = _make_ctx()

    outcome = strict_validator.validate(stage, result, ctx)

    assert outcome.passed is False, "strict data stage should FAIL on too few rows"


def test_data_stage_expected_columns_validated(validator: StageValidator) -> None:
    """query_database expected_columns check still fires."""
    stage = _data_stage(
        tool="query_database",
        validation=StageValidation(expected_columns=["id", "revenue"]),
    )
    result = _data_result(columns=["id", "value"])  # "revenue" missing
    ctx = _make_ctx()

    outcome = validator.validate(stage, result, ctx)

    assert outcome.passed is False
    assert any("revenue" in e.lower() for e in outcome.errors)


def test_text_stage_error_status_still_fails(validator: StageValidator) -> None:
    """status=error short-circuits before text-stage path — unchanged."""
    stage = _text_stage(tool="analyze_git")
    result = _text_result(summary="Has content", status="error")
    # Inject an error value since StageResult with status=error uses .error field
    result.error = "git clone failed"
    ctx = _make_ctx()

    outcome = validator.validate(stage, result, ctx)

    assert outcome.passed is False
