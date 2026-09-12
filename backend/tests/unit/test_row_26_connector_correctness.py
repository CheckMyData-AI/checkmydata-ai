"""Board row 26 — five connector defects, each a place where a guard exists and the
data path goes round it.

- **SQL-10** — `SafetyGuard`'s leading-token regex allows a leading `(`; Postgres's
  `_ROW_RETURNING_RE` does not. Two regexes read the same string and disagree, so
  `(SELECT …)` is admitted by the guard and then falls to the non-cursor branch, which
  materialises the whole result set in memory.
- **SQL-05** — `_SHELL_SAFE_RE` ends in `$`, which in Python also matches immediately
  before a trailing newline, so `"10.0.0.5\n"` is classified shell-safe and returned
  unquoted. And the substitution loop re-scans its own output, so a value that *is* a
  placeholder string gets expanded on a later iteration.
- **SQL-09** — MongoDB columns come from `capped[0].keys()`. Heterogeneous documents are
  the point of the model, and `_infer_fields` exists because the connector knows it: a
  field absent from document #1 is invisible in every row, and `d.get(c)` fills the gap
  with `None`, so a reader cannot tell "absent" from "null".
- **SQL-08** — Postgres introspection deliberately returns every non-system schema and
  populates `TableInfo.schema`; the pipeline then passes `table.name` alone, so
  `SELECT * FROM "events"` resolves against `search_path` and samples the wrong table or
  none at all.
- **SQL-03** — MySQL's `SSDictCursor` is unbuffered, so the row cap bounds memory and not
  the wire: closing it spins until EOF, because MySQL cannot be told to stop sending.
"""

from __future__ import annotations

import pytest


class TestTheCursorDecisionAgreesWithTheGuard:
    """SQL-10."""

    @pytest.mark.parametrize(
        "query",
        [
            "(SELECT 1)",
            "  ( SELECT * FROM t )",
            "((SELECT 1) UNION (SELECT 2))",
            "-- a comment\n(SELECT 1)",
        ],
    )
    def test_a_parenthesised_select_still_takes_the_cursor(self, query: str) -> None:
        from app.connectors.postgres import _is_row_returning

        assert _is_row_returning(query), (
            f"{query!r} is admitted by SafetyGuard — its leading-token regex allows the "
            "paren on purpose — and then falls to the non-cursor branch, materialising "
            "the whole result set in the dyno's memory (SQL-10)"
        )

    def test_the_two_readers_agree(self) -> None:
        """The property, rather than four examples of it."""
        from app.connectors.postgres import _is_row_returning
        from app.core.safety import _LEADING_TOKEN

        for query in (
            "(SELECT 1)",
            "SELECT 1",
            "  (((SELECT 1)))",
            "WITH t AS (SELECT 1) SELECT 1",
        ):
            token = _LEADING_TOKEN.match(query)
            assert token, query
            assert _is_row_returning(query), (
                f"the guard reads {token.group(1)!r} from {query!r} and admits it; the "
                "cursor decision reads the same string and refuses"
            )

    def test_a_write_still_does_not_take_the_cursor(self) -> None:
        """Widening must not admit DML — asyncpg cursors need a row-returning statement."""
        from app.connectors.postgres import _is_row_returning

        for query in (
            "UPDATE t SET x=1",
            "(UPDATE t SET x=1)",
            "DELETE FROM t",
            "CREATE TABLE t()",
        ):
            assert not _is_row_returning(query), query


class TestShellEscapingHasNoTrailingNewlineHole:
    """SQL-05."""

    def test_a_trailing_newline_is_not_shell_safe(self) -> None:
        from app.connectors.exec_templates import _shell_escape

        escaped = _shell_escape("10.0.0.5\n")
        assert escaped != "10.0.0.5\n", (
            "`_SHELL_SAFE_RE` ends in `$`, which in Python also matches immediately "
            "before a trailing newline — so the value was classified shell-safe and "
            "returned unquoted, ending the command line early (SQL-05)"
        )
        assert escaped.startswith("'")

    def test_an_ordinary_value_is_still_returned_bare(self) -> None:
        """Quoting everything would work and would make every command unreadable."""
        from app.connectors.exec_templates import _shell_escape

        assert _shell_escape("10.0.0.5") == "10.0.0.5"
        assert _shell_escape("my_db") == "my_db"

    def test_a_value_that_looks_like_a_placeholder_is_not_expanded(self) -> None:
        from app.connectors.exec_templates import format_template

        out = format_template(
            "psql -h {db_host} -d {db_name}",
            {"db_host": "{db_name}", "db_name": "secrets"},
        )
        assert out.count("secrets") == 1, (
            "the loop substituted `db_host` into the result and then re-scanned the "
            f"RESULT for `db_name`, expanding a value as if it were a placeholder: {out!r}"
        )


