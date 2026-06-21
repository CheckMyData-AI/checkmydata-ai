from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.connectors.base import QueryResult


class _ACM:
    """Minimal async context manager returning a fixed value."""

    def __init__(self, value):
        self._value = value

    async def __aenter__(self):
        return self._value

    async def __aexit__(self, *args):
        pass


class _AcquireCtx:
    """Mimics asyncpg's ``PoolAcquireContext``: both awaitable (``await
    pool.acquire()``) and an async context manager (``async with
    pool.acquire()``)."""

    def __init__(self, value):
        self._value = value

    def __await__(self):
        async def _acquire():
            return self._value

        return _acquire().__await__()

    async def __aenter__(self):
        return self._value

    async def __aexit__(self, *args):
        pass


# ---------------------------------------------------------------------------
# PostgresConnector
# ---------------------------------------------------------------------------


class TestPostgresConnector:
    @pytest.fixture
    def connector(self):
        from app.connectors.postgres import PostgresConnector

        return PostgresConnector()

    def _make_pool(self, mock_conn):
        pool = MagicMock()
        # asyncpg's ``pool.acquire()`` is a sync call returning a
        # PoolAcquireContext that is both awaitable and an async CM. execute_query
        # now awaits it + releases explicitly (so a timed-out connection can be
        # terminated before release); test_connection/introspect still use the CM.
        pool.acquire = MagicMock(return_value=_AcquireCtx(mock_conn))
        pool.release = AsyncMock()
        pool.close = AsyncMock()
        return pool

    @staticmethod
    def _wire_cursor(mock_conn, rows):
        """Wire the asyncpg server-side cursor flow (R2-1).

        ``conn.transaction()`` is a sync call returning an async CM, and
        ``await conn.cursor(q, *v)`` returns a cursor whose ``fetch(n)``
        yields ``rows``.
        """
        mock_conn.transaction = MagicMock(return_value=_ACM(None))
        cur = MagicMock()
        cur.fetch = AsyncMock(return_value=rows)
        mock_conn.cursor = AsyncMock(return_value=cur)
        return cur

    def test_db_type(self, connector):
        assert connector.db_type == "postgres"

    async def test_execute_query_not_connected(self, connector):
        result = await connector.execute_query("SELECT 1")
        assert result.error == "Not connected"

    async def test_execute_query_returns_rows(self, connector):
        row1 = MagicMock()
        row1.keys.return_value = ["id", "name"]
        row1.values.return_value = [1, "alice"]
        row2 = MagicMock()
        row2.keys.return_value = ["id", "name"]
        row2.values.return_value = [2, "bob"]

        mock_conn = AsyncMock()
        self._wire_cursor(mock_conn, [row1, row2])
        connector._pool = self._make_pool(mock_conn)

        result = await connector.execute_query("SELECT * FROM users")
        assert result.error is None
        assert result.columns == ["id", "name"]
        assert result.row_count == 2
        assert result.rows == [[1, "alice"], [2, "bob"]]
        assert result.truncated is False

    async def test_execute_query_empty_result(self, connector):
        mock_conn = AsyncMock()
        self._wire_cursor(mock_conn, [])
        connector._pool = self._make_pool(mock_conn)

        result = await connector.execute_query("SELECT * FROM empty")
        assert result.error is None
        assert result.row_count == 0

    async def test_execute_query_with_params(self, connector):
        row = MagicMock()
        row.keys.return_value = ["id"]
        row.values.return_value = [1]

        mock_conn = AsyncMock()
        self._wire_cursor(mock_conn, [row])
        connector._pool = self._make_pool(mock_conn)

        result = await connector.execute_query("SELECT * FROM users WHERE id = :id", {"id": 1})
        assert result.error is None
        mock_conn.cursor.assert_awaited_once()
        call_args = mock_conn.cursor.call_args
        assert "$1" in call_args[0][0]
        assert call_args[0][1] == 1

    async def test_execute_query_streams_cap_plus_one_and_truncates(self, connector):
        """R2-1: a cursor that yields MAX_RESULT_ROWS+1 rows must report
        truncated=True and cap the returned rows."""
        from app.connectors.base import MAX_RESULT_ROWS

        def _row(i):
            r = MagicMock()
            r.keys.return_value = ["id"]
            r.values.return_value = [i]
            return r

        rows = [_row(i) for i in range(MAX_RESULT_ROWS + 1)]
        mock_conn = AsyncMock()
        cur = self._wire_cursor(mock_conn, rows)
        connector._pool = self._make_pool(mock_conn)

        result = await connector.execute_query("SELECT * FROM big")
        assert result.truncated is True
        assert result.row_count == MAX_RESULT_ROWS
        assert len(result.rows) == MAX_RESULT_ROWS
        # We asked the cursor for exactly cap + 1 rows.
        cur.fetch.assert_awaited_once_with(MAX_RESULT_ROWS + 1)

    async def test_execute_query_non_select_uses_fetch(self, connector):
        """DDL/DML statements can't use a cursor — they go through fetch()."""
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_conn.cursor = AsyncMock()
        connector._pool = self._make_pool(mock_conn)

        result = await connector.execute_query("UPDATE users SET x = 1")
        assert result.error is None
        mock_conn.fetch.assert_awaited_once()
        mock_conn.cursor.assert_not_called()

    async def test_execute_query_exception(self, connector):
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(side_effect=Exception("connection lost"))
        connector._pool = self._make_pool(mock_conn)

        result = await connector.execute_query("BAD SQL")
        assert result.error is not None
        assert "connection lost" in result.error

    async def test_execute_query_times_out(self, connector):
        """R1-5: a hung query is bounded by asyncio.wait_for."""

        async def _never(*_a, **_k):
            import asyncio as _aio

            await _aio.sleep(10)

        mock_conn = AsyncMock()
        mock_conn.terminate = MagicMock()
        mock_conn.transaction = MagicMock(return_value=_ACM(None))
        cur = MagicMock()
        cur.fetch = _never
        mock_conn.cursor = AsyncMock(return_value=cur)
        connector._pool = self._make_pool(mock_conn)

        with patch("app.connectors.postgres.settings") as mock_settings:
            mock_settings.query_timeout_seconds = 0.05
            result = await connector.execute_query("SELECT * FROM slow")

        assert result.error is not None
        assert "timed out" in result.error

    async def test_timeout_terminates_pooled_connection(self, connector):
        """Re-audit: a query cancelled by the wait_for timeout must terminate
        the underlying connection so the asyncpg pool discards it instead of
        handing the next caller a connection still draining a server-side
        cursor / open transaction."""

        async def _never(*_a, **_k):
            import asyncio as _aio

            await _aio.sleep(10)

        mock_conn = AsyncMock()
        # terminate() is a *sync* asyncpg method — model it with MagicMock so an
        # accidental ``await`` would fail loudly.
        mock_conn.terminate = MagicMock()
        mock_conn.transaction = MagicMock(return_value=_ACM(None))
        cur = MagicMock()
        cur.fetch = _never
        mock_conn.cursor = AsyncMock(return_value=cur)
        pool = self._make_pool(mock_conn)
        connector._pool = pool

        with patch("app.connectors.postgres.settings") as mock_settings:
            mock_settings.query_timeout_seconds = 0.05
            result = await connector.execute_query("SELECT * FROM slow")

        assert result.error is not None and "timed out" in result.error
        # Poisoned connection terminated exactly once, then released so the
        # pool drops it (release of a closed conn is how asyncpg evicts it).
        mock_conn.terminate.assert_called_once()
        pool.release.assert_awaited_once_with(mock_conn)

    async def test_healthy_query_releases_without_terminate(self, connector):
        """A successful query must release the connection back to the pool
        untouched — only timed-out/cancelled connections get terminated."""
        row = MagicMock()
        row.keys.return_value = ["id"]
        row.values.return_value = [1]

        mock_conn = AsyncMock()
        mock_conn.terminate = MagicMock()
        self._wire_cursor(mock_conn, [row])
        pool = self._make_pool(mock_conn)
        connector._pool = pool

        result = await connector.execute_query("SELECT * FROM users")
        assert result.error is None
        mock_conn.terminate.assert_not_called()
        pool.release.assert_awaited_once_with(mock_conn)

    async def test_introspect_schema_not_connected(self, connector):
        schema = await connector.introspect_schema()
        assert schema.db_type == "postgres"
        assert schema.tables == []

    async def test_test_connection_no_pool(self, connector):
        assert await connector.test_connection() is False

    async def test_test_connection_success(self, connector):
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=1)
        connector._pool = self._make_pool(mock_conn)

        assert await connector.test_connection() is True

    async def test_test_connection_failure(self, connector):
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(side_effect=Exception("refused"))
        connector._pool = self._make_pool(mock_conn)

        assert await connector.test_connection() is False

    async def test_disconnect(self, connector):
        mock_pool = MagicMock()
        mock_pool.close = AsyncMock()
        connector._pool = mock_pool
        await connector.disconnect()
        mock_pool.close.assert_awaited_once()
        assert connector._pool is None

    async def test_disconnect_noop_when_no_pool(self, connector):
        await connector.disconnect()


