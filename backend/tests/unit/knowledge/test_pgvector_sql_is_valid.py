"""The SQL `PgVectorStore` composes must be SQL psycopg3 will accept.

PRJ-01 R2. Production, 2026-09-11 19:48 UTC: a repository rebuild ran 1 174 s and
died in `generate_docs` with

    only '%s', '%b', '%t' are allowed as placeholders, got '%''

psycopg3 scans the query TEXT for client-side placeholders before it reaches the
server, so a literal `%` inside a string literal must be written `%%`. `#344`
(commit `bd256428`, merged 20:43 UTC the day before the failure) added

    kind_clause = " AND doc_id LIKE 'sym:%'"

by concatenation. Nothing caught it: `test_vector_store.py` exercises the Chroma
backend, `make setup` creates SQLite where pgvector's migration is a no-op, and
the store's own unit test asserts the factory and the signatures without ever
executing a statement — so the production backend's SQL had no reader at all.

This test needs no database: it drives the real methods with a stub pool,
captures every statement they compose, and hands each to psycopg's own
client-side scanner — the exact code that raised in production.
"""

import re

import pytest
from psycopg._queries import _split_query

from app.knowledge.pgvector_store import PgVectorStore
from app.models.doc_embedding import DocEmbedding


class _Cursor:
    rowcount = 0

    def fetchone(self):
        return (0,)


class _Conn:
    def __init__(self, sink):
        self._sink = sink

    def execute(self, sql, params=None):
        self._sink.append(sql)
        return _Cursor()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Pool:
    def __init__(self, sink):
        self._sink = sink

    def connection(self):
        return _Conn(self._sink)


def _store():
    """A store with no database behind it — `__init__` opens a real pool."""
    store = object.__new__(PgVectorStore)
    sink: list[str] = []
    store._pool = _Pool(sink)
    return store, sink


def _assert_psycopg_accepts(sql: str) -> None:
    try:
        _split_query(sql.encode("utf-8"))
    except Exception as exc:  # pragma: no cover - the failure IS the message
        pytest.fail(f"psycopg3 refuses this statement: {exc}\n\n{sql}")


@pytest.mark.parametrize("kind", ["all", "symbol", "prose"])
def test_delete_by_source_path_composes_valid_sql(kind):
    store, sink = _store()
    store.delete_by_source_path("p1", "backend/app/x.py", kind=kind)
    assert sink, "the method executed nothing"
    for sql in sink:
        _assert_psycopg_accepts(sql)


def test_the_kind_filter_survives_escaping():
    """`%%` is what psycopg accepts; `sym:%` is what the DELETE must still mean.

    This assertion named `doc_id` when it was first written, because it was written
    from the code rather than from the schema — so it locked in the second defect
    while proving the first was fixed. A test that asserts the bug is worse than no
    test: it makes the next reader trust the wrong name. It reads the real column now,
    and `test_delete_by_source_path_names_only_columns_that_exist` is what makes that
    impossible to get wrong again.
    """
    store, sink = _store()
    store.delete_by_source_path("p1", "backend/app/x.py", kind="symbol")
    sql = sink[0]
    assert " AND id LIKE" in sql
    assert "%%" in sql, "the literal percent must be doubled for the client-side scanner"
    assert "NOT LIKE" not in sql

    store, sink = _store()
    store.delete_by_source_path("p1", "backend/app/x.py", kind="prose")
    assert "NOT LIKE" in sink[0]


def test_every_other_statement_the_store_composes_is_valid_too():
    store, sink = _store()
    store.delete_collection("p1")
    store.count("p1")
    assert len(sink) == 2
    for sql in sink:
        _assert_psycopg_accepts(sql)


# ---------------------------------------------------------------------------
# Parseable is not correct.
#
# PRJ-01 escaped the literal percent in this clause and shipped it. The first
# production rebuild after that deploy failed one line later:
#
#     psycopg.errors.UndefinedColumn: column "doc_id" does not exist
#
# Two defects in one clause, stacked: psycopg refused the statement before
# Postgres could refuse the column, so fixing the outer one merely revealed the
# inner one. The test above proves psycopg will *parse* what the store composes;
# it cannot know whether the columns exist. This one does, from the model — no
# database, so it runs in the same suite on SQLite.
# ---------------------------------------------------------------------------

_SQL_WORD = re.compile(r"\b[a-z_][a-z0-9_]*\b")
_NOT_COLUMNS = {
    # SQL itself
    "select",
    "from",
    "where",
    "and",
    "or",
    "not",
    "like",
    "delete",
    "insert",
    "into",
    "values",
    "on",
    "conflict",
    "do",
    "update",
    "set",
    "as",
    "limit",
    "order",
    "by",
    "count",
    "now",
    "unnest",
    "text",
    "jsonb",
    "vector",
    "distance",
    "asc",
    "desc",
    "excluded",
    "table",
    "if",
    "exists",
    "sym",
    "s",
    "u",
    "b",
    "t",
    "cast",
    "null",
    "using",
    "with",
    "returning",
    "coalesce",
    "is",
    "doc_embeddings",  # the table itself
}


def _referenced_words(sql: str) -> set[str]:
    """Every bare identifier in the statement, minus SQL's own vocabulary."""
    body = re.sub(r"'[^']*'", " ", sql)  # drop string literals
    return {w for w in _SQL_WORD.findall(body.lower()) if w not in _NOT_COLUMNS}


@pytest.mark.parametrize("kind", ["all", "symbol", "prose"])
def test_delete_by_source_path_names_only_columns_that_exist(kind):
    store, sink = _store()
    store.delete_by_source_path("p1", "backend/app/x.py", kind=kind)
    known = {c.name for c in DocEmbedding.__table__.columns}
    for sql in sink:
        unknown = _referenced_words(sql) - known
        assert not unknown, (
            f"the statement names {sorted(unknown)}, which `doc_embeddings` does not have. "
            f"Columns are {sorted(known)}.\n\n{sql}"
        )


def test_the_symbol_filter_uses_the_primary_key_column():
    """Named directly, because the prefix convention lives on the id."""
    store, sink = _store()
    store.delete_by_source_path("p1", "x.py", kind="symbol")
    assert " AND id LIKE 'sym:%%'" in sink[0]