class TestMongoColumnsCoverEveryDocument:
    """SQL-09."""

    def test_a_field_absent_from_the_first_document_is_still_a_column(self) -> None:
        from app.connectors.mongodb import columns_across

        docs = [{"_id": 1, "name": "a"}, {"_id": 2, "email": "b@x"}, {"_id": 3, "age": 7}]
        assert columns_across(docs) == ["_id", "name", "email", "age"], (
            "columns came from `capped[0].keys()`, so every field not present in "
            "document #1 was invisible — in a store whose whole point is that documents "
            "differ, and whose own `_infer_fields` exists because the connector knows "
            "it (SQL-09)"
        )

    def test_the_first_document_still_sets_the_order(self) -> None:
        """Stable and predictable: a reader's columns must not shuffle between runs."""
        from app.connectors.mongodb import columns_across

        assert columns_across([{"b": 1, "a": 2}, {"c": 3}]) == ["b", "a", "c"]

    def test_no_documents_means_no_columns(self) -> None:
        from app.connectors.mongodb import columns_across

        assert columns_across([]) == []


class TestSchemaQualifiedTablesAreSampledCorrectly:
    """SQL-08."""

    def test_the_sample_targets_the_schema_the_index_found_it_in(self) -> None:
        from app.connectors.base import DatabaseAdapter

        assert DatabaseAdapter._qualified_identifier("events", schema="analytics") == (
            '"analytics"."events"'
        ), (
            "introspection deliberately returns every non-system schema and populates "
            "`TableInfo.schema`; the pipeline passed `table.name` alone, so "
            '`SELECT * FROM "events"` resolved against `search_path` and sampled the '
            "wrong table or none (SQL-08)"
        )

    def test_an_unqualified_table_is_unchanged(self) -> None:
        from app.connectors.base import DatabaseAdapter

        assert DatabaseAdapter._qualified_identifier("events", schema=None) == '"events"'
        assert DatabaseAdapter._qualified_identifier("events", schema="") == '"events"'

    def test_every_pipeline_call_site_passes_the_schema(self) -> None:
        """Each site, not "the string appears somewhere in the module".

        The first draft asserted `"schema=table.schema" in source`. There are four call
        sites, so removing it from one left the substring present in the other three and
        the guard passed — while that table's samples went back to resolving against
        `search_path`.
        """
        import ast
        import inspect

        from app.knowledge import db_index_pipeline

        introspection = {"sample_data", "distinct_values", "approx_stats"}
        tree = ast.parse(inspect.getsource(db_index_pipeline))
        unqualified: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            attr = getattr(node.func, "attr", None)
            if attr not in introspection:
                continue
            if not any(kw.arg == "schema" for kw in node.keywords):
                unqualified.append(f"line {node.lineno}: {ast.unparse(node)[:70]}")
        assert not unqualified, (
            f"{unqualified} address the table by bare name, so the query resolves "
            "against the session `search_path` and reads a table of that name in "
            "`public` — or none at all (SQL-08)"
        )
        assert (
            len(
                [
                    n
                    for n in ast.walk(tree)
                    if isinstance(n, ast.Call) and getattr(n.func, "attr", None) in introspection
                ]
            )
            >= 4
        ), "the sweep found fewer call sites than exist; its matcher has rotted"


class TestMySQLStopsTheServerRatherThanTheReader:
    """SQL-03."""

    async def test_the_session_is_capped_before_the_query_runs(self) -> None:
        """The cap bounded MEMORY and not the WIRE.

        `SSDictCursor` is unbuffered, and closing it calls
        `_finish_unbuffered_query()`, which the driver documents as reading to EOF
        because the MySQL protocol has no way to say "stop sending". So a `SELECT *`
        over a hundred-million-row table transferred every row before `_run` returned,
        one block at a time. The only way to bound the transfer is to stop the server
        producing it.
        """
        from app.connectors.base import MAX_RESULT_ROWS
        from app.connectors.mysql import _apply_row_limit

        statements: list[str] = []
        await _apply_row_limit(_RecordingConn(statements))
        assert statements, "nothing was sent: the server was never told to stop"
        assert f"SQL_SELECT_LIMIT = {MAX_RESULT_ROWS + 1}" in statements[0], statements
        assert "SESSION" in statements[0], (
            "a GLOBAL limit would apply to every other caller on the server"
        )

    async def test_the_limit_leaves_room_for_the_truncation_sentinel(self) -> None:
        """Capping AT the cap would make a full page look complete."""
        from app.connectors.base import MAX_RESULT_ROWS
        from app.connectors.mysql import _apply_row_limit

        statements: list[str] = []
        await _apply_row_limit(_RecordingConn(statements))
        assert str(MAX_RESULT_ROWS) not in statements[0].split("=")[1].strip(), (
            "the client fetches MAX_RESULT_ROWS + 1 to detect truncation; a server "
            f"limit of exactly MAX_RESULT_ROWS hides it: {statements[0]!r}"
        )

    async def test_a_server_that_refuses_the_variable_does_not_fail_the_query(self) -> None:
        """Trading a slow answer for no answer is the wrong direction."""
        from app.connectors.mysql import _apply_row_limit

        await _apply_row_limit(_RaisingConn())  # must not raise

    async def test_the_connector_actually_applies_it(self) -> None:
        """A helper nothing calls is not a fix.

        The tests above exercise `_apply_row_limit` directly, so deleting its call from
        `execute_query` left them all green while the wire went back to unbounded. This
        drives the real `execute_query` and reads what was sent.
        """
        from unittest.mock import AsyncMock, MagicMock

        from app.connectors.base import ConnectionConfig
        from app.connectors.mysql import MySQLConnector

        sent: list[str] = []

        class _Cur:
            description = (("id",),)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_exc):
                return False

            async def execute(self, sql, *_a, **_k):
                sent.append(sql)

            async def fetchmany(self, _n):
                return []

        conn = MagicMock()
        conn.cursor = MagicMock(return_value=_Cur())

        class _Acquire:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *_exc):
                return False

        pool = MagicMock()
        pool.acquire = MagicMock(return_value=_Acquire())

        connector = MySQLConnector()
        connector._pool = pool
        connector.config = ConnectionConfig(
            db_type="mysql", db_host="h", db_port=3306, db_name="d", db_user="u"
        )
        connector._connected = True
        connector.connect = AsyncMock(return_value=True)

        await connector.execute_query("SELECT * FROM users")

        assert any("SQL_SELECT_LIMIT" in statement for statement in sent), (
            "`execute_query` never asked the server to stop producing rows, so the cap "
            f"bounds memory and not the wire again: {sent} (SQL-03)"
        )

    def test_a_timed_out_connection_is_not_returned_to_the_pool(self) -> None:
        import inspect

        from app.connectors.mysql import MySQLConnector

        source = inspect.getsource(MySQLConnector.execute_query)
        assert "conn.close()" in source and "CancelledError" in source, (
            "`asyncio.wait_for` cancels the coroutine mid-cursor, and an unbuffered "
            "MySQL connection interrupted that way still has unread rows on the wire. "
            "Returning it to the pool hands the next caller a connection whose next "
            "read is somebody else's result set — `postgres.py` already terminates its "
            "connection for exactly this reason (SQL-03)"
        )


class _RecordingConn:
    """A connection whose cursor records what was executed on it."""

    def __init__(self, sink: list[str]) -> None:
        self._sink = sink

    def cursor(self):
        sink = self._sink

        class _Cur:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_exc):
                return False

            async def execute(self, sql, *_a, **_k):
                sink.append(sql)

        return _Cur()


class _RaisingConn:
    def cursor(self):
        class _Cur:
            async def __aenter__(self):
                raise RuntimeError("this server has never heard of SQL_SELECT_LIMIT")

            async def __aexit__(self, *_exc):
                return False

        return _Cur()


class TestEveryAdapterAcceptsTheSchema:
    """SQL-08, the half a signature change makes silent.

    Found by doing it: widening the three introspection methods broke five fake
    connectors, and the failures did not read as `TypeError`. The pipeline wraps each
    call in a broad `except Exception`, so a signature mismatch produced **no samples,
    no distinct values and no statistics, with no error anywhere** — exactly the shape
    of a table the connector could not read.

    A production connector that misses the widening fails the same way. Narrowing the
    pipeline's handler is the wrong fix — it exists so one unreadable table does not
    fail a whole index — so the mismatch is caught here instead, where it is loud.
    """

    @pytest.mark.parametrize("method", ["sample_data", "distinct_values", "approx_stats"])
    def test_the_registered_adapters_take_it(self, method: str) -> None:
        import inspect

        from app.connectors.registry import ADAPTER_REGISTRY

        missing: list[str] = []
        for name, cls in ADAPTER_REGISTRY.items():
            fn = getattr(cls, method, None)
            if fn is None:
                continue
            if "schema" not in inspect.signature(fn).parameters:
                missing.append(f"{name}.{method}")
        assert not missing, (
            f"{missing} do not accept `schema`. The pipeline passes it and swallows the "
            "TypeError, so those tables get no samples, no distinct values and no "
            "statistics — indistinguishable from a table nobody could read (SQL-08)"
        )
