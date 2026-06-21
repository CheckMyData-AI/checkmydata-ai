"""Unit tests for :func:`app.core.datetime_utils.ensure_aware`."""

from datetime import UTC, datetime, timedelta, timezone

from app.core.datetime_utils import ensure_aware


def test_naive_becomes_utc_aware():
    naive = datetime(2026, 1, 2, 3, 4, 5)
    result = ensure_aware(naive)
    assert result is not None
    assert result.tzinfo is UTC
    # Wall-clock fields are unchanged — only the tz label is attached.
    assert result.replace(tzinfo=None) == naive


def test_aware_passes_through_unchanged():
    aware = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    assert ensure_aware(aware) == aware


def test_non_utc_aware_is_preserved():
    other = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone(timedelta(hours=5)))
    result = ensure_aware(other)
    # Existing offset is kept; we never silently rebase a naive-free value.
    assert result.utcoffset() == timedelta(hours=5)


def test_none_passes_through():
    assert ensure_aware(None) is None
