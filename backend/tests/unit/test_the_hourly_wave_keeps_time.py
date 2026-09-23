"""T07 / PRJ-07 S-13 and the two copy-pasted waves.

Both cron loops computed the next boundary as `now.replace(minute=0) + timedelta(hours=1)`
on a zone-aware datetime, which Python does on the WALL clock: across spring-forward the
nonexistent 02:00 was slept to and the hour's schedules were lost, and across fall-back
the repeated hour was treated as the next one. The boundary is now real elapsed time from
the local top of the hour; a skipped local hour is dispatched with the one after it; a
repeated hour is refused by the dispatcher's hour-scoped lock, as before.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.hourly_wave import next_boundary, seconds_between

BERLIN = ZoneInfo("Europe/Berlin")


def _local(y, mo, d, h, mi, fold=0):
    return datetime(y, mo, d, h, mi, tzinfo=BERLIN, fold=fold)


def test_an_ordinary_hour_is_the_next_top_of_the_hour() -> None:
    boundary, hours = next_boundary(_local(2026, 9, 23, 14, 37))
    assert (boundary.hour, boundary.minute) == (15, 0)
    assert hours == [15]


def test_spring_forward_does_not_lose_the_missing_hour() -> None:
    # 2027-03-28: Berlin jumps from 02:00 to 03:00.
    boundary, hours = next_boundary(_local(2027, 3, 28, 1, 40))
    assert boundary.hour == 3
    assert seconds_between(_local(2027, 3, 28, 1, 40), boundary) == 20 * 60
    assert hours == [2, 3], "schedules at 02:00 would never run that night"


def test_fall_back_sleeps_one_real_hour_into_the_repeated_hour() -> None:
    # 2026-10-25: Berlin repeats 02:00-03:00.
    first_two = _local(2026, 10, 25, 2, 30, fold=0)
    boundary, hours = next_boundary(first_two)
    assert boundary.hour == 2 and boundary.fold == 1
    assert seconds_between(first_two, boundary) == 30 * 60
    assert hours == [2], "the repeated hour carries its own label; the lock refuses it"


def test_both_waves_use_the_one_implementation() -> None:
    import inspect

    from app import main

    for loop in (main._daily_knowledge_sync_cron_loop, main._analytics_collect_cron_loop):
        src = inspect.getsource(loop)
        assert "run_hourly_wave" in src, f"{loop.__name__} still keeps its own clock"
        assert "timedelta(hours=1)" not in src
