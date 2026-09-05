"""A `NUMERIC` column contained no numbers, as far as three subsystems knew.

Board row 2.7 asked for "Decimal in the loss/opportunity detectors". Reading the
sites showed the row's premise was the smaller half. Precision was never the
problem: the detectors compare SQL aggregates the database already summed, and
render them through `:,.0f`. The problem is that

    isinstance(val, (int, float))

is **False for `Decimal`**, which is what `asyncpg` returns for a Postgres
`NUMERIC` and what `connectors/mongodb.py:134` deliberately converts
`Decimal128` into, "like asyncpg's numeric results". So `_extract_numeric`
returned an empty list for a revenue column and the loss detector reported
nothing — on exactly the columns it exists to watch.

The same guard is `True` for `bool`, which subclasses `int`, so a flag column
averages as a measurement.

`app/agents/data_gate.py:448` already had it right —
`isinstance(val, (int, float, Decimal)) and not isinstance(val, bool)` — three
files away. The pattern was present and understood and simply not applied, which
is the fourth time this programme has written that sentence. Hence one shared
leaf (`app/core/numeric.py`) rather than a fifth correct copy.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.numeric import is_measurement, to_number


class TestTheSharedPredicate:
    @pytest.mark.parametrize("value", [1, 1.5, Decimal("48213.55"), Decimal("0"), 0, -3])
    def test_numbers_are_measurements(self, value):
        assert is_measurement(value) is True
        assert to_number(value) is not None

    def test_decimal_is_the_whole_point(self):
        """asyncpg's NUMERIC and Mongo's Decimal128 both arrive as this type."""
        assert is_measurement(Decimal("48213.55")) is True
        assert to_number(Decimal("48213.55")) == pytest.approx(48213.55)

    @pytest.mark.parametrize("value", [True, False])
    def test_a_flag_is_not_a_measurement(self, value):
        """`bool` subclasses `int`, so the naive guard averages `is_active`."""
        assert is_measurement(value) is False
        assert to_number(value) is None

    @pytest.mark.parametrize("value", [None, "12", "", [], {}, object()])
    def test_non_numbers_are_refused(self, value):
        assert is_measurement(value) is False
        assert to_number(value) is None

    def test_nan_is_refused_in_both_spellings(self):
        assert is_measurement(float("nan")) is False
        assert is_measurement(Decimal("NaN")) is False

    def test_signalling_nan_does_not_escape_as_an_exception(self):
        """`Decimal('sNaN')` raises on comparison rather than comparing unequal,
        so the naive `val == val` test is not enough on its own."""
        assert to_number(Decimal("sNaN")) is None

    def test_a_decimal_beyond_float_range_becomes_inf_rather_than_raising(self):
        """Pins the measurement that removed a handler. The first draft caught
        `OverflowError` here on the belief that an out-of-range `Decimal` raises.
        It does not — it returns `inf` — so the handler could only have swallowed
        a real defect."""
        assert to_number(Decimal("1e400")) == float("inf")

    def test_infinity_passes_and_that_is_recorded_not_accidental(self):
        """Every call site already accepted it. Changing that silently, beside
        two fixes that have evidence, would make the change unreviewable."""
        assert is_measurement(float("inf")) is True


class TestTheLossDetectorSeesMoney:
    def test_a_numeric_revenue_column_is_extracted(self):
        """The defect, at the site the board row named."""
        from app.core.loss_detector import LossDetector

        rows = [{"revenue": Decimal("100.00")}, {"revenue": Decimal("42.50")}]
        assert LossDetector._extract_numeric(rows, "revenue") == [100.0, 42.5]

    def test_a_boolean_column_is_not_read_as_one_and_zero(self):
        from app.core.loss_detector import LossDetector

        rows = [{"is_active": True}, {"is_active": False}]
        assert LossDetector._extract_numeric(rows, "is_active") == []

    def test_to_number_accepts_decimal(self):
        from app.core.loss_detector import LossDetector

        assert LossDetector._to_number(Decimal("7.25")) == pytest.approx(7.25)


class TestTheOpportunityDetectorSeesMoney:
    def test_a_numeric_column_is_extracted(self):
        from app.core.opportunity_detector import OpportunityDetector

        rows = [{"spend": Decimal("1000")}, {"spend": Decimal("2000")}]
        assert OpportunityDetector._extract_numeric(rows, "spend") == [1000.0, 2000.0]

    def test_a_boolean_column_is_refused(self):
        from app.core.opportunity_detector import OpportunityDetector

        assert OpportunityDetector._extract_numeric([{"flag": True}], "flag") == []


class TestATotalGetsTheNumberCard:
    """`SELECT count(*)` returned a number card and `SELECT sum(revenue)` did
    not, because one is `int` and the other is `Decimal`. The product told the
    reader that counts are numbers and money is prose."""

    def _single_cell(self, value):
        from app.connectors.base import QueryResult

        return QueryResult(columns=["total"], rows=[[value]], row_count=1)

    def test_an_integer_total_renders_as_a_number(self):
        """The control: this half always worked."""
        from app.agents.viz_agent import VizAgent

        result = VizAgent._edge_case_fallback(self._single_cell(42))
        assert result is not None and result.viz_type == "number"

    def test_a_decimal_total_renders_as_a_number_too(self):
        from app.agents.viz_agent import VizAgent

        result = VizAgent._edge_case_fallback(self._single_cell(Decimal("48213.55")))
        assert result is not None and result.viz_type == "number", (
            "a money total fell through to viz_type='text', so asking for total "
            "revenue produced prose where a count produces a number card"
        )

    def test_a_boolean_cell_is_still_text(self):
        """Not a regression to guard against — a deliberate consequence of
        refusing flags: `SELECT is_active` is not a metric."""
        from app.agents.viz_agent import VizAgent

        result = VizAgent._edge_case_fallback(self._single_cell(True))
        assert result is not None and result.viz_type == "text"


class TestTheNegativeValueRuleActuallyFires:
    """A validation rule that reports itself as checked while checking nothing.

    `StageValidator`'s business rule "no negative values" tested
    `isinstance(val, (int, float)) and val < 0`, so on a Postgres NUMERIC column
    — a money column, the one the rule exists for — it never fired. Same shape as
    the required-filter guard already recorded in CLAUDE.md: a check reporting a
    pass it never performed.
    """

    def _validate(self, value):
        from app.agents.stage_context import (
            ExecutionPlan,
            PlanStage,
            StageContext,
            StageResult,
            StageValidation,
        )
        from app.agents.stage_validator import StageValidator
        from app.connectors.base import QueryResult

        stage = PlanStage(
            stage_id="s1",
            description="totals",
            tool="query_database",
            validation=StageValidation(business_rules=["no negative values"]),
        )
        result = StageResult(
            stage_id="s1",
            summary="ok",
            query_result=QueryResult(columns=["amount"], rows=[[value]], row_count=1),
        )
        ctx = StageContext(plan=ExecutionPlan(plan_id="p", question="q", stages=[stage]))
        return StageValidator().validate(stage, result, ctx)

    def test_a_negative_float_is_caught(self):
        """The control: this half always worked."""
        outcome = self._validate(-5.0)
        assert any("negative value" in w for w in outcome.warnings)

    def test_a_negative_decimal_is_caught_too(self):
        from decimal import Decimal

        outcome = self._validate(Decimal("-5.00"))
        assert any("negative value" in w for w in outcome.warnings), (
            "the rule never fired on a NUMERIC column, while reporting itself as checked"
        )

    def test_a_positive_decimal_is_not_flagged(self):
        from decimal import Decimal

        outcome = self._validate(Decimal("5.00"))
        assert not any("negative value" in w for w in outcome.warnings)
