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
        assert out.query_hints.startswith("MEASURED (units):")
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
            "MEASURED (units):"
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
        assert twice.query_hints.count("MEASURED (units):") == 1


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
    assert thrice.query_hints.count("MEASURED (units):") == 1
    assert "Use was_handled = 1." in thrice.query_hints


def test_the_model_s_own_prose_is_never_edited() -> None:
    """Only whole lines beginning with the prefix are dropped. A sentence the model wrote
    that happens to contain the word is prose, and prose is not the stripper's to edit."""
    from app.knowledge.db_index_validator import strip_measured_lines

    prose = "Nothing here is MEASURED: the column is undocumented."
    assert strip_measured_lines(f"MEASURED: counted 3\n{prose}") == prose


def test_the_stale_strip_runs_before_the_correction_not_after() -> None:
    """Two correct fixes cancelled each other in production, and only the order says so.

    Measured 2026-09-15: `apply_measured_corrections` was live, `strip_measured_lines` was
    live, both did what they were written to do — and no stored row carried the currency
    caveat, because the store site stripped the analysis AFTER correcting it.

    Neither function is wrong. A test on either passes. What is wrong is only visible as a
    sequence, so that is what this checks — read from the parse tree rather than from the
    source lines, because the first version matched a one-line call and stopped seeing it
    the moment the call took a second argument and wrapped.
    """
    tree = ast.parse(PIPELINE.read_text(encoding="utf-8"))

    def _calls(name: str) -> list[int]:
        return sorted(
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == name
            and "analysis.query_hints" in ast.unparse(node)
        )

    strips = _calls("strip_measured_lines")
    corrections = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "apply_measured_corrections"
    ]
    assert len(strips) == 1, (
        f"expected exactly one strip of the analysis hints, found {strips}. Two means one "
        "is undoing the correction; none means a reused analysis carries last night's "
        "caveats for ever."
    )
    assert len(corrections) == 1, corrections
    assert strips[0] < corrections[0], (
        f"the stale-caveat strip is at line {strips[0]} and the correction at "
        f"{corrections[0]}. Stripping after correcting removes the caveat just added — "
        "both functions stay correct and the stored row carries nothing."
    )

    # …and the row that is stored must use the corrected value, not re-strip it.
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values, strict=False):
            if isinstance(key, ast.Constant) and key.value == "query_hints":
                assert "strip_measured_lines" not in ast.unparse(value), (
                    "the stored `query_hints` strips again at the point of storage, which "
                    "removes this run's measured caveats along with the stale ones"
                )


class TestAPartialRunDoesNotEraseATrueWarning:
    """Measured on production 2026-09-16, and it is the flip side of "rebuild, never append".

    A `completed_partial` index spent its sampling budget before reaching
    `purchases.currency`. The units caveat therefore had nothing to rebuild from — and an
    unconditional strip removed the correct one the night before had established. The
    stored row went from carrying a true warning about fourteen currencies to carrying
    none, because the sampler ran out of time.

    **A caveat is replaced when there is a measurement to replace it with, and kept when
    there is not.** Forgetting something true on the strength of not having looked is the
    defect, not the fix.
    """

    _EXISTING = (
        "MEASURED (units): `currency` holds 14 distinct values in this table, so `amount` "
        "is denominated per row.\nUse was_handled = 1."
    )

    def test_an_unmeasured_run_keeps_what_a_previous_one_established(self) -> None:
        unmeasured = TableInfo(
            name="purchases",
            columns=[_col("currency", "varchar(3)"), _col("amount", "int")],
            row_count=120_000,
        )
        out = apply_measured_corrections(
            TableAnalysis(table_name="purchases", query_hints=self._EXISTING), unmeasured
        )
        assert "14 distinct values" in out.query_hints
        assert "Use was_handled = 1." in out.query_hints

    def test_a_measured_run_replaces_it(self) -> None:
        out = apply_measured_corrections(
            TableAnalysis(table_name="purchases", query_hints=self._EXISTING), _purchases(9)
        )
        assert out.query_hints.count("MEASURED (units):") == 1
        assert "9 distinct values" in out.query_hints

    def test_the_units_strip_leaves_a_rivalry_caveat_alone(self) -> None:
        """The two are produced by different steps. Removing one on the other's behalf is
        how a warning disappears for a reason that has nothing to do with it."""
        from app.knowledge.db_index_validator import MEASURED_RIVALRY, strip_measured_lines

        both = (
            "MEASURED (units): `currency` holds 14 distinct values.\n"
            f"{MEASURED_RIVALRY} over 2026-08, 4.30x apart.\n"
            "Use was_handled = 1."
        )
        from app.knowledge.db_index_validator import MEASURED_UNITS

        kept = strip_measured_lines(both, MEASURED_UNITS)
        assert "rivalry" in kept
        assert "units" not in kept
        assert "Use was_handled = 1." in kept


def test_the_rivalry_strip_runs_only_when_the_comparison_ran() -> None:
    """A step that never ran has established nothing.

    Stripping last night's rivalry caveats because this run's comparison was disabled,
    failed or timed out loses a true warning for a reason unrelated to its truth — the
    same rule the units caveat follows, applied to the other step.
    """
    tree = ast.parse(PIPELINE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        rendered = ast.unparse(node)
        if "strip_measured_lines" not in rendered or "analysis.query_hints" not in rendered:
            continue
        assert "MEASURED_RIVALRY" in rendered, (
            "the store site strips every measured caveat rather than the rivalry kind, so "
            "a run that measured no units erases the units caveat a previous run made"
        )

    source = PIPELINE.read_text(encoding="utf-8")
    assert "if _comparison_ran:" in source, (
        "the rivalry strip is unconditional — a comparison that was disabled or failed "
        "would delete last night's caveats on the strength of not having looked"
    )