class TestIsRowReturning:
    def test_select_variants_are_row_returning(self):
        from app.connectors.postgres import _is_row_returning

        for q in (
            "SELECT 1",
            "  select * from t",
            "WITH cte AS (SELECT 1) SELECT * FROM cte",
            "VALUES (1), (2)",
            "EXPLAIN SELECT 1",
            "SHOW search_path",
            "TABLE users",
        ):
            assert _is_row_returning(q) is True, q

    def test_dml_ddl_not_row_returning(self):
        from app.connectors.postgres import _is_row_returning

        for q in (
            "UPDATE t SET a = 1",
            "INSERT INTO t VALUES (1)",
            "DELETE FROM t",
            "CREATE TABLE t (id int)",
            "BAD SQL",
        ):
            assert _is_row_returning(q) is False, q

    def test_leading_comments_are_stripped(self):
        from app.connectors.postgres import _is_row_returning

        assert _is_row_returning("-- comment\nSELECT 1") is True
        assert _is_row_returning("/* block */ SELECT 1") is True
        assert _is_row_returning("-- c\n/* b */\nUPDATE t SET a=1") is False


class TestDictToPositionalPostgres:
    def test_converts_named_to_positional(self):
        from app.connectors.postgres import _dict_to_positional

        query = "SELECT * FROM t WHERE a = :val AND b = :val"
        converted, values = _dict_to_positional(query, {"val": 42})
        assert "$1" in converted
        assert ":val" not in converted
        assert values == [42]

    def test_unknown_param_left_unchanged(self):
        from app.connectors.postgres import _dict_to_positional

        query = "SELECT * FROM t WHERE a = :known AND b = :unknown"
        converted, values = _dict_to_positional(query, {"known": "x"})
        assert "$1" in converted
        assert ":unknown" in converted
        assert values == ["x"]

    def test_multiple_params(self):
        from app.connectors.postgres import _dict_to_positional

        query = "WHERE a = :x AND b = :y"
        converted, values = _dict_to_positional(query, {"x": 1, "y": 2})
        assert ":x" not in converted
        assert ":y" not in converted
        assert len(values) == 2


