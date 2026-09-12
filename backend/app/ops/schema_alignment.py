"""What the models say about nullability, and what the migrated schema actually has.

DATA-02. 81 columns across 19 tables are `NOT NULL` in the model and nullable in the
schema Alembic builds. `Mapped[str]` without `| None` makes SQLAlchemy infer
`nullable=False`, and the models rely on that inference throughout; the migrations
that created those tables passed `server_default=…` and no `nullable=False`. A 2026-03
hardening pass closed the gap for eighteen tables and stopped, and every table created
since has diverged again.

That matters more than tidiness, because the two schemas are built by different
things: the tests call `Base.metadata.create_all` and production runs Alembic. Where
they disagree, every test in the suite exercises a database that does not exist.

**The models are the authority here, not the migrations.** They are what the
application code is written against, what `create_all` builds, and what
`alembic autogenerate` compares to — three of the four readers. Making the fourth
agree is the smaller change, and the only one that leaves a single description of the
table.

**The column list is derived, never written down.** Eighty-one entries across
nineteen tables is a list that is stale the day it is typed, and the next table added
would silently rejoin the divergence. Reading `Base.metadata` means a table added next
month is covered without anybody remembering this module exists.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import Boolean, Float, Integer, Numeric, String, Text
from sqlalchemy.sql import ClauseElement

from app.models.base import Base

logger = logging.getLogger(__name__)

#: Tables whose nullability must NOT be tightened from the model, with the reason.
#: Empty today. It exists so that a future exception is a recorded decision rather
#: than a column quietly dropped from the sweep.
EXCLUDED_TABLES: dict[str, str] = {}


def _fill_for(column: Any) -> str | None:
    """What a pre-existing NULL in *column* should become, or ``None`` if unknown.

    Order matters. A server default is the database's own answer and is preferred; a
    Python-side scalar default is the application's answer for the same question. A
    type-shaped zero is the last resort and applies only where the type makes "empty"
    unambiguous — a string, a number, a boolean. For anything else (a timestamp, a
    foreign key, an enum-shaped column with no default) there IS no safe fill, and
    inventing one would write a value the application never chose.
    """
    server_default = getattr(column, "server_default", None)
    if server_default is not None:
        arg = getattr(server_default, "arg", None)
        text = getattr(arg, "text", None) or (arg if isinstance(arg, str) else None)
        if text is not None:
            return str(text)
        if isinstance(arg, ClauseElement):
            # A SQL expression default — `func.now()` on every `created_at` in the
            # schema. Twenty-five columns hang on this branch, and without it they
            # stay divergent for ever. It renders to the expression itself, so the
            # fill is the database's own answer to "what should this be".
            #
            # It CAN fabricate: a row with a NULL `created_at` gets one of now, which
            # is not when it was created. That is why the migration logs the row count
            # it actually filled per column — on a schema where these columns have
            # carried a server default since they were created, the honest expectation
            # is zero, and a non-zero number is something somebody must see.
            return str(arg.compile(compile_kwargs={"literal_binds": True}))

    default = getattr(column, "default", None)
    if default is not None and not getattr(default, "is_callable", False):
        arg = getattr(default, "arg", None)
        if isinstance(arg, str):
            return f"'{arg}'"
        if isinstance(arg, bool):
            return "true" if arg else "false"
        if isinstance(arg, (int, float)):
            return str(arg)

    type_ = column.type
    if isinstance(type_, (String, Text)):
        return "''"
    if isinstance(type_, (Integer, Float, Numeric)):
        return "0"
    if isinstance(type_, Boolean):
        return "false"
    return None


def columns_requiring_not_null() -> list[tuple[str, str, str]]:
    """Every `(table, column, fill)` the alignment migration should tighten.

    A column appears only when the model declares it `NOT NULL` **and** a fill exists
    for it. One with no answer to "what does an existing NULL become" is left out and
    logged by name — writing an invented value into a customer's row is worse than an
    admitted divergence, and a silent skip is worse than both.
    """
    planned: list[tuple[str, str, str]] = []
    unfillable: list[str] = []
    for table in Base.metadata.sorted_tables:
        if table.name in EXCLUDED_TABLES:
            continue
        for column in table.columns:
            if column.nullable or column.primary_key:
                continue
            fill = _fill_for(column)
            if fill is None:
                unfillable.append(f"{table.name}.{column.name}")
                continue
            planned.append((table.name, column.name, fill))
    if unfillable:
        logger.info(
            "schema alignment: %d NOT NULL column(s) have no safe fill and are left "
            "as the migration found them: %s",
            len(unfillable),
            ", ".join(sorted(unfillable)),
        )
    return planned
