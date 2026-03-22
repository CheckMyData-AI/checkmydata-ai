"""Unit tests for batch routes helper functions."""

from app.api.routes.batch import _safe_sheet_name


class TestSafeSheetName:
    def test_normal_title(self):
        assert _safe_sheet_name("Revenue Report", 0) == "1_Revenue Report"

    def test_long_title_truncated(self):
        long_name = "A" * 50
        result = _safe_sheet_name(long_name, 2)
        assert result.startswith("3_")
        assert len(result) <= 31

    def test_invalid_chars_replaced(self):
        result = _safe_sheet_name("My/Report*[test]", 0)
        assert "/" not in result
        assert "*" not in result
        assert "[" not in result
        assert "]" not in result

    def test_empty_title(self):
        result = _safe_sheet_name("", 5)
        assert result == "Query_6"

    def test_backslash_replaced(self):
        result = _safe_sheet_name("path\\to\\data", 0)
        assert "\\" not in result

    def test_question_mark_replaced(self):
        result = _safe_sheet_name("what?", 0)
        assert "?" not in result

    def test_colon_replaced(self):
        result = _safe_sheet_name("time:value", 0)
        assert ":" not in result
