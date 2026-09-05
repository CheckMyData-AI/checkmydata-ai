"""Truncation was the flag that made the gate skip exactly the risky results (2.4).

`ResultValidation.evaluate` returned a `warn` on truncation at step 4, **before**
step 5 ran DataGate's impossible-value checks. The module docstring's decision
table documented that order as intentional.

It is backwards. A capped result is the case most likely to carry a broken
aggregate — a percentage over 100 against a partial denominator, a count that
went negative because the window closed mid-scan. Truncation is not a reason to
relax the check; it is a reason to run it.

**And it is a universal check, so it also had to widen.** `_check_value_ranges`
looks only at columns the model named with one of 21 keywords — `percent`,
`rate`, `count`, `date` — so everything else is classified `other` and skipped
entirely.

The audit that raised this proposed a money kind, and that is **not** what ships
here. A negative revenue is not an impossible number: refunds, chargebacks and
adjustments produce one legitimately, and `block` is a hard refusal to use the
result. A gate that blocks legitimate negative revenue is a product that cannot
answer "how much did we refund". The keyword list is also already subtler than
the finding suggests — `_DELTA_KEYWORDS` demotes `percent_change` to `rate`
precisely because a delta may exceed 100 or go negative.

What ships instead is the check that needs **no** classification at all: a
non-finite number. `NaN` and `Infinity` reach a result set through a `0/0`, an
overflow, or a bad cast, and they are unusable as measures whatever the column is
called. Today they are silently treated as absent — `_check_nulls` counts a
`NaN` as a null and the parse helper turns one into `None` — so the one value
that is impossible by construction is the one nothing reports.

The gap that is deliberately left open, and recorded on the board rather than
patched: a count column not called `count`. `users`, `orders`, `sessions`,
`clicks` are all counts where a negative is genuinely impossible, and none match
a keyword. Every candidate fix is either a blocklist that the next noun defeats
or a shape heuristic that cannot tell a count from an id from a year — and a
false `block` costs a refused answer.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.agents.result_validation import ResultValidation
from app.connectors.base import QueryResult


def _qr(columns, rows, *, truncated=False, row_count=None):
    return QueryResult(
        columns=columns,
        rows=rows,
        row_count=row_count if row_count is not None else len(rows),
        truncated=truncated,
    )


@pytest.fixture
def validation():
    """The real gates, not stubs: the whole subject is which one runs first."""
    from app.agents.data_gate import DataGate
    from app.agents.validation import AgentResultValidator

    return ResultValidation(data_gate=DataGate(), result_gate=AgentResultValidator())


class TestATruncatedResultIsStillChecked:
    def test_an_impossible_percent_blocks_even_when_truncated(self, validation):
        """The defect. Both flags fire; the impossible value must win, because a
        warning about incompleteness beside a 320% conversion rate tells the
        reader the wrong thing is wrong."""
        qr = _qr(["conversion_percent"], [[320.0]], truncated=True)
        directive = validation.evaluate(qr, sql="SELECT ...", question="conversion?")
        assert directive.action == "block"

    def test_the_reason_still_names_the_truncation(self, validation):
        """Blocking must not swallow the other fact: the result is both
        impossible and partial, and a re-query needs to know both."""
        qr = _qr(["conversion_percent"], [[320.0]], truncated=True)
        directive = validation.evaluate(qr, sql="SELECT ...", question="conversion?")
        assert "partial" in directive.reason.lower() or "truncat" in directive.reason.lower()

    def test_a_clean_truncated_result_still_only_warns(self, validation):
        """The behaviour that was right stays right."""
        qr = _qr(["conversion_percent"], [[42.0]], truncated=True)
        directive = validation.evaluate(qr, sql="SELECT ...", question="conversion?")
        assert directive.action == "warn"
        assert "PARTIAL DATA" in directive.reason

    def test_an_untruncated_impossible_value_still_blocks(self, validation):
        qr = _qr(["conversion_percent"], [[320.0]])
        directive = validation.evaluate(qr, sql="SELECT ...", question="conversion?")
        assert directive.action == "block"


class TestThePipelinePathKeepsItsWarning:
    """`skip_data_gate=True` is the pipeline, which ran `DataGate.check()` on the
    full StageResult already. Reordering naively would have returned `accept`
    there and dropped the truncation warning with it — the trap in this change."""

    def test_truncation_still_warns_when_the_gate_is_skipped(self, validation):
        qr = _qr(["conversion_percent"], [[42.0]], truncated=True)
        directive = validation.evaluate(qr, sql="SELECT ...", question="q", skip_data_gate=True)
        assert directive.action == "warn"

    def test_the_gate_is_genuinely_skipped_there(self, validation):
        """An impossible value must NOT be double-blocked on that path."""
        qr = _qr(["conversion_percent"], [[320.0]])
        directive = validation.evaluate(qr, sql="SELECT ...", question="q", skip_data_gate=True)
        assert directive.action == "accept"


class TestANonFiniteNumberIsImpossibleWhateverTheColumnIsCalled:
    """The widening that needs no classifier."""

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_a_non_finite_float_blocks(self, validation, bad):
        qr = _qr(["total_revenue"], [[bad]])
        directive = validation.evaluate(qr, sql="SELECT ...", question="revenue?")
        assert directive.action == "block", (
            "a NaN or Infinity is unusable as a measure whatever the column is "
            "named, and today it is silently counted as a null instead"
        )

    def test_a_non_finite_decimal_blocks(self, validation):
        qr = _qr(["amount"], [[Decimal("NaN")]])
        directive = validation.evaluate(qr, sql="SELECT ...", question="amount?")
        assert directive.action == "block"

    def test_the_column_is_named_in_the_reason(self, validation):
        qr = _qr(["ok_col", "broken_col"], [[1, float("inf")]])
        directive = validation.evaluate(qr, sql="SELECT ...", question="q")
        assert "broken_col" in directive.reason

    def test_ordinary_numbers_are_untouched(self, validation):
        qr = _qr(["total_revenue"], [[-4_200_000], [0], [17.5]])
        directive = validation.evaluate(qr, sql="SELECT ...", question="revenue?")
        assert directive.action == "accept", (
            "a negative revenue is a refund, not an impossible number — blocking it "
            "would make the product unable to answer 'how much did we refund'"
        )

    def test_a_string_is_not_treated_as_non_finite(self, validation):
        """`"nan"` in a text column is a word, not a number. Restricting the
        check to real float/Decimal values is what keeps it false-positive-free."""
        qr = _qr(["name"], [["Nan"]])
        directive = validation.evaluate(qr, sql="SELECT ...", question="q")
        assert directive.action == "accept"


class TestTheDocumentedOrderMatchesTheCode:
    def test_the_decision_table_no_longer_puts_truncation_before_the_gate(self):
        """The table called the old order intentional. A doc that contradicts the
        code is worse than no doc, because it is read as a decision."""
        from pathlib import Path

        src = Path("app/agents/result_validation.py").read_text(encoding="utf-8")
        table = src[src.index("Decision table for") : src.index("from __future__")]
        gate_at = table.index("DataGate")
        trunc_at = table.index("truncated")
        assert gate_at < trunc_at, "the table must show the gate running first"
