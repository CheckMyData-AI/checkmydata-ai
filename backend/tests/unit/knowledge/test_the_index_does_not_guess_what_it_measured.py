"""The schema index measured fourteen currencies and advised summing them as dollars.

B-08, and the shape is the one this repository keeps finding: a measurement, a claim and
a consumer that all exist while nothing compares them.

Production, 2026-09-15, one row of `db_index` for `purchases`:

- `column_stats_json` → `currency`: ``{"distinct_count": 14, "min": "BRL", "max": "VND"}``
- `column_notes_json` → `currency`: *"Currency code, likely USD."*
- `query_hints` → *"The 'amount' column should be divided by 100 to convert from cents
  to dollars."*

Fourteen currencies counted and one guessed, written by the same run into the same row.
`amount` is minor units **of `currency`** and there is no dollar column anywhere, so a
`SUM(amount)/100` presented as dollars is wrong by whatever the currency mix happens to
be — and the agent states it confidently, because the index told it to.

The model was not the failure. `_build_table_prompt` rendered a column as
``name: type[PK][nullable][DEFAULT][comment]`` and read neither `distinct_values` nor
`distinct_count`, both of which `fetch_samples` had already written. **We measured it and
did not say it.**

Two layers, because a prompt is a request and not a guarantee — the rule
`resolve_sync_status` already states for the code↔DB map:

1. the prompt carries what was counted, so the guess has nothing to grow in;
2. a deterministic caveat goes in front of the advice, so a model that guesses anyway
   cannot have the last word.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from app.connectors.base import ColumnInfo, TableInfo
from app.knowledge.db_index_validator import (
    DbIndexValidator,
    TableAnalysis,
    apply_measured_corrections,
)

VALIDATOR = (
    pathlib.Path(__file__).resolve().parents[3] / "app" / "knowledge" / "db_index_validator.py"
)


def _col(name: str, dtype: str = "varchar", *, count: int | None = None, values=None):
    col = ColumnInfo(name=name, data_type=dtype)
    col.distinct_count = count
    col.distinct_values = values
    return col


def _purchases(currency_count: int = 14) -> TableInfo:
    """The production shape that produced the wrong advice."""
    return TableInfo(
        name="purchases",
        columns=[
            _col("currency", "varchar(3)", count=currency_count, values=["BRL", "MXN", "USD"]),
            _col("amount", "int", count=6022),
            _col("created_at", "datetime"),
        ],
        row_count=120_000,
    )


class TestThePromptCarriesWhatWasMeasured:
    def test_a_counted_column_shows_its_count(self) -> None:
        prompt = DbIndexValidator._build_table_prompt(_purchases(), None, "", "")
        assert "14 distinct" in prompt, (
            "the indexer counted this column's values and the prompt did not say so — "
            "which is how 'likely USD' was written about fourteen currencies"
        )
        assert "BRL" in prompt and "USD" in prompt

    def test_an_unmeasured_column_says_nothing(self) -> None:
        """Silence, not "0 values" or "unknown". A column the sampler skipped and a
        column with no values are different facts, and only one of them is a fact about
        the data."""
        prompt = DbIndexValidator._build_table_prompt(_purchases(), None, "", "")
        created = next(line for line in prompt.splitlines() if "created_at" in line)
        assert "measured" not in created

    def test_a_long_value_list_is_summarised_rather_than_dumped(self) -> None:
        """Above the cap the list stops being evidence and becomes a sample of a sample."""
        many = [f"V{i}" for i in range(40)]
        table = TableInfo(name="t", columns=[_col("status", count=40, values=many)], row_count=10)
        prompt = DbIndexValidator._build_table_prompt(table, None, "", "")
        assert "40 distinct" in prompt
        assert "…" in prompt
        assert "V39" not in prompt


class TestTheCaveatOutranksTheAdvice:
    def _analysis(self, hints: str) -> TableAnalysis:
        return TableAnalysis(table_name="purchases", query_hints=hints)

    def test_the_measured_currency_count_goes_in_front_of_the_advice(self) -> None:
        wrong = "The 'amount' column should be divided by 100 to convert from cents to dollars."
        out = apply_measured_corrections(self._analysis(wrong), _purchases())
        assert out.query_hints.startswith("MEASURED:")
        assert "14 distinct values" in out.query_hints
        assert "`amount`" in out.query_hints
        assert wrong in out.query_hints, (
            "the caveat is additive — rewriting generated prose by pattern is how a "
            "correct sentence gets corrupted by a guard aimed at a different one"
        )

    def test_a_single_currency_table_is_left_alone(self) -> None:
        """One measured value is not a mix, and a caveat about it would be noise on a
        rail where noise is what makes the real warning ignorable."""
        out = apply_measured_corrections(self._analysis("hint"), _purchases(currency_count=1))
        assert out.query_hints == "hint"

    def test_an_unmeasured_currency_column_is_left_alone(self) -> None:
        """The guard stands on a measurement or it does not fire. Asserting a mix the
        sampler never counted would be the same defect facing the other way."""
        table = TableInfo(
            name="purchases",
            columns=[_col("currency", "varchar(3)"), _col("amount", "int")],
            row_count=10,
        )
        assert apply_measured_corrections(self._analysis("hint"), table).query_hints == "hint"

    def test_a_table_with_no_money_column_is_left_alone(self) -> None:
        table = TableInfo(
            name="settings",
            columns=[_col("currency", "varchar(3)", count=14), _col("label", "varchar")],
            row_count=10,
        )
        assert apply_measured_corrections(self._analysis("hint"), table).query_hints == "hint"

    @pytest.mark.parametrize("name", ["currency", "currency_code", "ccy", "settlement_currency"])
    def test_the_unit_column_is_recognised_by_its_name(self, name: str) -> None:
        table = TableInfo(
            name="t", columns=[_col(name, count=3), _col("total", "int")], row_count=9
        )
        assert apply_measured_corrections(self._analysis(""), table).query_hints.startswith(
            "MEASURED:"
        )

    def test_a_rate_column_is_not_a_unit_column(self) -> None:
        """`currency_rate` holds a number, not a unit, and matching it as a substring
        would fire the caveat on tables that have no currency mix at all."""
        table = TableInfo(
            name="t", columns=[_col("currency_rate", count=50), _col("amount", "int")], row_count=9
        )
        assert apply_measured_corrections(self._analysis("hint"), table).query_hints == "hint"

    def test_applying_it_twice_does_not_stack_the_caveat(self) -> None:
        once = apply_measured_corrections(self._analysis("hint"), _purchases())
        twice = apply_measured_corrections(once, _purchases())
        assert twice.query_hints.count("MEASURED:") == 1


def test_every_path_that_builds_an_analysis_passes_through_the_corrector() -> None:
    """Two sites build a `TableAnalysis` from a tool call — the single-table path and the
    batch — and a guard on one of two writers is a shape this repository has been caught
    by before. Walked rather than asserted, so a third site cannot appear unnoticed."""
    tree = ast.parse(VALIDATOR.read_text(encoding="utf-8"))
    built_from_args: list[int] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id != "TableAnalysis":
            continue
        rendered = ast.unparse(node)
        if "args.get" not in rendered:
            continue  # the deterministic fallback builds one too, from no model output
        built_from_args.append(node.lineno)

    assert len(built_from_args) >= 2, (
        "fewer than two model-derived analyses found — the walker has stopped measuring"
    )
    source = VALIDATOR.read_text(encoding="utf-8").splitlines()
    for lineno in built_from_args:
        window = "\n".join(source[max(0, lineno - 4) : lineno])
        assert "apply_measured_corrections" in window, (
            f"db_index_validator.py:{lineno} builds a TableAnalysis from a tool call "
            "without passing it through apply_measured_corrections"
        )
