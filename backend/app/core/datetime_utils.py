"""Small datetime helpers shared across the backend.

SQLite reads ``DateTime(timezone=True)`` columns back as *naive* datetimes
(it has no native tz storage), while PostgreSQL/asyncpg returns tz-aware
values. Comparing or subtracting a naive value against an aware
``datetime.now(UTC)`` raises ``TypeError: can't compare offset-naive and
offset-aware datetimes``. :func:`ensure_aware` normalizes stored timestamps —
which are UTC by construction — so the same code path works on both backends.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import overload


@overload
def ensure_aware(dt: datetime) -> datetime: ...


@overload
def ensure_aware(dt: None) -> None: ...


def ensure_aware(dt: datetime | None) -> datetime | None:
    """Return ``dt`` as a UTC-aware datetime, treating a naive value as UTC.

    ``None`` passes through unchanged; an already-aware datetime is returned
    as-is (its existing tzinfo is preserved).
    """
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt
