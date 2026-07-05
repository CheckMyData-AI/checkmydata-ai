"""Tests for required_filter_guard — enforce was_handled / deleted_at on purchases."""

from app.core.required_filter_guard import (
    check_required_filters,
    compile_filter_check,
    merge_required_filters,
    parse_required_columns_from_hint,
)

# The exact prod-incident query (audit §2): a legitimate June revenue query that
# the 2-column hardcoded guard blocked to death.
PROD_REVENUE_QUERY = """
SELECT ROUND(SUM(amount) / 100, 2) AS revenue
FROM purchases
WHERE created_at >= '2026-06-01 00:00:00'
  AND created_at < '2026-06-30 00:00:00'
"""

MAY_GROSS_QUERY = """
SELECT product_type, ROUND(SUM(amount) / 100, 2) AS gross_revenue
FROM purchases
WHERE deleted_at IS NULL
  AND created_at >= '2026-05-01 00:00:00'
  AND created_at < '2026-05-19 00:00:00'
  AND product_type IN ('NEW_INTERNET_PROFILE', 'TOP_UP_SECOND_PHONE')
GROUP BY product_type
"""

MAY_GROSS_QUERY_FIXED = """
SELECT product_type, ROUND(SUM(amount) / 100, 2) AS gross_revenue
FROM purchases
WHERE deleted_at IS NULL
  AND was_handled = 1
  AND created_at >= '2026-05-01 00:00:00'
  AND created_at < '2026-05-19 00:00:00'
  AND product_type IN ('NEW_INTERNET_PROFILE', 'TOP_UP_SECOND_PHONE')
GROUP BY product_type
"""


def test_parse_required_columns_from_purchases_hint():
    hint = (
        "Use 'was_handled = 1' and 'deleted_at IS NULL' to filter for valid purchases. "
        "Divide amount by 100."
    )
    assert parse_required_columns_from_hint(hint) == {"was_handled", "deleted_at"}


def test_merge_required_filters_combines_sync_and_index():
    """merge_required_filters returns dict[str, dict[str,str]] preserving predicates."""
    merged = merge_required_filters(
        {"purchases": {"was_handled": "= 1"}},
        {"purchases": "Use was_handled = 1 and deleted_at IS NULL"},
    )
    assert isinstance(merged["purchases"], dict)
    assert set(merged["purchases"].keys()) == {"was_handled", "deleted_at"}


def test_check_required_filters_fails_without_was_handled():
    required = {"purchases": {"was_handled", "deleted_at"}}
    result = check_required_filters(MAY_GROSS_QUERY, "mysql", required)
    assert not result.is_valid
    assert result.error is not None
    assert "was_handled" in result.error.message


def test_check_required_filters_passes_with_was_handled():
    required = {"purchases": {"was_handled", "deleted_at"}}
    result = check_required_filters(MAY_GROSS_QUERY_FIXED, "mysql", required)
    assert result.is_valid


def test_check_required_filters_ignores_unrelated_tables():
    required = {"purchases": {"was_handled"}}
    query = "SELECT COUNT(*) FROM users WHERE active = 1"
    result = check_required_filters(query, "mysql", required)
    assert result.is_valid


def test_compile_filter_check_equality_and_is_null():
    eq = compile_filter_check("was_handled", "= 1")
    assert eq.search("... WHERE was_handled = 1 ...")
    assert not eq.search("... WHERE other = 1 ...")
    isnull = compile_filter_check("deleted_at", "IS NULL")
    assert isnull.search("... WHERE deleted_at IS NULL ...")


def test_data_driven_from_required_filters_json_dict():
    """Guard must enforce arbitrary configured predicates, not just the 2 hardcoded."""
    required = {"orders": {"is_test": "= 0"}}  # a column NOT in the old hardcode
    missing = "SELECT COUNT(*) FROM orders"
    res = check_required_filters(missing, "mysql", required, attempt=1, max_attempts=3)
    assert not res.is_valid
    ok = "SELECT COUNT(*) FROM orders WHERE is_test = 0"
    res2 = check_required_filters(ok, "mysql", required, attempt=1, max_attempts=3)
    assert res2.is_valid


def test_final_attempt_degrades_to_warning_not_hard_fail():
    """SYNC-L1: on the last attempt an unsatisfied filter DEGRADES — the legit
    revenue query must NOT be blocked to death."""
    required = {"purchases": {"was_handled": "= 1", "deleted_at": "IS NULL"}}
    res = check_required_filters(PROD_REVENUE_QUERY, "mysql", required, attempt=3, max_attempts=3)
    assert res.is_valid  # degraded, not blocked
    assert res.warning is not None
    assert "was_handled" in res.warning or "deleted_at" in res.warning


def test_degrade_increments_metric(monkeypatch):
    from app.core import metrics

    metrics._collector = metrics.MetricsCollector()  # fresh
    required = {"purchases": {"was_handled": "= 1"}}
    check_required_filters(PROD_REVENUE_QUERY, "mysql", required, attempt=3, max_attempts=3)
    counters = metrics.get_metrics_collector().snapshot_counters("filter_guard")
    assert counters.get("filter_guard_degrade_total", 0) >= 1


def test_early_attempt_still_hard_fails_to_drive_repair():
    """On non-final attempts the guard still fails so the repair loop adds the filter."""
    required = {"purchases": {"was_handled": "= 1"}}
    res = check_required_filters(PROD_REVENUE_QUERY, "mysql", required, attempt=1, max_attempts=3)
    assert not res.is_valid