# ---------------------------------------------------------------------------
# MySQLConnector
# ---------------------------------------------------------------------------


class _MySQLCursorACM:
    def __init__(self, cursor):
        self._cursor = cursor

    async def __aenter__(self):
        return self._cursor

    async def __aexit__(self, *args):
        pass


class TestMySQLConnector:
    @pytest.fixture
    def connector(self):
        from app.connectors.mysql import MySQLConnector

        return MySQLConnector()

    def _make_pool(self, mock_cursor):
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = _MySQLCursorACM(mock_cursor)

        pool = MagicMock()
        pool.acquire.return_value = _ACM(mock_conn)
        pool.close = MagicMock()
        pool.wait_closed = AsyncMock()
        return pool

    def test_db_type(self, connector):
        assert connector.db_type == "mysql"

    async def test_execute_query_not_connected(self, connector):
        result = await connector.execute_query("SELECT 1")
        assert result.error == "Not connected"

    async def test_execute_query_returns_rows(self, connector):
        mock_cur = AsyncMock()
        mock_cur.execute = AsyncMock()
        mock_cur.fetchmany = AsyncMock(
            return_value=[
                {"id": 1, "name": "alice"},
                {"id": 2, "name": "bob"},
            ]
        )
        connector._pool = self._make_pool(mock_cur)

        result = await connector.execute_query("SELECT * FROM users")
        assert result.error is None
        assert result.row_count == 2
        assert result.columns == ["id", "name"]

    async def test_execute_query_empty(self, connector):
        mock_cur = AsyncMock()
        mock_cur.execute = AsyncMock()
        mock_cur.fetchmany = AsyncMock(return_value=[])
        connector._pool = self._make_pool(mock_cur)

        result = await connector.execute_query("SELECT * FROM empty")
        assert result.row_count == 0

    async def test_execute_query_exception(self, connector):
        mock_cur = AsyncMock()
        mock_cur.execute = AsyncMock(side_effect=Exception("access denied"))
        connector._pool = self._make_pool(mock_cur)

        result = await connector.execute_query("BAD")
        assert "access denied" in result.error

    async def test_execute_query_with_dict_params(self, connector):
        mock_cur = AsyncMock()
        mock_cur.execute = AsyncMock()
        mock_cur.fetchmany = AsyncMock(return_value=[{"id": 1}])
        connector._pool = self._make_pool(mock_cur)

        result = await connector.execute_query("SELECT * FROM t WHERE id = :id", {"id": 1})
        assert result.error is None
        call_args = mock_cur.execute.call_args
        assert "%s" in call_args[0][0]

    async def test_execute_query_uses_server_side_cursor(self, connector):
        """F-ARCH-5: the data path must use the unbuffered SSDictCursor and bound
        the fetch to MAX_RESULT_ROWS + 1 instead of fetchall()."""
        import aiomysql

        from app.connectors.base import MAX_RESULT_ROWS

        mock_cur = AsyncMock()
        mock_cur.execute = AsyncMock()
        mock_cur.fetchmany = AsyncMock(return_value=[{"id": 1}])
        mock_conn = MagicMock()
        mock_conn.cursor = MagicMock(return_value=_MySQLCursorACM(mock_cur))
        pool = MagicMock()
        pool.acquire.return_value = _ACM(mock_conn)
        connector._pool = pool

        await connector.execute_query("SELECT * FROM users")

        # Streaming cursor requested, and we never call fetchall().
        mock_conn.cursor.assert_called_once_with(aiomysql.SSDictCursor)
        mock_cur.fetchmany.assert_awaited_once_with(MAX_RESULT_ROWS + 1)
        assert not mock_cur.fetchall.called

    async def test_execute_query_caps_and_reports_truncated(self, connector):
        """A result of MAX_RESULT_ROWS + 1 rows is capped and flagged truncated."""
        from app.connectors.base import MAX_RESULT_ROWS

        rows = [{"id": i} for i in range(MAX_RESULT_ROWS + 1)]
        mock_cur = AsyncMock()
        mock_cur.execute = AsyncMock()
        mock_cur.fetchmany = AsyncMock(return_value=rows)
        connector._pool = self._make_pool(mock_cur)

        result = await connector.execute_query("SELECT * FROM big")
        assert result.truncated is True
        assert result.row_count == MAX_RESULT_ROWS
        assert len(result.rows) == MAX_RESULT_ROWS

    async def test_execute_query_byte_guard_truncates(self, connector):
        """A small row count whose payload exceeds the byte cap is trimmed."""
        from app.connectors.base import MAX_RESULT_BYTES

        big = "x" * (MAX_RESULT_BYTES // 2 + 1)
        rows = [{"blob": big}, {"blob": big}, {"blob": big}]
        mock_cur = AsyncMock()
        mock_cur.execute = AsyncMock()
        mock_cur.fetchmany = AsyncMock(return_value=rows)
        connector._pool = self._make_pool(mock_cur)

        result = await connector.execute_query("SELECT blob FROM wide")
        assert result.truncated is True
        assert len(result.rows) < 3

    async def test_introspect_schema_not_connected(self, connector):
        schema = await connector.introspect_schema()
        assert schema.db_type == "mysql"
        assert schema.tables == []

    async def test_test_connection_no_pool(self, connector):
        assert await connector.test_connection() is False

    def test_dict_to_positional(self, connector):
        query = "SELECT * FROM t WHERE a = :name"
        converted, params = connector._dict_to_positional(query, {"name": "test"})
        assert "%s" in converted
        assert ":name" not in converted
        assert params == ("test",)


# ---------------------------------------------------------------------------
# MongoDBConnector
# ---------------------------------------------------------------------------


class TestMongoDBConnector:
    @pytest.fixture
    def connector(self):
        from app.connectors.mongodb import MongoDBConnector

        return MongoDBConnector()

    def test_db_type(self, connector):
        assert connector.db_type == "mongodb"

    async def test_execute_query_not_connected(self, connector):
        result = await connector.execute_query("{}")
        assert result.error == "Not connected"

    async def test_execute_query_find(self, connector):
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[
                {"_id": "abc", "name": "alice"},
                {"_id": "def", "name": "bob"},
            ]
        )
        mock_cursor.limit = MagicMock(return_value=mock_cursor)

        mock_coll = MagicMock()
        mock_coll.find.return_value = mock_cursor

        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_coll)
        connector._db = mock_db

        query = json.dumps(
            {
                "collection": "users",
                "operation": "find",
                "filter": {},
            }
        )
        result = await connector.execute_query(query)
        assert result.error is None
        assert result.row_count == 2
        assert result.rows[0][0] == "abc"

    async def test_execute_query_byte_guard_truncates(self, connector):
        """A few very wide documents exceeding the byte cap are trimmed and flagged,
        matching the SQL connectors (mongodb previously only capped row count)."""
        from app.connectors.base import MAX_RESULT_BYTES

        big = "x" * (MAX_RESULT_BYTES // 2 + 1)
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[
                {"_id": "a", "blob": big},
                {"_id": "b", "blob": big},
                {"_id": "c", "blob": big},
            ]
        )
        mock_cursor.limit = MagicMock(return_value=mock_cursor)
        mock_coll = MagicMock()
        mock_coll.find.return_value = mock_cursor
        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_coll)
        connector._db = mock_db

        query = json.dumps({"collection": "wide", "operation": "find", "filter": {}})
        result = await connector.execute_query(query)
        assert result.truncated is True
        assert len(result.rows) < 3

    async def test_execute_query_count(self, connector):
        mock_coll = AsyncMock()
        mock_coll.count_documents = AsyncMock(return_value=42)

        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_coll)
        connector._db = mock_db

        query = json.dumps(
            {
                "collection": "users",
                "operation": "count",
                "filter": {},
            }
        )
        result = await connector.execute_query(query)
        assert result.row_count == 1
        assert result.rows == [[42]]

    async def test_execute_query_missing_collection_key(self, connector):
        connector._db = MagicMock()
        query = json.dumps({"operation": "find"})
        result = await connector.execute_query(query)
        assert result.error is not None
        assert "collection" in result.error

    async def test_execute_query_unsupported_operation(self, connector):
        mock_coll = MagicMock()
        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_coll)
        connector._db = mock_db

        query = json.dumps(
            {
                "collection": "users",
                "operation": "delete_many",
            }
        )
        result = await connector.execute_query(query)
        assert "Unsupported" in result.error

    async def test_execute_query_invalid_json(self, connector):
        connector._db = MagicMock()
        result = await connector.execute_query("NOT JSON")
        assert result.error is not None

    async def test_execute_query_empty_find(self, connector):
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_cursor.limit = MagicMock(return_value=mock_cursor)

        mock_coll = MagicMock()
        mock_coll.find.return_value = mock_cursor

        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_coll)
        connector._db = mock_db

        query = json.dumps(
            {
                "collection": "users",
                "operation": "find",
                "filter": {},
            }
        )
        result = await connector.execute_query(query)
        assert result.row_count == 0

    async def test_introspect_schema_not_connected(self, connector):
        schema = await connector.introspect_schema()
        assert schema.db_type == "mongodb"
        assert schema.tables == []

    async def test_test_connection_no_client(self, connector):
        assert await connector.test_connection() is False

    async def test_test_connection_success(self, connector):
        mock_client = AsyncMock()
        mock_client.admin.command = AsyncMock(return_value={"ok": 1})
        connector._client = mock_client
        assert await connector.test_connection() is True

    async def test_test_connection_failure(self, connector):
        mock_client = AsyncMock()
        mock_client.admin.command = AsyncMock(side_effect=Exception("timeout"))
        connector._client = mock_client
        assert await connector.test_connection() is False

    async def test_disconnect(self, connector):
        mock_client = MagicMock()
        connector._client = mock_client
        connector._db = MagicMock()
        await connector.disconnect()
        mock_client.close.assert_called_once()
        assert connector._client is None
        assert connector._db is None

    async def test_sample_data_delegates(self, connector):
        connector._db = MagicMock()
        with patch.object(
            connector,
            "execute_query",
            new_callable=AsyncMock,
            return_value=QueryResult(row_count=3),
        ) as mock_eq:
            result = await connector.sample_data("users", limit=3)
        assert result.row_count == 3
        mock_eq.assert_called_once()


