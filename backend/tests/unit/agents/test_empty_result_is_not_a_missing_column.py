"""An empty result is not a missing column, and saying so blamed the wrong thing.

All seven `stage_validation` failures in production carry the same message, and it is
the largest single category of span failure in the system:

    06-22  Missing expected columns: ['purchase_count', 'purchase_date',
                                      'revenue_usd', 'virtual_number']
    06-25  Missing expected columns: ['data_revenue']
    06-30  Missing expected columns: ['cohort_size']
    06-30  Missing expected columns: ['activity_month', 'amount', 'user_id']
    06-30  Missing expected columns: ['user_id']
    08-27  Missing expected columns: ['plan_days', 'plan_gb', 'purchase_date', …]
    08-27  Missing expected columns: ['id']

At least two of them are provably false. Paired with the query the agent produced in
the same trace:

    plan wanted  ['data_revenue']
    agent ran    SELECT ROUND(SUM(p.amount) / 100, 2) AS data_revenue,
                        COUNT(*) AS txn_count FROM purchases p WHERE …

    plan wanted  ['purchase_count', 'purchase_date', 'revenue_usd', 'virtual_number']
    agent ran    SELECT DATE(p.created_at) AS purchase_date,
                        pn.phone         AS virtual_number,
                        SUM(p.amount)/100 AS revenue_usd,
                        COUNT(*)          AS purchase_count  FROM …

Every alias is exactly what the plan asked for. The queries were right.

`mysql.py` derived its column list from `rows[0].keys()` and returned
`QueryResult(row_count=0)` — **with no columns at all** — when nothing matched. The
validator then compared the expected names against an empty set and reported all of
them missing. A correct query that legitimately matched zero rows failed, after up to
ten LLM calls and four minutes, blaming columns it had in fact selected.

Two changes, and they are different in kind. The connector now reports the columns the
cursor knows regardless of rows, so the check *can* be evaluated. The validator no
longer treats "no metadata to check against" as "the check failed" — whether emptiness
is acceptable is what `min_rows` decides, and it is evaluated separately.

The distinction that matters: **unverifiable is not violated.**
"""

from __future__ import annotations

import pytest

from app.agents.stage_validator import StageValidator


@pytest.fixture
def validator():
    return StageValidator()


def _run(validator, *, columns, rows, expected_columns):
    """Drive the real validator over a stage whose result has the given shape.

    Real `PlanStage` / `StageResult` / `StageValidation`, not stand-ins: the first
    version of this file used `SimpleNamespace` and failed on `result.status`, which is
    exactly the kind of divergence a fake hides until the shape it imitates moves.
    """
    from app.agents.stage_context import (
        PlanStage,
        StageContext,
        StageResult,
        StageValidation,
    )
    from app.connectors.base import QueryResult

    qr = QueryResult(columns=list(columns), rows=list(rows), row_count=len(rows))
    result = StageResult(
        stage_id="s1", status="success", query="SELECT 1", query_result=qr, summary="ok"
    )
    stage = PlanStage(
        stage_id="s1",
        description="d",
        tool="execute_query",
        validation=StageValidation(expected_columns=list(expected_columns)),
    )
    ctx = StageContext(plan=None, results={})
    return validator.validate(stage, result, ctx)


class TestAnEmptyResultDoesNotFailOnColumns:
    def test_no_rows_and_no_metadata_is_not_a_column_failure(self, validator) -> None:
        """The production shape: `mysql.py` returned row_count=0 with no columns, and
        every expected name read as missing."""
        outcome = _run(validator, columns=[], rows=[], expected_columns=["data_revenue"])
        assert "Missing expected columns" not in str(outcome.errors), outcome.errors

    def test_no_rows_but_metadata_present_still_checks(self, validator) -> None:
        """With the connector fix the cursor reports its columns even for an empty
        result — so the check becomes answerable again, and a genuinely wrong column
        set must still fail. Losing that would trade one silent failure for another."""
        outcome = _run(validator, columns=["txn_count"], rows=[], expected_columns=["data_revenue"])
        assert not outcome.passed
        assert "data_revenue" in str(outcome.errors)

    def test_no_rows_with_matching_metadata_passes(self, validator) -> None:
        outcome = _run(
            validator, columns=["data_revenue"], rows=[], expected_columns=["data_revenue"]
        )
        assert outcome.passed, outcome.errors


class TestTheCheckStillWorksWhenThereAreRows:
    """The fix must not disable the check it repairs."""

    def test_a_genuinely_missing_column_still_fails(self, validator) -> None:
        outcome = _run(
            validator,
            columns=["user_id", "cnt"],
            rows=[[1, 2]],
            expected_columns=["user_id", "revenue_usd"],
        )
        assert not outcome.passed
        assert "revenue_usd" in str(outcome.errors)

    def test_matching_columns_pass(self, validator) -> None:
        outcome = _run(
            validator,
            columns=["purchase_date", "revenue_usd"],
            rows=[["2026-01-01", 10]],
            expected_columns=["purchase_date", "revenue_usd"],
        )
        assert outcome.passed, outcome.errors

    def test_case_still_does_not_matter(self, validator) -> None:
        """Quoted identifiers come back cased differently per driver; that was fixed
        earlier and must stay fixed."""
        outcome = _run(
            validator,
            columns=["Purchase_Date"],
            rows=[["2026-01-01"]],
            expected_columns=["purchase_date"],
        )
        assert outcome.passed, outcome.errors


def test_the_mysql_connector_reports_columns_without_rows() -> None:
    """The other half. Reading the source rather than a live MySQL because the point is
    the shape of the code path: columns must come from the cursor, which knows them,
    and not from the first row, which does not exist."""
    import inspect

    from app.connectors import mysql

    source = inspect.getsource(mysql)
    assert "cur.description" in source, (
        "the column list is derived from the first row again — an empty result will "
        "carry no columns and the validator will call every expected column missing"
    )
    assert "columns=described" in source, "the empty-result return path drops the columns"
