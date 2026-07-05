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
