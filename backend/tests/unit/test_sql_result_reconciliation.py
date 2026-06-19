"""Tests for SQL result reconciliation and false self-correction scrubbing."""

from app.agents.response_builder import ResponseBuilder
from app.agents.sql_agent import SQLAgentResult
from app.agents.sql_result_reconciliation import (
    build_reconciliation_note,
    collect_sql_totals_snapshots,
    scrub_false_sql_self_correction,
    sql_results_reconcile,
)
from app.connectors.base import QueryResult
from app.llm.base import Message


def _dina_like_results() -> list[SQLAgentResult]:
    aggregate = SQLAgentResult(
        status="success",
        query="SELECT CASE ... END AS product_category, SUM(amount)/100 ...",
        results=QueryResult(
            columns=["product_category", "gross_revenue_usd"],
            rows=[
                ["virtual number", 92021.35],
                ["data", 52671.79],
            ],
            row_count=2,
        ),
    )
    detail = SQLAgentResult(
        status="success",
        query="SELECT product_type, ROUND(SUM(amount)/100, 2) AS gross_revenue_usd ...",
        results=QueryResult(
            columns=["product_type", "gross_revenue_usd"],
            rows=[
                ["TOP_UP_SECOND_PHONE", 90369.61],
                ["NEW_INTERNET_PROFILE", 18934.22],
                ["RENEW_INTERNET_PROFILE_SUBSCRIPTION", 13012.18],
                ["NEW_INTERNET_PROFILE_SUBSCRIPTION", 12882.17],
                ["TOP_UP_INTERNET_PROFILE", 7750.46],
                ["RENEW_TOP_UP_SECOND_PHONE_SUBSCRIPTION", 832.34],
                ["TOP_UP_SECOND_PHONE_SUBSCRIPTION", 819.40],
                ["NEW_MULTIPLE_INTERNET_PROFILES", 92.76],
            ],
            row_count=8,
        ),
    )
    return [aggregate, detail]


def test_collect_sql_totals_snapshots_matches_dina_case():
    snapshots = collect_sql_totals_snapshots(_dina_like_results())
    assert len(snapshots) == 2
    assert {snap.grand_total for snap in snapshots} == {144693.14}


def test_sql_results_reconcile_when_totals_match():
    assert sql_results_reconcile(_dina_like_results()) is True


def test_build_reconciliation_note_for_matching_queries():
    note = build_reconciliation_note(_dina_like_results())
    assert note is not None
    assert "SQL RECONCILIATION (verified)" in note
    assert "144,693.14" in note
    assert "do NOT tell the user" in note


def test_scrub_false_sql_self_correction_removes_dina_leadin():
    raw = (
        "The first gross query missed some product types (its `LIKE` patterns didn't "
        "capture `SUBSCRIPTION` and `MULTIPLE` variants correctly — it actually did "
        "via LIKE '%INTERNET_PROFILE%' and '%SECOND_PHONE%', but reported lower totals). "
        "The detailed breakdown gives the accurate picture. Let me classify properly:\n\n"
        "**Data products:** NEW_INTERNET_PROFILE\n\n"
        "## Net Revenue"
    )
    cleaned = scrub_false_sql_self_correction(raw, reconciled=True)
    assert "first gross query missed" not in cleaned.lower()
    assert cleaned.startswith("**Data products:**")


def test_scrub_false_sql_self_correction_noop_when_not_reconciled():
    raw = "The first gross query missed some product types."
    assert scrub_false_sql_self_correction(raw, reconciled=False) == raw


def test_sql_results_reconcile_with_mixed_refund_and_gross_queries():
    """Gross aggregate + detail reconcile even when refund queries differ."""
    gross1, gross2 = _dina_like_results()
    refunds = SQLAgentResult(
        status="success",
        query="SELECT ... FROM refund_requests ...",
        results=QueryResult(
            columns=["product_category", "approved_refund_amount_usd"],
            rows=[
                ["virtual number", 1913.60],
                ["data", 1395.91],
            ],
            row_count=2,
        ),
    )
    all_results = [refunds, gross1, gross2]
    assert sql_results_reconcile(all_results) is True
    note = build_reconciliation_note(all_results)
    assert note is not None
    assert "144,693.14" in note


def test_build_synthesis_messages_includes_reconciliation_note():
    sr1, sr2 = _dina_like_results()
    messages = [
        Message(role="system", content="You are a data assistant."),
        Message(role="user", content="Revenue by product"),
    ]
    result = ResponseBuilder.build_synthesis_messages(
        messages,
        sr2,
        [],
        32000,
        all_sql_results=[sr1, sr2],
    )
    assert "SQL RECONCILIATION (verified)" in result[1].content
    assert "do NOT claim an earlier query was wrong" in result[1].content
