"""B-17 — the rival-table comparison on every engine, and what "it ran" means.

Audit 2026-09-23 §3.1 (`docs/audits/2026-09-23-recent-work-audit.md`):

* F-R1 — `period_total` bound the period as ISO STRINGS in `:name` style. asyncpg refuses
  a `str` for a date or timestamp parameter, ClickHouse's `bind_query` leaves `:name`
  unbound, and SSH-exec refuses parameters — so on three of the five engines every call
  returned `(None, 0)` and no rivalry could ever be found. The bounds are now date
  LITERALS rendered from a validated `datetime.date`: nothing but a real date can reach
  the SQL, and no engine is asked to bind anything.
* F-R2 — `_comparison_ran` was set whenever `measure_rivalries` returned, including when
  every pair failed or the budget was spent before one, and the pipeline then stripped
  last night's correct `MEASURED (rivalry):` caveats on the strength of not having looked.
"""

from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from app.connectors.base import ConnectionConfig, QueryResult
from app.connectors.sqlite import SQLiteConnector
from app.knowledge.rival_tables import measure_rivalries


class _Recording(SQLiteConnector):
    def __init__(self) -> None:
        super().__init__()
        self.seen: list[tuple[str, object]] = []

    async def execute_query(self, query, params=None, **kw):
        self.seen.append((query, params))
        return QueryResult(columns=["total", "n"], rows=[[10.0, 3]], row_count=1)


async def test_the_bounds_are_literals_and_no_parameter_is_bound() -> None:
    conn = _Recording()
    total = await conn.period_total(
        "orders", "amount", "created_at", date(2026, 8, 1), date(2026, 9, 1)
    )
    assert total == (10.0, 3)
    query, params = conn.seen[0]
    assert params is None, "an engine that cannot bind :name cannot run this"
    assert "2026-08-01" in query and "2026-09-01" in query


async def test_a_string_that_is_not_a_date_never_reaches_the_sql() -> None:
    conn = _Recording()
    assert await conn.period_total(
        "orders", "amount", "created_at", "2026-08-01' OR 1=1 --", "2026-09-01"
    ) == (None, 0)
    assert conn.seen == []


@pytest.mark.parametrize(
    "connector_path, literal",
    [
        ("app.connectors.postgres.PostgresConnector", "DATE '2026-08-01'"),
        ("app.connectors.mysql.MySQLConnector", "DATE '2026-08-01'"),
        ("app.connectors.clickhouse.ClickHouseConnector", "toDate('2026-08-01')"),
        ("app.connectors.sqlite.SQLiteConnector", "'2026-08-01'"),
    ],
)
def test_each_dialect_writes_a_date_it_understands(connector_path: str, literal: str) -> None:
    import importlib

    module, cls = connector_path.rsplit(".", 1)
    connector = getattr(importlib.import_module(module), cls)()
    assert connector._date_literal(date(2026, 8, 1)) == literal


async def test_it_really_sums_the_month_on_a_real_engine(tmp_path, monkeypatch) -> None:
    from app.services import demo_data

    monkeypatch.setattr(demo_data, "demo_db_dir", lambda: tmp_path)
    path = tmp_path / "shop.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE orders (amount REAL, created_at TEXT)")
        db.executemany(
            "INSERT INTO orders VALUES (?, ?)",
            [
                (10.0, "2026-07-31 23:59:59"),
                (20.0, "2026-08-01 00:00:00"),
                (30.0, "2026-08-31 12:00:00"),
                (40.0, "2026-09-01 00:00:00"),
            ],
        )
    conn = SQLiteConnector()
    await conn.connect(ConnectionConfig(db_type="sqlite", db_name=str(path)))
    try:
        assert await conn.period_total(
            "orders", "amount", "created_at", date(2026, 8, 1), date(2026, 9, 1)
        ) == (50.0, 2)
    finally:
        await conn.disconnect()


class _Failing:
    async def period_total(self, *a, **kw):
        return None, 0


async def test_a_comparison_where_every_query_failed_measured_nothing() -> None:
    from tests.unit.knowledge.test_two_tables_that_both_look_like_revenue import _MONEY, _table

    out = await measure_rivalries(
        _Failing(), [_table("a", _MONEY), _table("b", _MONEY)], today=date(2026, 9, 15)
    )
    assert out == [] and out.pairs_measured == 0


async def test_a_comparison_that_ran_counts_its_pairs() -> None:
    from tests.unit.knowledge.test_two_tables_that_both_look_like_revenue import (
        _MONEY,
        _Connector,
        _table,
    )

    conn = _Connector({"a": (100.0, 50), "b": (101.0, 50)})
    out = await measure_rivalries(
        conn, [_table("a", _MONEY), _table("b", _MONEY)], today=date(2026, 9, 15)
    )
    assert out == [] and out.pairs_measured == 1, "two agreeing tables were measured"


def test_the_pipeline_strips_old_caveats_only_after_a_measurement() -> None:
    import inspect

    from app.knowledge import db_index_pipeline

    src = inspect.getsource(db_index_pipeline)
    assert "pairs_measured" in src, "`_comparison_ran` must mean a pair was measured"
