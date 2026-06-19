"""Tests for required_filter_guard — enforce was_handled / deleted_at on purchases."""

from app.core.required_filter_guard import (
    check_required_filters,
    merge_required_filters,
    parse_required_columns_from_hint,
)

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
