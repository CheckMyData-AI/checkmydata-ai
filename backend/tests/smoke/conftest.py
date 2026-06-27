"""Deterministic substrate for the STARTUP SMOKE suite.

Seeds a tiny, fully deterministic ``orders`` table in a temp aiosqlite
database modeled on a real billing/subscriptions project (we do NOT have
the prod data, so this is a representative schema). Every date is FIXED
(derived from a hardcoded anchor, never ``datetime.now()``) so the expected
aggregates can be hand-computed and asserted exactly.

The seed and all expected values live here as module-level constants so the
tests stay self-verifying: a test recomputes the expected numbers from
``SEED_ROWS`` rather than trusting a magic literal.

Business scenario under test:
  (1) revenue for the last 3 months broken down by payment method;
  (2) weekly cohort analysis over the last 3 months (avg order value,
      number of purchases, total revenue per weekly cohort).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

import aiosqlite
import pytest_asyncio

# ---------------------------------------------------------------------------
# Fixed anchor + window. NOTHING here reads the wall clock.
# ---------------------------------------------------------------------------
# Anchor is mid-June 2026; "last 3 months" is expressed as a hardcoded cutoff
# (inclusive) that the test SQL filters on. One row sits BEFORE the cutoff to
# prove the window filter actually excludes it.
ANCHOR_DATE = "2026-06-15"
WINDOW_CUTOFF = "2026-04-01"  # created_at >= this is "in window"

# Each tuple: (created_at date, amount_cents, payment_method).
# Times are pinned to noon so SQLite's strftime week bucketing is unambiguous.
# Weeks are SQLite ``%W`` (Monday-based week-of-year), e.g. 2026-04-06 -> "14".
_PRE_CUTOFF_ROW = ("2026-03-20", 99_999, "card")  # MUST be excluded by the window.

_IN_WINDOW_ROWS: list[tuple[str, int, str]] = [
    ("2026-04-06", 1_000, "card"),  # %W=14
    ("2026-04-08", 3_000, "apple"),  # %W=14
    ("2026-04-13", 2_000, "google"),  # %W=15
    ("2026-04-15", 2_000, "card"),  # %W=15
    ("2026-04-20", 5_000, "apple"),  # %W=16
    ("2026-05-04", 1_500, "card"),  # %W=18
    ("2026-05-11", 2_500, "google"),  # %W=19
    ("2026-05-18", 4_000, "apple"),  # %W=20
    ("2026-06-01", 3_000, "card"),  # %W=22
    ("2026-06-08", 1_000, "google"),  # %W=23
    ("2026-06-15", 6_000, "apple"),  # %W=24
]

# Full seed (pre-cutoff row first so its id is lowest — order is irrelevant to
# the aggregates, which is itself a property worth not depending on).
SEED_ROWS: list[tuple[str, int, str]] = [_PRE_CUTOFF_ROW, *_IN_WINDOW_ROWS]

# Rows the queries are expected to operate on (window applied).
IN_WINDOW_ROWS: list[tuple[str, int, str]] = list(_IN_WINDOW_ROWS)


# ---------------------------------------------------------------------------
# Hand-computed expectations (derived from IN_WINDOW_ROWS, not magic literals).
# ---------------------------------------------------------------------------
def _expected_revenue_by_method() -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for _date, amount, method in IN_WINDOW_ROWS:
        out[method] += amount
    return dict(out)


EXPECTED_REVENUE_BY_METHOD: dict[str, int] = _expected_revenue_by_method()
EXPECTED_GRAND_TOTAL_CENTS: int = sum(EXPECTED_REVENUE_BY_METHOD.values())
EXPECTED_IN_WINDOW_COUNT: int = len(IN_WINDOW_ROWS)


# ---------------------------------------------------------------------------
# Minimal async "connector": executes a SQL string and returns rows.
# ---------------------------------------------------------------------------
@dataclass
class SmokeRows:
    """Result of a smoke query: column names + row tuples."""

    columns: list[str]
    rows: list[tuple[Any, ...]]


SmokeConnector = Callable[[str], "Any"]  # async (sql) -> SmokeRows


async def _seed(db: aiosqlite.Connection) -> None:
    await db.execute(
        """
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            amount_cents INTEGER NOT NULL,
            payment_method TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    for idx, (date, amount, method) in enumerate(SEED_ROWS, start=1):
        await db.execute(
            "INSERT INTO orders (id, user_id, amount_cents, payment_method, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (idx, 1_000 + idx, amount, method, f"{date} 12:00:00"),
        )
    await db.commit()


@pytest_asyncio.fixture
async def smoke_db() -> AsyncIterator[aiosqlite.Connection]:
    """A fresh, seeded in-memory aiosqlite database per test."""
    db = await aiosqlite.connect(":memory:")
    try:
        await _seed(db)
        yield db
    finally:
        await db.close()


@pytest_asyncio.fixture
async def run_sql(smoke_db: aiosqlite.Connection) -> SmokeConnector:
    """Return an async helper ``run_sql(sql) -> SmokeRows`` over the seed."""

    async def _run(sql: str) -> SmokeRows:
        cur = await smoke_db.execute(sql)
        rows = await cur.fetchall()
        columns = [c[0] for c in cur.description] if cur.description else []
        await cur.close()
        return SmokeRows(columns=columns, rows=[tuple(r) for r in rows])

    return _run
