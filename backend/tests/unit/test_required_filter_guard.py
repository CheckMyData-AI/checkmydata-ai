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
    merged = merge_required_filters(
        {"purchases": {"was_handled": "= 1"}},
        {"purchases": "Use was_handled = 1 and deleted_at IS NULL"},
    )
    assert merged["purchases"] == {"was_handled", "deleted_at"}


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
