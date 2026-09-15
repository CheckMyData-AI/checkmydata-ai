"""Sixty-five per cent of the index hedges, and the agent could not tell.

B-12. Measured on production 2026-09-15 over 214 indexed tables:

- **139** carry hedged prose somewhere in their generated text — *"possibly"*, *"likely"*,
  *"appears to"*, *"suggests"*;
- **209** carry real per-column statistics beside it.

The measurement and the guess sat in one block with nothing to tell them apart, so an
agent reading *"Currency code, likely USD"* had no way to know the indexer had counted
`distinct_count: 14` for that column.

`schema_context_builder` rendered `column_distinct_values_json` under *"Distinct values"*
and **never rendered `column_stats_json` at all** — the same defect B-08 closed one layer
earlier, arriving one layer later. So the agent saw the value LISTS, which the sampler had
spent on identifier columns (`id`, `user_id`, `payment_id`), and not the counts, which is
where the answer lives. For `purchases` that was thirty payment UUIDs on screen and
`currency: 14 distinct` nowhere.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from app.agents.schema_context_builder import (
    _MEASURED_COLUMN_CAP,
    format_table_context,
    render_measured_facts,
)


def _entry(stats: dict | str, **kw) -> SimpleNamespace:
    payload = stats if isinstance(stats, str) else json.dumps(stats)
    return SimpleNamespace(
        table_name=kw.pop("table_name", "purchases"),
        business_description=kw.pop("business_description", ""),
        column_stats_json=payload,
        column_notes_json="{}",
        column_distinct_values_json="{}",
        query_hints="",
        data_patterns="",
        row_count=120_000,
        table_schema="public",
        relevance_score=5,
        latest_record_at=None,
        sample_data_json="[]",
        numeric_format_notes="{}",
        code_match_status="unknown",
        code_match_details="",
        ordering_column=None,
        **kw,
    )


_PRODUCTION = {
    "currency": {"distinct_count": 14, "min": "BRL", "max": "VND", "null_rate": "0"},
    "payment_id": {"distinct_count": 1_034_221, "min": "0000", "max": "ffff", "null_rate": 0},
    "amount": {"distinct_count": 6022, "min": "-3000", "max": "2147483647", "null_rate": 0},
    "deleted_at": {
        "distinct_count": 12,
        "min": "2024-01-01",
        "max": "2026-09-01",
        "null_rate": 0.98,
    },
}


class TestWhatWasCountedIsSaid:
    def test_the_measured_count_reaches_the_agent(self) -> None:
        out = render_measured_facts(_entry(_PRODUCTION))
        assert "currency: 14 distinct" in out
        assert "BRL" in out and "VND" in out

    def test_it_says_that_it_was_counted(self) -> None:
        """The label is the point. A reader who can see which claims were counted can
        discount the ones that were not; a reader who cannot must treat them alike, and
        then the hedged ones read as facts."""
        assert "MEASURED" in render_measured_facts(_entry(_PRODUCTION))

    def test_the_columns_that_settle_a_question_come_first(self) -> None:
        """A low distinct count is an enum and answers something. A high one is an
        identifier and answers nothing, so it must not crowd the other out."""
        lines = render_measured_facts(_entry(_PRODUCTION)).splitlines()[1:]
        assert lines[0].strip().startswith("deleted_at")
        assert lines[-1].strip().startswith("payment_id")

    def test_a_null_rate_is_reported_only_when_there_are_nulls(self) -> None:
        out = render_measured_facts(_entry(_PRODUCTION))
        assert "98% NULL" in out
        currency_line = next(ln for ln in out.splitlines() if "currency" in ln)
        assert "NULL" not in currency_line

    def test_a_constant_column_reports_no_range(self) -> None:
        """`min == max` is not a range, and printing one implies variation that is not
        there."""
        out = render_measured_facts(
            _entry({"status": {"distinct_count": 1, "min": "1", "max": "1", "null_rate": 0}})
        )
        assert "1 distinct" in out
        assert "range" not in out

    def test_a_wide_table_is_capped(self) -> None:
        wide = {f"c{i}": {"distinct_count": i, "min": None, "max": None} for i in range(60)}
        assert len(render_measured_facts(_entry(wide)).splitlines()) == _MEASURED_COLUMN_CAP + 1


class TestItNeverInventsAMeasurement:
    def test_no_statistics_renders_nothing(self) -> None:
        """Silence, not "unknown". A table the sampler skipped and a table with no
        variation are different facts."""
        assert render_measured_facts(_entry({})) == ""

    def test_unreadable_statistics_render_nothing(self) -> None:
        assert render_measured_facts(_entry("{not json")) == ""

    def test_an_entry_without_the_field_renders_nothing(self) -> None:
        """Older rows predate the column, and a prompt builder that raises on one takes
        the whole answer with it."""
        assert render_measured_facts(SimpleNamespace(table_name="t")) == ""

    def test_a_column_with_nothing_countable_is_skipped(self) -> None:
        assert render_measured_facts(_entry({"x": {}, "y": None})) == ""


def test_the_measurement_is_read_before_the_prose() -> None:
    """The prose hedges in 65% of indexed tables. Put the counted fact above it and the
    hedge reads as what it is; put it below and the first thing read is the guess."""
    block = format_table_context(
        _entry(_PRODUCTION, business_description="Currency code, likely USD."),
        None,
        None,
        None,
    )
    assert block.index("MEASURED") < block.index("likely USD")
