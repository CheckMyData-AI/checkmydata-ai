"""Unit tests for ``CollectOutcome`` (spec §2.4).

The load-bearing distinction: *no errors and zero rows* is ``ok`` — nothing was
due — while *errors and zero rows* is ``failed``. Collapsing the two would let a
broken credential look like a quiet day.
"""

from __future__ import annotations

from app.analytics.outcome import CollectOutcome


def test_no_errors_and_zero_rows_is_ok() -> None:
    outcome = CollectOutcome()

    assert outcome.rows_written == 0
    assert outcome.errors == []
    assert outcome.status == "ok"
    assert outcome.exit_code == 0


def test_no_errors_with_rows_is_ok() -> None:
    outcome = CollectOutcome(rows_written=42, periods_ok=3)

    assert outcome.status == "ok"
    assert outcome.exit_code == 0


def test_only_empty_periods_is_ok() -> None:
    """Periods that genuinely had no data are not a failure."""
    outcome = CollectOutcome(periods_empty=5)

    assert outcome.status == "ok"
    assert outcome.exit_code == 0


def test_errors_with_rows_is_partial() -> None:
    outcome = CollectOutcome(
        rows_written=10,
        periods_ok=1,
        errors=["2026-07-30 overview: quota exhausted"],
    )

    assert outcome.status == "partial"
    assert outcome.exit_code == 1


def test_errors_with_zero_rows_is_failed() -> None:
    outcome = CollectOutcome(errors=["credential rejected"])

    assert outcome.status == "failed"
    assert outcome.exit_code == 2


def test_partial_and_failed_are_distinct_for_the_same_error_list() -> None:
    """The same error must read as ``partial`` or ``failed`` purely on rows."""
    errors = ["2026-07-30 geo: HTTP 500"]

    assert CollectOutcome(rows_written=1, errors=list(errors)).status == "partial"
    assert CollectOutcome(rows_written=0, errors=list(errors)).status == "failed"


def test_error_lists_are_not_shared_between_instances() -> None:
    first = CollectOutcome()
    second = CollectOutcome()

    first.errors.append("boom")

    assert second.errors == []
    assert second.status == "ok"
    assert first.status == "failed"


def test_exit_code_tracks_status_after_mutation() -> None:
    """Collection mutates the outcome as it goes; the properties must follow."""
    outcome = CollectOutcome()
    assert (outcome.status, outcome.exit_code) == ("ok", 0)

    outcome.errors.append("2026-07-31 events: HTTP 429")
    assert (outcome.status, outcome.exit_code) == ("failed", 2)

    outcome.rows_written += 7
    outcome.periods_ok += 1
    assert (outcome.status, outcome.exit_code) == ("partial", 1)
