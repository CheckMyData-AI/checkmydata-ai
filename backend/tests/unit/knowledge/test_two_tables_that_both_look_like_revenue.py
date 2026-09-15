"""`payment_histories` is the trap, and no document about it can say so.

B-09. Production, 2026-09-15: the schema index carries `payment_histories` at relevance
4, described as *"historical payment records for users, including transaction details,
payment methods, and associated metadata"*, with hints recommending how to join and
filter it, and **no warning of any kind**. It is movement history including internal
write-offs: against `purchases` it is off by 4.3x for one month and by a different factor
every other. An agent asked for revenue lands there and answers confidently and wrongly.

Reading `payment_histories` cannot produce that warning, however carefully. The fact is
not about the table, it is about the **relationship** — the same aggregate run on both,
compared — which is why every document generated so far describes the trap accurately and
sells it anyway.

So the index computes it, and these tests hold the two halves that make the computation
safe to run against a customer's live database: what is chosen, and what is refused.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.connectors.base import ColumnInfo, IndexInfo, TableInfo
from app.knowledge.rival_tables import (
    MAX_PAIRS,
    UNINDEXED_ROW_CEILING,
    Rivalry,
    choose_pairs,
    describe,
    last_complete_month,
    measure_rivalries,
)


def _table(name, cols, *, rows=1000, indexes=(), kind="table"):
    return TableInfo(
        name=name,
        columns=[ColumnInfo(name=c, data_type=t) for c, t in cols],
        row_count=rows,
        indexes=[IndexInfo(name=f"ix_{c}", columns=[c]) for c in indexes],
        object_kind=kind,
    )


_MONEY = [
    ("id", "bigint"),
    ("amount", "bigint"),
    ("currency", "varchar"),
    ("created_at", "datetime"),
]


class TestWhatIsWorthComparing:
    def test_a_table_with_money_and_a_date_qualifies(self) -> None:
        got = describe(_table("purchases", _MONEY))
        assert got is not None
        assert (got.money_column, got.date_column) == ("amount", "created_at")

    def test_a_table_with_no_money_column_is_not_a_candidate(self) -> None:
        assert describe(_table("users", [("id", "bigint"), ("created_at", "datetime")])) is None

    def test_a_table_with_no_date_column_is_not_a_candidate(self) -> None:
        """A comparison needs a period; without one there is nothing to hold constant."""
        assert describe(_table("prices", [("id", "bigint"), ("amount", "bigint")])) is None

    @pytest.mark.parametrize("name", ["total_count", "user_id", "amount_rate", "fee_pct"])
    def test_a_tally_or_a_ratio_is_not_money(self, name: str) -> None:
        """`total_count` is a tally and `amount_rate` is a ratio. Summing either produces
        a number that looks like revenue and is not."""
        table = _table("t", [(name, "bigint"), ("created_at", "datetime")])
        assert describe(table) is None

    def test_a_float_money_column_is_refused(self) -> None:
        """Money in binary floating point is its own finding. Summing one to compare
        against another puts accumulated rounding error inside a fact this product
        presents as measured."""
        table = _table("t", [("amount", "double precision"), ("created_at", "datetime")])
        assert describe(table) is None

    def test_created_at_wins_over_another_date(self) -> None:
        """An `updated_at` window moves rows between periods whenever somebody edits one,
        so two tables compared on it disagree for a reason that is not their contents."""
        table = _table(
            "t",
            [
                ("amount", "bigint"),
                ("currency", "varchar"),
                ("updated_at", "datetime"),
                ("created_at", "datetime"),
            ],
        )
        assert describe(table).date_column == "created_at"

    def test_a_view_is_not_compared(self) -> None:
        """A view's aggregate measures whatever its definition selected, which is a fact
        about the definition rather than about the data."""
        assert describe(_table("v_revenue", _MONEY, kind="matview")) is None

    def test_a_huge_table_with_no_index_on_its_date_is_refused(self) -> None:
        """The aggregate becomes a full scan. A background job that makes the customer's
        database slow is worse than a missing fact."""
        big = _table("events", _MONEY, rows=UNINDEXED_ROW_CEILING + 1)
        assert describe(big) is None

    def test_the_same_table_indexed_on_its_date_is_allowed(self) -> None:
        big = _table("events", _MONEY, rows=UNINDEXED_ROW_CEILING + 1, indexes=["created_at"])
        assert describe(big) is not None

    def test_only_a_leading_index_column_counts(self) -> None:
        """A date in third position does not make the range scan cheap."""
        big = TableInfo(
            name="events",
            columns=[ColumnInfo(name=c, data_type=t) for c, t in _MONEY],
            row_count=UNINDEXED_ROW_CEILING + 1,
            indexes=[IndexInfo(name="ix", columns=["id", "amount", "created_at"])],
        )
        assert describe(big) is None


class TestTheWorkIsBounded:
    def test_pairs_are_capped(self) -> None:
        """Pairs grow as n(n-1)/2, so the ceiling has to be on the product."""
        many = [_table(f"t{i}", _MONEY, rows=100 - i) for i in range(12)]
        assert len(choose_pairs(many)) <= MAX_PAIRS

    def test_the_index_s_own_relevance_ranks_the_candidates(self) -> None:
        tables = [_table("noise", _MONEY, rows=9000), _table("purchases", _MONEY, rows=10)]
        pairs = choose_pairs(tables, relevance={"purchases": 5, "noise": 1})
        assert pairs[0][0].name == "purchases"

    def test_the_same_schema_produces_the_same_pairs(self) -> None:
        """A fact that appears one night and vanishes the next is worse than no fact."""
        tables = [_table(n, _MONEY, rows=500) for n in ("b", "a", "c")]
        assert [(x.name, y.name) for x, y in choose_pairs(tables)] == [
            (x.name, y.name) for x, y in choose_pairs(list(reversed(tables)))
        ]


class TestTheComparison:
    def test_the_production_shape_reproduces(self) -> None:
        """4.3x is the figure the board recorded for August."""
        r = Rivalry("purchases", "payment_histories", "2026-08", 412_000.0, 1_771_600.0)
        assert round(r.ratio, 1) == 4.3
        assert r.diverges is True

    def test_agreement_is_not_a_warning(self) -> None:
        assert Rivalry("a", "b", "2026-08", 100.0, 103.0).diverges is False

    def test_one_empty_side_is_infinite_and_that_is_an_answer(self) -> None:
        """It says one of these tables holds nothing in a period where the other holds
        money, which is exactly what a reader needs to know."""
        r = Rivalry("a", "b", "2026-08", 0.0, 500.0)
        assert r.ratio == float("inf")
        assert "∞" in r.caveat_for("a")

    def test_both_empty_is_not_a_divergence(self) -> None:
        assert Rivalry("a", "b", "2026-08", 0.0, 0.0).diverges is False

    def test_the_caveat_is_written_from_the_reading_table_s_side(self) -> None:
        r = Rivalry("purchases", "payment_histories", "2026-08", 412_000.0, 1_771_600.0)
        assert "`payment_histories`" in r.caveat_for("purchases")
        assert "`purchases`" in r.caveat_for("payment_histories")
        assert "larger" in r.caveat_for("payment_histories")
        assert "smaller" in r.caveat_for("purchases")


class _Connector:
    def __init__(self, totals, *, fail=()):
        self.totals = totals
        self.fail = set(fail)
        self.calls: list[str] = []

    async def period_total(self, table, money, date_col, start, end, schema=None):
        self.calls.append(table)
        if table in self.fail:
            raise RuntimeError("the customer's database said no")
        return self.totals.get(table, (None, 0))


class TestTheRunnerDegradesToSilence:
    _TODAY = date(2026, 9, 15)

    async def test_a_diverging_pair_is_reported(self) -> None:
        conn = _Connector({"purchases": (412_000.0, 900), "payment_histories": (1_771_600.0, 4000)})
        out = await measure_rivalries(
            conn,
            [_table("purchases", _MONEY), _table("payment_histories", _MONEY)],
            today=self._TODAY,
        )
        assert len(out) == 1 and round(out[0].ratio, 1) == 4.3
        assert out[0].period == "2026-08"

    async def test_a_failing_query_produces_no_fact(self) -> None:
        conn = _Connector({"b": (10.0, 5)}, fail=["a"])
        out = await measure_rivalries(
            conn, [_table("a", _MONEY), _table("b", _MONEY)], today=self._TODAY
        )
        assert out == []

    async def test_an_empty_period_on_one_side_produces_no_fact(self) -> None:
        """That measures the backfill, not the relationship — and "4x apart" about it
        would be a fabricated warning."""
        conn = _Connector({"a": (100.0, 7), "b": (0.0, 0)})
        out = await measure_rivalries(
            conn, [_table("a", _MONEY), _table("b", _MONEY)], today=self._TODAY
        )
        assert out == []

    async def test_each_table_is_aggregated_once_however_many_pairs_it_is_in(self) -> None:
        tables = [_table(n, _MONEY, rows=500) for n in ("a", "b", "c")]
        conn = _Connector({n: (float(i + 1) * 1000, 50) for i, n in enumerate("abc")})
        await measure_rivalries(conn, tables, today=self._TODAY)
        assert sorted(conn.calls) == ["a", "b", "c"], conn.calls

    async def test_a_spent_budget_stops_the_comparison(self) -> None:
        conn = _Connector({n: (float(i + 1) * 1000, 50) for i, n in enumerate("abcd")})
        out = await measure_rivalries(
            conn, [_table(n, _MONEY) for n in "abcd"], today=self._TODAY, budget_seconds=0.0
        )
        assert out == []
        assert conn.calls == []


def test_the_period_is_the_last_month_that_has_ended() -> None:
    """Not "the last 30 days", which moves under the comparison, and not the current
    month, which makes the smaller table look smaller for a reason that is the clock."""
    assert last_complete_month(date(2026, 9, 15)) == ("2026-08-01", "2026-09-01", "2026-08")
    assert last_complete_month(date(2026, 1, 3)) == ("2025-12-01", "2026-01-01", "2025-12")


def test_the_money_hints_agree_with_the_schema_index() -> None:
    """Two lists spelling the same idea in two modules drift, and the drift is silent:
    one would start warning about a column the other does not consider money."""
    from app.knowledge.db_index_validator import _AMOUNT_HINTS
    from app.knowledge.rival_tables import MONEY_NAME_HINTS

    assert set(MONEY_NAME_HINTS) == set(_AMOUNT_HINTS)


def test_the_currency_names_agree_with_the_schema_index() -> None:
    """Same argument, and it matters more here: this list now DECIDES what gets
    compared at all, so a divergence would silently change which tables the step
    can see."""
    from app.knowledge.db_index_validator import _CURRENCY_COLUMNS
    from app.knowledge.rival_tables import CURRENCY_COLUMNS

    assert set(CURRENCY_COLUMNS) == set(_CURRENCY_COLUMNS)


class TestAMoneyTableRecordsItsUnit:
    """The rule the first production run demanded, within minutes of shipping.

    Run without it against the real schema, the step found six pairs — `users` vs
    `balance_transactions` (16x), `purchases` vs `user_crm_profiles` (1522x), `purchases`
    vs `payment_tokens` (649x) and three more — and **the one pair it exists for,
    `purchases` vs `payment_histories`, was not among them**, crowded out by tables that
    rank higher and are not about money at all.

    Of those seven tables exactly three carry a currency column, and two of the three are
    the pair that matters. `users.balance` is a STATE in some implied unit rather than a
    flow; `user_crm_profiles.total_*` is a tally. Warning about either is noise on a table
    nobody would ask a revenue question about — and noise is what makes a real warning
    ignorable.
    """

    def test_a_money_column_without_a_currency_column_is_refused(self) -> None:
        wallet = _table(
            "users", [("id", "bigint"), ("balance", "bigint"), ("created_at", "datetime")]
        )
        assert describe(wallet) is None

    @pytest.mark.parametrize("unit", ["currency", "currency_code", "ccy", "settlement_currency"])
    def test_any_spelling_of_the_unit_column_qualifies(self, unit: str) -> None:
        t = _table("t", [("amount", "bigint"), (unit, "varchar"), ("created_at", "datetime")])
        assert describe(t) is not None

    def test_a_rate_is_not_a_unit(self) -> None:
        """`currency_rate` holds a number. Matching it as a substring would readmit
        exactly the tables this rule exists to exclude."""
        t = _table(
            "t", [("amount", "bigint"), ("currency_rate", "decimal"), ("created_at", "datetime")]
        )
        assert describe(t) is None

    def test_the_production_pair_survives_the_rule(self) -> None:
        """The rule has to keep what it was written for."""
        tables = [
            _table(
                "users",
                [("id", "bigint"), ("balance", "bigint"), ("created_at", "datetime")],
                rows=900_000,
            ),
            _table("purchases", _MONEY, rows=10_368),
            _table("payment_histories", _MONEY, rows=40_000),
        ]
        pairs = choose_pairs(tables, relevance={"users": 5, "purchases": 5, "payment_histories": 4})
        names = {frozenset((a.name, b.name)) for a, b in pairs}
        assert frozenset(("purchases", "payment_histories")) in names
        assert all("users" not in p for p in names)


class TestAnAbsurdRatioIsNotARivalry:
    """The second production run's answer, and the rule it gave.

    With the currency rule in place the step reported `purchases` vs
    `partner_phone_number_sms` at **485 521 961x** and `purchases` vs
    `kyc_verification_requests` at 162 722x. Eight orders of magnitude is not a
    divergence between two accounts of the same thing — it is proof they are accounts of
    different things, and nobody has ever confused them.

    The warning earns its place in the middle band: close enough that the two could be
    mistaken for each other, far enough apart that the mistake is expensive. The pair
    this step was built for sits at 4.3x.
    """

    def test_the_pair_it_was_built_for_is_inside_the_band(self) -> None:
        assert (
            Rivalry("purchases", "payment_histories", "2026-08", 412_000.0, 1_771_600.0).diverges
            is True
        )

    @pytest.mark.parametrize("other", [1_771_600.0 * 100, 485_521_961.0, 1e12])
    def test_an_absurd_ratio_is_not_reported(self, other: float) -> None:
        assert Rivalry("purchases", "x", "2026-08", 1.0, other).diverges is False

    def test_one_empty_side_is_no_longer_reported_either(self) -> None:
        """An infinite ratio is the most absurd of all. It still reads as an answer in
        `caveat_for`, for a caller that wants it, but it is not a rivalry: a table with
        nothing in the period is not a rival account of one that has money."""
        assert Rivalry("a", "b", "2026-08", 0.0, 500.0).diverges is False

    def test_the_ceiling_admits_a_plausible_confusion(self) -> None:
        """Gross versus net, or with-tax versus without, land in single digits. The
        ceiling must not cut those out to keep the absurd ones."""
        for ratio in (1.2, 4.3, 12.0, 19.9):
            assert Rivalry("a", "b", "2026-08", 1000.0, 1000.0 * ratio).diverges is True
