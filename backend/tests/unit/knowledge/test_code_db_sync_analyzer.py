"""Unit tests for CodeDbSyncAnalyzer."""

import json

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


# ---------------------------------------------------------------------------
# PRJ-01 R1 — a tool-call argument declared ``string`` that arrives as an object
#
# Production, 2026-09-10..12: four consecutive ``code_db_sync`` runs died in
# ``store_sync`` with ``asyncpg.exceptions.DataError: invalid input for query
# argument $6: {} (expected str)``. The parsing lines date from March; what
# changed is the model — ``DEFAULT_LLM_MODEL`` moved to a provider that returns
# JSON *objects* where the previous one returned JSON *strings*, for parameters
# the tool schema declares ``type="string"``.
#
# The fixture above mirrors the SCHEMA ("{}"), which is why every existing test
# was green while production could not store a single row. These mirror a MODEL.
# ---------------------------------------------------------------------------

_OBJECT_ARGS = {
    "required_filters": {"status": "= 1"},
    "column_value_mappings": {"status": {"0": "pending", "1": "done"}},
    "column_sync_notes": {"id": "primary key"},
}

_TEXT_FIELDS = (
    "data_format_notes",
    "column_sync_notes_json",
    "business_logic_notes",
    "conversion_warnings",
    "query_recommendations",
    "required_filters_json",
    "column_value_mappings_json",
)


def _tc_objects(table_name, **overrides):
    """A tool call shaped like a model that ignores ``type="string"``."""
    args = {
        "table_name": table_name,
        "sync_status": "matched",
        "confidence_score": 4,
        **_OBJECT_ARGS,
    }
    args.update(overrides)
    return ToolCall(id="x", name="table_sync_analysis", arguments=args)


def _assert_storable(analysis):
    """Every column that is ``Text`` in ``models/code_db_sync.py`` must be ``str``."""
    for field in _TEXT_FIELDS:
        value = getattr(analysis, field)
        assert isinstance(value, str), f"{field} is {type(value).__name__}, asyncpg needs str"
    for field in ("column_sync_notes_json", "required_filters_json", "column_value_mappings_json"):
        json.loads(getattr(analysis, field))  # must round-trip, not just be a str


async def test_single_object_valued_args_are_stored_as_json_strings():
    analyzer = CodeDbSyncAnalyzer(_Router([_tc_objects("orders")]))
    out = await analyzer.analyze_table(table_name="orders", code_context="", db_context="")
    _assert_storable(out)
    assert json.loads(out.required_filters_json) == {"status": "= 1"}
    assert json.loads(out.column_value_mappings_json) == {"status": {"0": "pending", "1": "done"}}


async def test_batch_object_valued_args_are_stored_as_json_strings():
    tables = [("orders", "", ""), ("payments", "", "")]
    analyzer = CodeDbSyncAnalyzer(_Router([_tc_objects("orders"), _tc_objects("payments")]))
    out = await analyzer.analyze_table_batch(tables)
    assert len(out) == 2
    for analysis in out:
        _assert_storable(analysis)


async def test_a_list_where_prose_was_asked_for_is_stored_not_dropped():
    """The four non-``_json`` text fields are declared ``string`` too."""
    call = _tc_objects("orders", conversion_warnings=["utc vs local", "cents vs units"])
    analyzer = CodeDbSyncAnalyzer(_Router([call]))
    out = await analyzer.analyze_table(table_name="orders", code_context="", db_context="")
    _assert_storable(out)
    assert "utc vs local" in out.conversion_warnings


async def test_a_value_that_cannot_be_serialised_degrades_to_the_default():
    class _Unserialisable:
        pass

    call = _tc_objects("orders", required_filters=_Unserialisable())
    analyzer = CodeDbSyncAnalyzer(_Router([call]))
    out = await analyzer.analyze_table(table_name="orders", code_context="", db_context="")
    _assert_storable(out)
    assert json.loads(out.required_filters_json) == {}
