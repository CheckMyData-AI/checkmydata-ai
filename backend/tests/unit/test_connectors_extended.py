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
        pool.acquire.return_value = _ACM(mock_conn)
        pool.close = AsyncMock()
        return pool

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
        mock_conn.fetch = AsyncMock(return_value=[row1, row2])
        connector._pool = self._make_pool(mock_conn)

        result = await connector.execute_query("SELECT * FROM users")
        assert result.error is None
        assert result.columns == ["id", "name"]
        assert result.row_count == 2
        assert result.rows == [[1, "alice"], [2, "bob"]]

    async def test_execute_query_empty_result(self, connector):
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        connector._pool = self._make_pool(mock_conn)

        result = await connector.execute_query("SELECT * FROM empty")
        assert result.error is None
        assert result.row_count == 0

    async def test_execute_query_with_params(self, connector):
        row = MagicMock()
        row.keys.return_value = ["id"]
        row.values.return_value = [1]

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[row])
        connector._pool = self._make_pool(mock_conn)

        result = await connector.execute_query("SELECT * FROM users WHERE id = :id", {"id": 1})
        assert result.error is None
        mock_conn.fetch.assert_called_once()
        call_args = mock_conn.fetch.call_args
        assert "$1" in call_args[0][0]

    async def test_execute_query_exception(self, connector):
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(side_effect=Exception("connection lost"))
        connector._pool = self._make_pool(mock_conn)

        result = await connector.execute_query("BAD SQL")
        assert result.error is not None
        assert "connection lost" in result.error

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
        mock_cur.fetchall = AsyncMock(
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
        mock_cur.fetchall = AsyncMock(return_value=[])
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
        mock_cur.fetchall = AsyncMock(return_value=[{"id": 1}])
        connector._pool = self._make_pool(mock_cur)

        result = await connector.execute_query("SELECT * FROM t WHERE id = :id", {"id": 1})
        assert result.error is None
        call_args = mock_cur.execute.call_args
        assert "%s" in call_args[0][0]

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

    async def test_execute_query_returns_rows(self, connector):
        mock_result = MagicMock()
        mock_result.column_names = ["id", "name"]
        mock_result.result_rows = [(1, "alice"), (2, "bob")]

        mock_client = MagicMock()
        mock_client.query.return_value = mock_result
        connector._client = mock_client

        result = await connector.execute_query("SELECT * FROM users")
        assert result.error is None
        assert result.columns == ["id", "name"]
        assert result.row_count == 2

    async def test_execute_query_empty(self, connector):
        mock_result = MagicMock()
        mock_result.column_names = []
        mock_result.result_rows = []

        mock_client = MagicMock()
        mock_client.query.return_value = mock_result
        connector._client = mock_client

        result = await connector.execute_query("SELECT * FROM empty")
        assert result.row_count == 0

    async def test_execute_query_exception(self, connector):
        mock_client = MagicMock()
        mock_client.query.side_effect = Exception("network error")
        connector._client = mock_client

        result = await connector.execute_query("BAD")
        assert "network error" in result.error

    async def test_execute_query_with_params(self, connector):
        mock_result = MagicMock()
        mock_result.column_names = ["cnt"]
        mock_result.result_rows = [(5,)]

        mock_client = MagicMock()
        mock_client.query.return_value = mock_result
        connector._client = mock_client

        result = await connector.execute_query(
            "SELECT count() FROM t WHERE x = {val:Int32}",
            params={"val": 10},
        )
        assert result.row_count == 1
        mock_client.query.assert_called_once_with(
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
