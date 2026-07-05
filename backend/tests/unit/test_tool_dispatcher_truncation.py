"""DATA-02: process_data must not call a truncated set 'complete'."""

from app.agents.tool_dispatcher import ToolDispatcher


def test_full_data_hint_marks_truncated_as_partial():
    hint = ToolDispatcher._full_data_hint(10_000, truncated=True)
    assert "complete dataset" not in hint.lower()
    assert "capped" in hint.lower() or "truncated" in hint.lower() or "partial" in hint.lower()


def test_full_data_hint_complete_for_untruncated():
    hint = ToolDispatcher._full_data_hint(42, truncated=False)
    assert "complete dataset" in hint.lower()
    assert "42" in hint


# ---------------------------------------------------------------------------
# DATA-20: _fmt_cell readable large numbers
# ---------------------------------------------------------------------------


def test_fmt_cell_thousands_separator():
    from app.agents.tool_dispatcher import ToolDispatcher

    assert ToolDispatcher._fmt_cell(1234567) == "1,234,567"
    assert ToolDispatcher._fmt_cell("text") == "text"


def test_fmt_cell_decimal():
    from decimal import Decimal

    from app.agents.tool_dispatcher import ToolDispatcher

    assert ToolDispatcher._fmt_cell(Decimal("9876543")) == "9,876,543"


def test_fmt_cell_bool_not_numeric():
    from app.agents.tool_dispatcher import ToolDispatcher

    assert ToolDispatcher._fmt_cell(True) == "True"
    assert ToolDispatcher._fmt_cell(False) == "False"


def test_fmt_cell_small_int_no_separator():
    from app.agents.tool_dispatcher import ToolDispatcher

    assert ToolDispatcher._fmt_cell(42) == "42"


def test_fmt_cell_none():
    from app.agents.tool_dispatcher import ToolDispatcher

    assert ToolDispatcher._fmt_cell(None) == "None"
