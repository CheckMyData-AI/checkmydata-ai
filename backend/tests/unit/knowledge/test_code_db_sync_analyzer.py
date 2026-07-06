"""Unit tests for CodeDbSyncAnalyzer."""

from app.knowledge.code_db_sync_analyzer import CodeDbSyncAnalyzer
from app.llm.base import LLMResponse, ToolCall


class _Router:
    def __init__(self, calls):
        self._calls = calls

    async def complete(self, **kwargs):
        return LLMResponse(tool_calls=self._calls)


def _tc(table_name, conf=4, status="matched"):
    return ToolCall(
        id="x",
        name="table_sync_analysis",
        arguments={
            "table_name": table_name,
            "sync_status": status,
            "confidence_score": conf,
            "required_filters": "{}",
            "column_value_mappings": "{}",
        },
    )


async def test_batch_reconciles_by_name_not_position():
    tables = [("orders", "", ""), ("payments", "", "")]
    # LLM returns them REVERSED
    analyzer = CodeDbSyncAnalyzer(_Router([_tc("payments"), _tc("orders")]))
    out = await analyzer.analyze_table_batch(tables)
    by_name = {a.table_name: a for a in out}
    assert by_name["orders"].sync_status == "matched"
    assert by_name["payments"].sync_status == "matched"
    assert not by_name["orders"].is_fallback


async def test_batch_unknown_name_dropped_and_missing_filled_with_fallback():
    tables = [("orders", "", ""), ("payments", "", "")]
    analyzer = CodeDbSyncAnalyzer(_Router([_tc("orders"), _tc("ghost_table")]))
    out = await analyzer.analyze_table_batch(tables)
    by_name = {a.table_name: a for a in out}
    assert len(out) == 2
    assert by_name["payments"].is_fallback is True  # never returned by LLM
    assert by_name["orders"].is_fallback is False


async def test_batch_bad_confidence_only_degrades_that_table():
    tables = [("orders", "", ""), ("payments", "", "")]
    bad = _tc("orders")
    bad.arguments["confidence_score"] = "4.5"
    analyzer = CodeDbSyncAnalyzer(_Router([bad, _tc("payments", conf=5)]))
    out = await analyzer.analyze_table_batch(tables)
    by_name = {a.table_name: a for a in out}
    # L11 fix: "4.5" rounds to 4 (not the old default-3), preserving the signal
    assert by_name["orders"].confidence_score == 4
    assert by_name["orders"].is_fallback is False
    assert by_name["payments"].confidence_score == 5


async def test_fallback_marked():
    a = CodeDbSyncAnalyzer._fallback_analysis("t")
    assert a.is_fallback is True and a.confidence_score == 1
