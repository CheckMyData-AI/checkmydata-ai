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

_KNOWLEDGE = pathlib.Path(__file__).resolve().parents[3] / "app" / "knowledge"
VALIDATOR = _KNOWLEDGE / "db_index_validator.py"
PIPELINE = _KNOWLEDGE / "db_index_pipeline.py"


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


def test_every_analysis_that_reaches_storage_passes_through_the_corrector() -> None:
    """The guard moved, and the move is the finding.

    Its first version walked `db_index_validator` and required every `TableAnalysis`
    built **from a tool call** to be corrected. Both such sites were — and
    `purchases.column_notes_json` still read "Currency code, likely USD" after the fix
    shipped, because there is a THIRD builder: a table whose column signature has not
    changed has its whole analysis cloned from the stored `db_index` row (R2-3), and that
    one is built from a database row rather than from a model.

    So the guard watches the place every analysis passes through instead of the places
    they come from. `db_index_pipeline` stores them in one loop; if that loop can reach
    `_svc.store_results`-bound `table_data` without the correction, a fourth builder will
    be silently uncovered the same way.
    """
    tree = ast.parse(PIPELINE.read_text(encoding="utf-8"))

    def _builds_the_stored_row(fn: ast.AST) -> bool:
        """A dict literal with a `query_hints` KEY is the row handed to `store_results`.

        Keyed on the literal rather than on the name: `_build_reuse_map` also mentions
        `query_hints`, as a keyword argument cloning a stored row, and it must NOT be
        corrected there — it runs before `fetch_samples`, so there is nothing measured
        for a correction to read.
        """
        return any(
            isinstance(node, ast.Dict)
            and any(isinstance(k, ast.Constant) and k.value == "query_hints" for k in node.keys)
            for node in ast.walk(fn)
        )

    functions = [
        fn
        for fn in ast.walk(tree)
        if isinstance(fn, ast.AsyncFunctionDef | ast.FunctionDef) and _builds_the_stored_row(fn)
    ]
    assert functions, "no function builds the stored row — the walk has stopped measuring"
    for fn in functions:
        body = ast.unparse(fn)
        assert "apply_measured_corrections" in body, (
            f"{fn.name} builds the row that is stored in `db_index` without passing the "
            "analysis through apply_measured_corrections — a reused or future third-party "
            "analysis would carry whatever prose it arrived with"
        )


def test_the_caveat_is_rebuilt_rather_than_stacked() -> None:
    """A reused analysis arrives carrying the caveat a previous run added.

    Without the strip, a table that survives twenty nights unchanged accumulates twenty
    copies of the same warning, each quoting a total from a different month — and the
    hints field grows without bound while saying the same thing.
    """
    analysis = TableAnalysis(table_name="purchases", query_hints="Use was_handled = 1.")
    once = apply_measured_corrections(analysis, _purchases())
    twice = apply_measured_corrections(once, _purchases())
    thrice = apply_measured_corrections(twice, _purchases())
    assert thrice.query_hints.count("MEASURED:") == 1
    assert "Use was_handled = 1." in thrice.query_hints


def test_the_model_s_own_prose_is_never_edited() -> None:
    """Only whole lines beginning with the prefix are dropped. A sentence the model wrote
    that happens to contain the word is prose, and prose is not the stripper's to edit."""
    from app.knowledge.db_index_validator import strip_measured_lines

    prose = "Nothing here is MEASURED: the column is undocumented."
    assert strip_measured_lines(f"MEASURED: counted 3\n{prose}") == prose
