"""Two tables that both look like revenue, and only one of them is.

B-09. Production, 2026-09-15: `payment_histories` sits in the schema index at relevance
4, described as *"historical payment records for users, including transaction details,
payment methods, and associated metadata"*, with hints that recommend joining and
filtering it — **and not one word of warning**. It is movement history including internal
write-offs. Against `purchases` it is off by 4.3x for one month and by a different factor
every other. An agent asked for revenue lands there and answers confidently and wrongly.

No amount of reading `payment_histories` can produce that warning. The fact is not about
the table, it is about the **relationship**: the same aggregate run on both, compared. A
per-file document cannot carry it, which is why every document generated so far describes
the trap accurately and sells it anyway.

So the index computes it. This module decides WHAT to compare — deterministic, cheap, and
testable without a database — and `db_index_pipeline` runs the two aggregates.

The selection is deliberately narrow, because every candidate costs a query against the
customer's database:

- a table qualifies only with **both** a money-shaped numeric column and a date column,
  since a comparison needs a measure and a period;
- a table whose date column carries **no index** is skipped above a row ceiling, because
  the aggregate would be a full scan on a live database and this is a background job that
  must not be felt;
- candidates are ranked by relevance and row count, then capped, and the pairs drawn from
  them are capped again — the pair count is quadratic and the ceiling has to be on the
  product, not on the inputs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from time import monotonic
from typing import Any

from app.connectors.base import ColumnInfo, TableInfo

logger = logging.getLogger(__name__)

#: Names of the column that carries the UNIT an amount is in. Shared with the schema
#: index's B-08 caveat, kept here rather than imported to avoid a cycle;
#: ``tests/unit/knowledge/test_two_tables_that_both_look_like_revenue.py`` pins the two
#: against each other.
CURRENCY_COLUMNS = ("currency", "currency_code", "ccy")

#: Column names that hold a monetary measure. The same list the schema index uses for
#: its currency caveat, kept here rather than imported to avoid a cycle;
#: ``tests/unit/knowledge/test_two_tables_that_both_look_like_revenue.py`` pins the two
#: against each other.
MONEY_NAME_HINTS = ("amount", "price", "total", "cost", "revenue", "fee", "balance", "sum")

#: Types a money column can have. `float`/`double` are absent on purpose: a money column
#: stored as binary floating point is its own finding, and summing one to compare against
#: another would put an accumulated rounding error into a fact this product presents as
#: measured.
MONEY_TYPES = ("int", "bigint", "smallint", "decimal", "numeric", "money")

#: Type fragments that make a column a period axis.
DATE_TYPES = ("date", "time", "timestamp")

#: Above this many rows, a date column with no index is refused: the aggregate becomes a
#: full scan, and a background job that makes the customer's database slow is worse than
#: a missing fact.
UNINDEXED_ROW_CEILING = 2_000_000

#: How many tables may enter the pairing, and how many pairs may leave it. Pairs grow as
#: n(n-1)/2, so the second ceiling is the one that actually bounds the work.
MAX_CANDIDATES = 6
MAX_PAIRS = 8


@dataclass(frozen=True)
class MoneyTable:
    """A table that can answer "how much, in this period"."""

    name: str
    schema: str
    money_column: str
    date_column: str
    row_count: int


def _is_money_column(col: ColumnInfo) -> bool:
    name = col.name.lower()
    dtype = (col.data_type or "").lower()
    if not any(hint in name for hint in MONEY_NAME_HINTS):
        return False
    if name.endswith(("_id", "_count", "_rate", "_percent", "_pct")):
        # `total_count` is a tally and `amount_rate` is a ratio; neither is money, and
        # summing one produces a number that looks like revenue and is not.
        return False
    return any(t in dtype for t in MONEY_TYPES)


def _is_date_column(col: ColumnInfo) -> bool:
    return any(t in (col.data_type or "").lower() for t in DATE_TYPES)


def _is_currency_column(col: ColumnInfo) -> bool:
    """The column that says what unit the amount beside it is in.

    Matched as a whole name or a `_currency` suffix, never as a substring, so
    `currency_rate` — a number, not a unit — is not one. The same rule
    `db_index_validator` uses for the B-08 caveat, and
    ``tests/unit/knowledge/test_two_tables_that_both_look_like_revenue.py`` pins the
    two together.
    """
    name = col.name.lower()
    return name in CURRENCY_COLUMNS or name.endswith("_currency")


def _indexed_columns(table: TableInfo) -> set[str]:
    out: set[str] = set()
    for idx in table.indexes or []:
        cols = list(getattr(idx, "columns", []) or [])
        if cols:
            # Only the LEADING column of an index makes a range scan cheap; a date in
            # third position does not help the aggregate at all.
            out.add(cols[0])
    return out


def _refused(table: str, why: str) -> None:
    """Say why a table was not compared.

    Every rule here removes a table from the comparison silently, and silence is how the
    second production run spent its budget on `partner_phone_number_sms` while
    `payment_histories` — the table this whole step exists for — was absent with no line
    anywhere saying which rule dropped it. A refusal nobody can read is indistinguishable
    from a table that was never there.

    DEBUG rather than INFO: 214 tables produce 214 lines on a nightly, and an operator
    looking for one of them can raise the level.
    """
    logger.debug("rival tables: %s not compared — %s", table, why)


def describe(table: TableInfo) -> MoneyTable | None:
    """The measure and the period axis this table can be aggregated on, or nothing.

    Prefers a `created_at`-shaped column over any other date, because that is the axis a
    revenue question means: an `updated_at` window moves rows between periods every time
    somebody edits one, so two tables compared on it disagree for a reason that has
    nothing to do with their contents.
    """
    if getattr(table, "object_kind", "table") != "table":
        _refused(table.name, "a view's aggregate measures its definition, not the data")
        return None

    money = next((c.name for c in table.columns if _is_money_column(c)), None)
    if money is None:
        _refused(table.name, "no money-shaped numeric column")
        return None

    # A money column is only comparable when the table records what unit it is in.
    #
    # Measured on production 2026-09-15, the first run of this step: without this rule
    # the six pairs it found were `users` vs `balance_transactions` (16x), `purchases`
    # vs `user_crm_profiles` (1522x), `purchases` vs `payment_tokens` (649x) and three
    # more of the same shape — and the ONE pair this whole step exists for,
    # `purchases` vs `payment_histories`, was not among them, crowded out by tables
    # ranked higher.
    #
    # Of those seven tables exactly three carry a currency column: `purchases`,
    # `payment_histories`, and one reporting view. The four that produced the noise
    # carry none. `users.balance` is a STATE in some implied unit rather than a flow,
    # and `user_crm_profiles.total_*` is a tally; comparing either to revenue measures
    # nothing and warns about a table nobody would ask a revenue question about, which
    # is the noise that makes a real warning ignorable.
    #
    # The rule also connects to B-08: a currency column is what makes an amount
    # interpretable at all, and a table that records one is a table that knows it is
    # handling money.
    if not any(_is_currency_column(c) for c in table.columns):
        _refused(table.name, f"`{money}` has no currency column beside it")
        return None

    dates = [c.name for c in table.columns if _is_date_column(c)]
    if not dates:
        _refused(table.name, "no date column to hold a period constant")
        return None
    preferred = next((d for d in dates if "creat" in d.lower()), None)
    date_col = preferred or dates[0]

    rows = table.row_count or 0
    if rows > UNINDEXED_ROW_CEILING and date_col not in _indexed_columns(table):
        _refused(
            table.name,
            f"{rows:,} rows and `{date_col}` leads no index — the aggregate would be a "
            "full scan on a live database",
        )
        return None

    return MoneyTable(
        name=table.name,
        schema=table.schema,
        money_column=money,
        date_column=date_col,
        row_count=rows,
    )


def choose_pairs(
    tables: list[TableInfo],
    relevance: dict[str, int] | None = None,
) -> list[tuple[MoneyTable, MoneyTable]]:
    """Which tables to compare against which, bounded.

    Ranked by the index's own relevance first and row count second, because the tables an
    agent is most likely to reach for are the ones whose rivalry matters. Ties break on
    the name so two runs over the same schema produce the same pairs, and a fact that
    appears and disappears between nights is worse than no fact.
    """
    rel = relevance or {}
    described = [d for d in (describe(t) for t in tables) if d is not None]
    described.sort(key=lambda d: (-rel.get(d.name, 0), -d.row_count, d.name))
    chosen = described[:MAX_CANDIDATES]

    pairs: list[tuple[MoneyTable, MoneyTable]] = []
    for i, left in enumerate(chosen):
        for right in chosen[i + 1 :]:
            pairs.append((left, right))
            if len(pairs) >= MAX_PAIRS:
                return pairs
    return pairs


#: Below this relative gap the two tables are telling the same story and a warning about
#: them would be noise. Above it they cannot both be revenue.
DIVERGENCE_THRESHOLD = 0.10

#: And above THIS, they are not rivals at all.
#:
#: Measured on production 2026-09-15, the second run of this step: with the currency rule
#: in place it reported `purchases` vs `partner_phone_number_sms` at **485 521 961x** and
#: `purchases` vs `kyc_verification_requests` at 162 722x. A ratio of eight orders of
#: magnitude is not a divergence between two accounts of the same thing — it is proof
#: they are accounts of different things, and nobody has ever confused them.
#:
#: The warning is worth reading in the middle band: close enough that the two tables
#: could be mistaken for each other, far enough apart that the mistake is expensive.
#: `purchases` vs `payment_histories`, the pair this step was built for, sits at 4.3x.
#: Everything the run produced above 70x was a pair no reader would ever conflate.
RIVALRY_CEILING = 20.0

#: A period is compared only when both sides have something in it. Comparing a month in
#: which one table is empty measures the backfill, not the relationship.
MIN_ROWS_PER_SIDE = 1


@dataclass(frozen=True)
class Rivalry:
    """What the same aggregate returned on two tables over the same period."""

    left: str
    right: str
    period: str
    left_total: float
    right_total: float

    @property
    def ratio(self) -> float:
        """How many times bigger the larger side is. Infinite when one side is zero and
        the other is not — which is a real answer, not an error: it says one of these
        tables has nothing in a period where the other has money."""
        lo, hi = sorted((abs(self.left_total), abs(self.right_total)))
        if lo == 0:
            return float("inf") if hi > 0 else 1.0
        return hi / lo

    @property
    def diverges(self) -> bool:
        """Far enough apart to be worth a warning, close enough to be a rivalry.

        Bounded at BOTH ends. Under the floor the two agree and the warning is noise;
        over the ceiling they are measuring different things and the warning states the
        obvious loudly, which is the same cost paid twice — an operator who reads one
        absurd caveat stops reading the next one.
        """
        gap = abs(self.ratio - 1.0)
        return DIVERGENCE_THRESHOLD < gap and self.ratio <= RIVALRY_CEILING

    def caveat_for(self, table: str) -> str:
        """The sentence stored on one table's hints, written from its own side."""
        other = self.right if table == self.left else self.left
        mine = self.left_total if table == self.left else self.right_total
        theirs = self.right_total if table == self.left else self.left_total
        bigger = "larger" if mine > theirs else "smaller"
        factor = "∞" if self.ratio == float("inf") else f"{self.ratio:.2f}x"
        return (
            f"MEASURED: over {self.period}, the same aggregate returns {mine:,.2f} here "
            f"and {theirs:,.2f} on `{other}` — {factor} apart, this side {bigger}. "
            f"The two tables are NOT interchangeable for a revenue question; one of them "
            f"counts something the other does not. Establish which before summing either, "
            f"and say which table the answer came from."
        )