# ---------------------------------------------------------------------------
# SYNC-L1 review: real merge→guard predicate-enforcement path
# ---------------------------------------------------------------------------


def test_merge_preserves_non_legacy_predicates():
    """merge_required_filters must return the predicate values from sync_filters,
    not just column names.  A non-legacy column like 'is_active' with predicate
    '= 1' must survive the merge unchanged."""
    merged = merge_required_filters(
        {"users": {"is_active": "= 1"}},
        {},  # no index hints
    )
    # Must be dict form, not set form
    assert isinstance(merged.get("users"), dict), (
        f"merge_required_filters must return dict[str, dict[str,str]], got: {merged}"
    )
    assert merged["users"].get("is_active") == "= 1", (
        f"Predicate '= 1' for 'is_active' was discarded — got: {merged['users']}"
    )


def test_merge_to_guard_real_path_enforces_predicate():
    """End-to-end: merge_required_filters result flows directly into check_required_filters.
    A non-legacy predicate (is_active = 1) must be ENFORCED with the predicate, not
    just bare presence.  Blocked when SQL lacks 'is_active = 1'; passes when present."""
    # Build filters exactly as sql_agent._load_required_filters_by_table does:
    sync_filters = {"users": {"is_active": "= 1"}}
    index_hints: dict[str, str] = {}
    required_by_table = merge_required_filters(sync_filters, index_hints)

    sql_missing = "SELECT COUNT(*) FROM users WHERE name = 'Alice'"
    res_missing = check_required_filters(
        sql_missing, "postgres", required_by_table, attempt=1, max_attempts=3
    )
    assert not res_missing.is_valid, (
        "SQL without 'is_active = 1' must be BLOCKED through the real merge→guard path"
    )
    assert res_missing.error is not None
    assert "is_active" in res_missing.error.message

    sql_bare_col = "SELECT COUNT(*) FROM users WHERE is_active AND name = 'Alice'"
    res_bare = check_required_filters(
        sql_bare_col, "postgres", required_by_table, attempt=1, max_attempts=3
    )
    assert not res_bare.is_valid, (
        "SQL with 'is_active' present but WITHOUT '= 1' predicate must still be BLOCKED"
    )

    sql_ok = "SELECT COUNT(*) FROM users WHERE is_active = 1 AND name = 'Alice'"
    res_ok = check_required_filters(
        sql_ok, "postgres", required_by_table, attempt=1, max_attempts=3
    )
    assert res_ok.is_valid, "SQL with 'is_active = 1' must PASS through the real merge→guard path"


def test_merge_combines_sync_and_hint_preserving_sync_predicates():
    """When sync_filters and index_hints both name a column for a table,
    the sync predicate must be preserved and hint-only columns use legacy fallback."""
    merged = merge_required_filters(
        {"purchases": {"was_handled": "= 1"}},
        {"purchases": "Use was_handled = 1 and deleted_at IS NULL"},
    )
    assert isinstance(merged.get("purchases"), dict), f"Must return dict form, got: {merged}"
    # sync-sourced column must keep its predicate
    assert merged["purchases"].get("was_handled") == "= 1", (
        f"sync predicate for was_handled must be preserved, got: {merged['purchases']}"
    )
    # hint-sourced column must receive the legacy predicate (IS NULL for deleted_at)
    assert "deleted_at" in merged["purchases"], (
        f"deleted_at from hint must be in merged result, got: {merged['purchases']}"
    )
    assert merged["purchases"]["deleted_at"] == "IS NULL", (
        f"hint-sourced deleted_at must get legacy predicate 'IS NULL', got: {merged['purchases']}"
    )


# ---------------------------------------------------------------------------
# SYNC-L1 review: unparseable condition → advisory (bare presence), not hard-block
# ---------------------------------------------------------------------------


def test_unparseable_condition_falls_back_to_bare_presence_advisory():
    """An unparseable predicate like 'BETWEEN 1 AND 5' must fall back to bare
    column-name presence check — compile_filter_check must not hard-block when the
    column name appears, even though the exact condition cannot be verified."""
    from app.core.required_filter_guard import compile_filter_check

    pat = compile_filter_check("status", "BETWEEN 1 AND 5")
    # Column name present → advisory passes
    assert pat.search("SELECT * FROM orders WHERE status BETWEEN 1 AND 5"), (
        "Unparseable predicate should fall back to bare presence; column appears → should match"
    )
    assert pat.search("SELECT * FROM orders WHERE status = 2"), (
        "Bare presence: any mention of 'status' should match when predicate is unparseable"
    )
    # Column name absent → bare presence correctly not matched
    assert not pat.search("SELECT * FROM orders WHERE other_col = 1"), (
        "Column name absent → bare-presence regex should NOT match"
    )


def test_unparseable_condition_guard_passes_when_column_appears():
    """check_required_filters with an unparseable predicate must PASS (not hard-block)
    when the column name appears anywhere in the query — even if the exact condition
    shape cannot be verified."""
    required = {"orders": {"status": "BETWEEN 1 AND 5"}}
    sql_with_col = "SELECT COUNT(*) FROM orders WHERE status BETWEEN 1 AND 5"
    res = check_required_filters(sql_with_col, "postgres", required, attempt=1, max_attempts=3)
    assert res.is_valid, (
        "Unparseable predicate with column present must PASS (advisory, not hard-block)"
    )
