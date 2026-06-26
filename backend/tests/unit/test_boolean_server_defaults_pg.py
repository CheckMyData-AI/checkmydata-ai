"""Guard: Boolean columns must use a Postgres-valid boolean server_default.

Regression test for the 2026-06-26 production outage (release v185): the
``connections.send_sample_data_to_llm`` migration used ``server_default=sa.text("1")``
on a Boolean column. SQLite accepts ``1`` for booleans, so every SQLite-only test
(and the local ``alembic upgrade`` check) passed — but PostgreSQL rejects it with
``DatatypeMismatchError: column ... is of type boolean but default expression is of
type integer``, crashing ``alembic upgrade head`` on web boot.

This test compiles every mapped Boolean column's ``server_default`` for the
PostgreSQL dialect and asserts it renders a real boolean literal (``true``/``false``),
not an integer — catching the class of bug at the source (models) without needing a
live Postgres in CI. New Boolean columns MUST use ``sa.true()`` / ``sa.false()``
(or ``sa.text("true")`` / ``sa.text("false")``), never ``sa.text("1")`` / ``"0"``.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateColumn

import app.models  # noqa: F401  — ensure all models are imported/registered
from app.models.base import Base

_PG = postgresql.dialect()


def _boolean_columns_with_server_default():
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, sa.Boolean) and col.server_default is not None:
                yield table.name, col


def test_boolean_columns_have_no_bare_integer_pg_default():
    """A Boolean column must NOT render a BARE INTEGER default on Postgres.

    PG rejects ``DEFAULT 1`` ("boolean but default expression is of type integer")
    — that is the ``sa.text("1")`` form that crashed v185. Quoted string literals
    (``'0'``/``'1'``) and ``true``/``false`` are PG-valid and are left as-is.
    """
    offenders: list[str] = []
    for table_name, col in _boolean_columns_with_server_default():
        ddl = str(CreateColumn(col).compile(dialect=_PG))
        lowered = ddl.lower()
        assert "default" in lowered, f"{table_name}.{col.name}: no DEFAULT rendered ({ddl})"
        # Token right after DEFAULT, e.g. "true" | "false" | "'0'" | "1".
        after = lowered.split("default", 1)[1].strip().split()[0].strip("()")
        if after.isdigit():  # bare unquoted integer — the only PG-incompatible form
            offenders.append(
                f"{table_name}.{col.name} -> DEFAULT {after} (bare integer; use sa.true()/false())"
            )
    assert not offenders, (
        "Boolean column(s) have a BARE-INTEGER Postgres server_default "
        "(crashes alembic on Postgres — use sa.true()/sa.false()):\n  " + "\n  ".join(offenders)
    )


def test_send_sample_data_to_llm_renders_true_on_pg():
    """The exact column that caused the v185 outage now renders `true` on Postgres."""
    col = Base.metadata.tables["connections"].columns["send_sample_data_to_llm"]
    ddl = str(CreateColumn(col).compile(dialect=_PG)).lower()
    assert "default true" in ddl, ddl