#: The period compared: the last calendar month that has fully elapsed. "Last 30 days"
#: would move under the comparison and make two nights disagree for no reason; a partial
#: current month makes the smaller table look smaller for a reason that is only the clock.
def last_complete_month(today: date) -> tuple[str, str, str]:
    """``(start, end, label)`` for the most recent month that has ended, half-open."""
    first_of_this = today.replace(day=1)
    end = first_of_this
    start = (first_of_this - timedelta(days=1)).replace(day=1)
    return start.isoformat(), end.isoformat(), start.strftime("%Y-%m")


async def measure_rivalries(
    connector: Any,
    tables: list[TableInfo],
    *,
    relevance: dict[str, int] | None = None,
    today: date | None = None,
    budget_seconds: float = 120.0,
) -> list[Rivalry]:
    """Run the same aggregate on each chosen pair and return what diverged.

    **Degrades to silence, never to a guess.** A pair whose query fails, whose period is
    empty on either side, or that runs out of budget produces no fact — because the only
    thing worse than no warning about `payment_histories` is a warning about a table that
    turns out to be fine.

    Bounded by wall clock as well as by pair count. The caps bound how many queries are
    issued; the clock bounds what they cost, and only the second survives meeting a table
    the planner decided to scan.
    """
    start, end, label = last_complete_month(today or date.today())
    pairs = choose_pairs(tables, relevance)
    if not pairs:
        return []

    totals: dict[str, tuple[float | None, int]] = {}
    deadline = monotonic() + budget_seconds
    out: list[Rivalry] = []

    async def total_for(t: MoneyTable) -> tuple[float | None, int]:
        if t.name not in totals:
            totals[t.name] = await connector.period_total(
                t.name, t.money_column, t.date_column, start, end, schema=t.schema
            )
        return totals[t.name]

    for left, right in pairs:
        if monotonic() >= deadline:
            logger.info(
                "rival tables: %ds budget spent after %d pair(s); the rest are not compared",
                int(budget_seconds),
                len(out),
            )
            break
        try:
            l_total, l_rows = await total_for(left)
            r_total, r_rows = await total_for(right)
        except Exception:
            logger.debug("rival tables: %s vs %s failed", left.name, right.name, exc_info=True)
            continue

        if l_total is None or r_total is None:
            continue
        if l_rows < MIN_ROWS_PER_SIDE or r_rows < MIN_ROWS_PER_SIDE:
            # One side has nothing in the period. That measures the backfill, not the
            # relationship, and saying "4x apart" about it would be a fabricated warning.
            continue

        rivalry = Rivalry(left.name, right.name, label, l_total, r_total)
        if rivalry.diverges:
            out.append(rivalry)
    return out
