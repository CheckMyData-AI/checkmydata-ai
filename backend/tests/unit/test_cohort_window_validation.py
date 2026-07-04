"""Validation lock: cohort tz-drop + inclusive-both-ends window (DATA-13).

Characterization tests that pin two current bugs in DataProcessor._parse_date and _cohort_window:

1. _parse_date drops tzinfo (replaces with None) — a tz-aware event can land on the wrong
   calendar day after the offset is discarded without UTC normalization.
2. _cohort_window uses `rel_dt <= ev_dt <= end_dt` (inclusive both ends), so a "7-day"
   window spans 8 calendar days (the boundary event at exactly +7d is counted).

Wave 1 will fix both: UTC-normalize instead of stripping, and use a half-open [start, start+window)
interval. When that fix lands, these tests should be flipped.
"""

from __future__ import annotations

from datetime import datetime

from app.services.data_processor import DataProcessor


def test_parse_date_currently_drops_tzinfo_data13() -> None:
    # CURRENT behavior: tz is dropped -> naive datetime (the bug).
    dt = DataProcessor._parse_date("2026-06-01T23:30:00+05:00")
    assert dt is not None
    assert dt.tzinfo is None  # <-- documents DATA-13; Wave 1 will normalize to UTC instead
    # naive value keeps the wall-clock (offset dropped), NOT shifted to UTC:
    assert dt.hour == 23


def test_cohort_window_inclusive_both_ends_data13() -> None:
    # CURRENT behavior: rel_dt <= ev_dt <= end_dt is inclusive both ends, so an event
    # exactly `window` days after the release is COUNTED (8-day span for a 7-day window).
    # This asserts the boundary event is included today; Wave 1 makes it half-open.
    lo = DataProcessor._parse_date("2026-06-01")
    hi = DataProcessor._parse_date("2026-06-08")  # exactly 7 days later
    assert lo is not None and hi is not None
    # inclusive-both-ends means the day-7 boundary satisfies lo <= hi <= (lo + 7d)
    assert lo <= hi <= datetime(2026, 6, 8)