# ---------------------------------------------------------------------------
# ClickHouseConnector
# ---------------------------------------------------------------------------


class TestClickHouseConnector:
    @pytest.fixture
    def connector(self):
        from app.connectors.clickhouse import ClickHouseConnector

        return ClickHouseConnector()

    def test_db_type(self, connector):
        assert connector.db_type == "clickhouse"

    async def test_execute_query_not_connected(self, connector):
        result = await connector.execute_query("SELECT 1")
        assert result.error == "Not connected"

    @staticmethod
    def _stream(blocks, columns):
        """Mimic clickhouse-connect's row-block stream context manager."""
        stream = MagicMock()
        stream.source.column_names = columns
        stream.__enter__ = MagicMock(return_value=stream)
        stream.__exit__ = MagicMock(return_value=False)
        stream.__iter__ = MagicMock(side_effect=lambda: iter(blocks))
        return stream

    async def test_execute_query_returns_rows(self, connector):
        mock_client = MagicMock()
        mock_client.query_row_block_stream.return_value = self._stream(
            [[(1, "alice"), (2, "bob")]], ["id", "name"]
        )
        connector._client = mock_client

        result = await connector.execute_query("SELECT * FROM users")
        assert result.error is None
        assert result.columns == ["id", "name"]
        assert result.row_count == 2

    async def test_execute_query_empty(self, connector):
        mock_client = MagicMock()
        mock_client.query_row_block_stream.return_value = self._stream([], [])
        connector._client = mock_client

        result = await connector.execute_query("SELECT * FROM empty")
        assert result.row_count == 0

    async def test_execute_query_exception(self, connector):
        mock_client = MagicMock()
        mock_client.query_row_block_stream.side_effect = Exception("network error")
        connector._client = mock_client

        result = await connector.execute_query("BAD")
        assert "network error" in result.error

    async def test_execute_query_with_params(self, connector):
        mock_client = MagicMock()
        mock_client.query_row_block_stream.return_value = self._stream([[(5,)]], ["cnt"])
        connector._client = mock_client

        result = await connector.execute_query(
            "SELECT count() FROM t WHERE x = {val:Int32}",
            params={"val": 10},
        )
        assert result.row_count == 1
        mock_client.query_row_block_stream.assert_called_once_with(
            "SELECT count() FROM t WHERE x = {val:Int32}",
            parameters={"val": 10},
        )

    async def test_introspect_schema_not_connected(self, connector):
        schema = await connector.introspect_schema()
        assert schema.db_type == "clickhouse"
        assert schema.tables == []

    async def test_test_connection_no_client(self, connector):
        assert await connector.test_connection() is False

    async def test_test_connection_success(self, connector):
        mock_client = MagicMock()
        mock_client.query.return_value = MagicMock()
        connector._client = mock_client
        assert await connector.test_connection() is True

    async def test_test_connection_failure(self, connector):
        mock_client = MagicMock()
        mock_client.query.side_effect = Exception("refused")
        connector._client = mock_client
        assert await connector.test_connection() is False

    async def test_disconnect(self, connector):
        mock_client = MagicMock()
        connector._client = mock_client
        await connector.disconnect()
        mock_client.close.assert_called_once()
        assert connector._client is None

    async def test_disconnect_noop(self, connector):
        await connector.disconnect()


