"""KL-1 — an inference must not read like a measurement.

`db_index` and `code_db_sync` mix two kinds of content. Some is introspected fact
(`enum_labels`, `column_count`). Some is an LLM's reading of the codebase
(`data_conventions`, `conversion_warnings`, `business_description`). Both were rendered
into the system prompt in the same voice, with no indication that the second kind was
inferred, or when.

The timestamps already exist — `CodeDbSync.synced_at`, `DbIndex.indexed_at`. They were
simply never shown to the agent. This test pins that they are.

Why it matters more than tidiness: a stale `required_filters` / `conversion_warnings`
entry is the one thing in this layer that makes the agent state a **wrong number
confidently**. If soft-delete was removed from the code and no re-index has run, the
agent dutifully keeps adding a filter that no longer exists and under-reports. Age in
the prompt is what lets it hedge instead.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.agents.sql_agent import format_derived_age


def test_fresh_knowledge_is_not_hedged():
    """Noise on every prompt would train the agent to ignore the marker."""
    assert format_derived_age(datetime.now(UTC) - timedelta(hours=2)) == ""


def test_week_old_knowledge_carries_its_age():
    marker = format_derived_age(datetime.now(UTC) - timedelta(days=9))
    assert "9 days" in marker
    assert "inferred" in marker.lower()


def test_very_stale_knowledge_says_so_plainly():
    marker = format_derived_age(datetime.now(UTC) - timedelta(days=120))
    assert "120 days" in marker
    assert "verify" in marker.lower(), (
        "past a season, the agent should be told to check rather than merely informed"
    )


def test_a_naive_timestamp_does_not_crash_the_prompt():
    """SQLite hands back naive datetimes; a prompt builder must not raise on one."""
    assert isinstance(format_derived_age(datetime.now() - timedelta(days=30)), str)


def test_missing_timestamp_is_silent_rather_than_wrong():
    assert format_derived_age(None) == ""


def test_the_helper_is_actually_wired_into_the_prompt():
    """A provenance marker nobody renders is decoration.

    Asserted on the call, not on wording: the wording is covered above, and this
    check exists so the helper cannot be quietly orphaned by a later refactor.
    """
    import inspect

    from app.agents.sql_agent import SQLAgent

    source = inspect.getsource(SQLAgent._load_sync_for_prompt)
    assert source.count("format_derived_age(") >= 2, (
        "both the conventions summary and the per-table warnings must carry their age"
    )


def test_a_non_datetime_is_silent_rather_than_raising():
    """The caller swallows exceptions, so raising here deletes the whole warning block.

    Regression: passing a MagicMock (as every test double does) previously raised a
    TypeError inside `_load_sync_for_prompt`, whose broad `except` turned it into an
    empty string -- the agent then got a prompt with its safety warnings silently
    missing. A prompt helper must degrade, not raise.
    """
    from unittest.mock import MagicMock

    assert format_derived_age(MagicMock()) == ""
    assert format_derived_age("2026-01-01") == ""
