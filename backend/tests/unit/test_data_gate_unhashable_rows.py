"""F-DG-04: a JSON or array cell must not crash the quality gate.

`_check_duplicates` builds `key = tuple(row)` and tests `key in seen`. A row holding a
`list` or `dict` — a Postgres `json`/`jsonb` or array column, a Mongo document, an
aggregated array — makes that tuple unhashable and the membership test raise
`TypeError`. Measured directly:

    tuple([1, {"a": 1}]) in set()  ->  TypeError: unhashable type: 'dict'
    tuple([2, ["x"]])    in set()  ->  TypeError: unhashable type: 'list'

The consequence is the shape that matters: DataGate sits on the answer path, so a
perfectly good query over a JSON column failed the whole answer. **A check that breaks
what it is checking is worse than no check** — and that is the general property tested
here, not only the one crashing call site.
"""

from __future__ import annotations

import pytest

from app.agents.data_gate import DataGate
from app.connectors.base import QueryResult

UNHASHABLE_CELLS = [
    {"tags": ["a", "b"]},
    ["x", "y"],
    {"nested": {"deep": [1, 2]}},
    [{"id": 1}, {"id": 2}],
]


def _rows_with(cell: object, n: int = 12) -> QueryResult:
    # >= 10 rows, or the duplicate check returns early and proves nothing.
    return QueryResult(
        columns=["id", "payload"],
        rows=[[i, cell] for i in range(n)],
        row_count=n,
    )


class TestItDoesNotCrash:
    @pytest.mark.parametrize("cell", UNHASHABLE_CELLS)
    def test_an_unhashable_cell_is_survivable(self, cell: object):
        outcome = DataGate().check_query_result(_rows_with(cell))
        assert outcome is not None

    @pytest.mark.parametrize("cell", UNHASHABLE_CELLS)
    def test_the_duplicate_check_itself_survives(self, cell: object):
        gate = DataGate()
        from app.agents.data_gate import DataGateOutcome

        outcome = DataGateOutcome()
        gate._check_duplicates(_rows_with(cell), outcome)
        assert isinstance(outcome.warnings, list)


class TestItStillDetects:
    def test_identical_json_rows_are_still_seen_as_duplicates(self):
        """Surviving is not enough — the check has to keep working on these rows."""
        gate = DataGate()
        from app.agents.data_gate import DataGateOutcome

        outcome = DataGateOutcome()
        gate._check_duplicates(_rows_with({"tags": ["a"]}, n=12), outcome)
        # Every row differs only by `id`, so these are NOT duplicates …
        assert not any("duplicate" in w for w in outcome.warnings)

        outcome2 = DataGateOutcome()
        same = QueryResult(
            columns=["id", "payload"],
            rows=[[1, {"tags": ["a"]}] for _ in range(12)],
            row_count=12,
        )
        gate._check_duplicates(same, outcome2)
        # … while these are, and a JSON cell must not hide that.
        assert any("duplicate" in w for w in outcome2.warnings), (
            "identical JSON rows were not recognised as duplicates"
        )

    def test_rows_differing_only_inside_the_json_are_not_duplicates(self):
        gate = DataGate()
        from app.agents.data_gate import DataGateOutcome

        outcome = DataGateOutcome()
        rows = QueryResult(
            columns=["id", "payload"],
            rows=[[1, {"n": i}] for i in range(12)],
            row_count=12,
        )
        gate._check_duplicates(rows, outcome)
        assert not any("duplicate" in w for w in outcome.warnings)


class TestOrdinaryRowsUnaffected:
    def test_plain_duplicates_still_warn(self):
        gate = DataGate()
        from app.agents.data_gate import DataGateOutcome

        outcome = DataGateOutcome()
        gate._check_duplicates(
            QueryResult(columns=["a"], rows=[["x"] for _ in range(12)], row_count=12),
            outcome,
        )
        assert any("duplicate" in w for w in outcome.warnings)

    def test_plain_distinct_rows_do_not_warn(self):
        gate = DataGate()
        from app.agents.data_gate import DataGateOutcome

        outcome = DataGateOutcome()
        gate._check_duplicates(
            QueryResult(columns=["a"], rows=[[i] for i in range(12)], row_count=12),
            outcome,
        )
        assert not any("duplicate" in w for w in outcome.warnings)
