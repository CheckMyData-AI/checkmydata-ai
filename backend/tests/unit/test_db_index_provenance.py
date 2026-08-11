"""KL-1, second half — the DB side of the same honesty problem.

`index_to_prompt_context` already stamped a date: "## Database Index (analyzed
2026-03-19 14:02)". A raw date is better than nothing and still leaves two things
unsaid, both of which the agent has to infer for itself:

* that `business_description`, `query_hints` and `data_patterns` are an LLM's reading
  of the schema (`db_index_pipeline.py:895` writes `analysis.business_description`),
  not values introspected from the database like `column_count` or `enum_labels`;
* that the reading is old. Asking a model to subtract dates mid-prompt and then
  calibrate its confidence is asking it to do the one thing it is least reliable at.

The sync side (`code_db_sync`) was fixed on 2026-08-09. This makes both halves speak
the same way, using the same helper, so a reader does not learn two conventions.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.services.db_index_service import DbIndexService


def _entry(**kw):
    base = dict(
        table_name="orders",
        row_count=1000,
        relevance_score=5,
        business_description="revenue is stored in minor units",
        query_hints="always filter deleted_at IS NULL",
        data_patterns="",
        column_notes_json="{}",
        is_active=True,
        table_schema="public",
        sample_data_json="[]",
        ordering_column=None,
        latest_record_at=None,
        numeric_format_notes="{}",
        column_distinct_values_json="{}",
        enum_labels_json="{}",
        check_constraints_json="{}",
        column_count=3,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _summary(age_days: int):
    return SimpleNamespace(
        indexed_at=datetime.now(UTC) - timedelta(days=age_days),
        total_tables=1,
        analyzed_tables=1,
        summary_text="",
        recommendations="",
        common_joins="",
        data_quality_notes="",
    )


def test_a_fresh_index_is_not_hedged():
    out = DbIndexService.index_to_prompt_context([_entry()], _summary(1))
    assert "Database Index" in out
    assert "inferred" not in out.lower(), "noise on every prompt trains the model to skip it"


def test_a_stale_index_says_the_descriptions_are_inferred_and_old():
    out = DbIndexService.index_to_prompt_context([_entry()], _summary(140))
    assert "140 days" in out
    assert "verify" in out.lower(), (
        "past a season the agent should be told to check, not merely informed"
    )


def test_the_raw_date_survives():
    """The absolute timestamp stays: age answers 'how stale', the date answers 'since when'."""
    s = _summary(140)
    out = DbIndexService.index_to_prompt_context([_entry()], s)
    assert s.indexed_at.strftime("%Y-%m-%d") in out


def test_no_summary_still_renders():
    out = DbIndexService.index_to_prompt_context([_entry()], None)
    assert "Database Index" in out