# ---------------------------------------------------------------------------
# Result byte guard (shared across connectors)
# ---------------------------------------------------------------------------


class TestCapRowsByBytes:
    def test_under_budget_returns_all(self):
        from app.connectors.base import cap_rows_by_bytes

        rows = [["a", 1], ["b", 2]]
        capped, truncated = cap_rows_by_bytes(rows, max_bytes=1000)
        assert capped == rows
        assert truncated is False

    def test_over_budget_trims_and_flags(self):
        from app.connectors.base import cap_rows_by_bytes

        rows = [["x" * 10], ["y" * 10], ["z" * 10]]
        capped, truncated = cap_rows_by_bytes(rows, max_bytes=15)
        assert truncated is True
        assert len(capped) < len(rows)

    def test_single_oversized_row_is_kept(self):
        from app.connectors.base import cap_rows_by_bytes

        rows = [["x" * 100]]
        capped, truncated = cap_rows_by_bytes(rows, max_bytes=10)
        assert capped == rows
        assert truncated is False

    def test_handles_bytes_and_none(self):
        from app.connectors.base import _estimate_value_bytes

        assert _estimate_value_bytes(None) == 0
        assert _estimate_value_bytes(b"abcd") == 4
        assert _estimate_value_bytes("abc") == 3
        assert _estimate_value_bytes(123) == 3
