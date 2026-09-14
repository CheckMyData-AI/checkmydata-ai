"""`as_text` — the one place a tool-call argument becomes application data.

PRJ-01 and its ladder walk found **six** fields across two modules where a parameter the
schema declares ``type="string"`` is written straight into a ``Text`` column. Four of
them were discovered by a production outage (four nights of `code_db_sync` storing
nothing), one by asking what the *next* writer in the same file does, and one by walking
the REQ ladder into a module the outage never touched. They shared no helper, so each had
to be found separately — which is the argument for this module existing at all.
"""

import json

import pytest

from app.llm.tool_args import as_text


def test_a_string_is_returned_unchanged():
    assert as_text("already text") == "already text"


@pytest.mark.parametrize(
    "value",
    [
        {"status": "= 1"},
        {"status": {"0": "pending", "1": "done"}},
        ["utc vs local", "cents vs units"],
        [],
        {},
    ],
)
def test_objects_and_lists_become_json_that_round_trips(value):
    out = as_text(value)
    assert isinstance(out, str)
    assert json.loads(out) == value


def test_none_becomes_the_default():
    assert as_text(None) == ""
    assert as_text(None, "{}") == "{}"


@pytest.mark.parametrize("value,expected", [(1, "1"), (2.5, "2.5"), (True, "True")])
def test_scalars_are_stringified(value, expected):
    assert as_text(value) == expected


def test_an_unserialisable_value_degrades_to_the_default_rather_than_raising():
    class _Opaque:
        pass

    assert as_text(_Opaque(), "{}") == "{}"


def test_unicode_survives():
    """`ensure_ascii=False`: a column note in Russian must stay readable in the column."""
    out = as_text({"note": "число строк"})
    assert "число строк" in out


class TestEverySiteUsesIt:
    """The six fields, named, so a seventh cannot be added without noticing."""

    def test_the_sync_analyzer_routes_every_string_field_through_it(self):
        import inspect

        from app.knowledge import code_db_sync_analyzer as mod

        src = inspect.getsource(mod)
        for field in (
            "data_format_notes",
            "column_sync_notes",
            "business_logic_notes",
            "conversion_warnings",
            "query_recommendations",
            "required_filters",
            "column_value_mappings",
            "global_notes",
            "data_conventions",
            "query_guidelines",
            "join_recommendations",
        ):
            assert f'as_text(args.get("{field}"' in src, f"{field} is not coerced"

    def test_the_db_index_validator_does_too(self):
        import inspect

        from app.knowledge import db_index_validator as mod

        src = inspect.getsource(mod)
        for field in ("summary_text", "recommendations", "column_notes", "numeric_format_notes"):
            assert f'as_text(args.get("{field}"' in src, f"{field} is not coerced"
