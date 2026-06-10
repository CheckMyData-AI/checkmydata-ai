"""ClickHouse connector: streaming row cap + connector pool registry."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.connectors.base import MAX_RESULT_ROWS
from app.connectors.clickhouse import ClickHouseConnector
from app.core import connector_pools


class _FakeStream:
    """Mimics clickhouse-connect's row-block stream context manager."""

    def __init__(self, blocks: list[list[tuple]], columns: list[str]):
        self._blocks = blocks
        self.source = MagicMock()
        self.source.column_names = columns
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True
        return False

    def __iter__(self):
        return iter(self._blocks)


def _connector_with_stream(stream: _FakeStream) -> ClickHouseConnector:
    conn = ClickHouseConnector()
    client = MagicMock()
    client.query_row_block_stream = lambda query, parameters=None: stream
    conn._client = client
    return conn


class TestClickHouseStreamingCap:
    @pytest.mark.asyncio
    async def test_small_result_passthrough(self):
        stream = _FakeStream([[(1, "a"), (2, "b")]], ["id", "name"])
        conn = _connector_with_stream(stream)
        result = await conn.execute_query("SELECT 1")
        assert result.error is None
        assert result.columns == ["id", "name"]
        assert result.rows == [[1, "a"], [2, "b"]]
        assert result.truncated is False
        assert stream.closed is True

    @pytest.mark.asyncio
    async def test_row_cap_stops_consuming_blocks(self):
        block = [(i,) for i in range(MAX_RESULT_ROWS)]
        # Second block must never be needed: cap hits inside the first+second.
        stream = _FakeStream([block, [(0,)] * 10, [(0,)] * 10], ["id"])
        conn = _connector_with_stream(stream)
        result = await conn.execute_query("SELECT big")
        assert result.row_count == MAX_RESULT_ROWS
        assert result.truncated is True
        assert stream.closed is True

    @pytest.mark.asyncio
    async def test_exactly_at_cap_not_truncated(self):
        block = [(i,) for i in range(MAX_RESULT_ROWS)]
        stream = _FakeStream([block], ["id"])
        conn = _connector_with_stream(stream)
        result = await conn.execute_query("SELECT big")
        assert result.row_count == MAX_RESULT_ROWS
        assert result.truncated is False

    @pytest.mark.asyncio
    async def test_not_connected(self):
        conn = ClickHouseConnector()
        result = await conn.execute_query("SELECT 1")
        assert result.error == "Not connected"

    @pytest.mark.asyncio
    async def test_query_error_returned(self):
        conn = ClickHouseConnector()
        client = MagicMock()
        client.query_row_block_stream = MagicMock(side_effect=RuntimeError("syntax error"))
        conn._client = client
        result = await conn.execute_query("SELECT bad")
        assert result.error == "syntax error"


class TestConnectorPoolRegistry:
    def setup_method(self):
        connector_pools.reset()

    def teardown_method(self):
        connector_pools.reset()

    def test_registered_pool_visible(self):
        class Owner:
            def __init__(self):
                self._connectors = {"c1:pg": "connector-1"}

        owner = Owner()
        connector_pools.register_pool("sql_agent", owner)
        assert connector_pools.all_connectors() == {"c1:pg": "connector-1"}

    def test_multiple_pools_merged(self):
        class Owner:
            def __init__(self, pool):
                self._connectors = pool

        a = Owner({"c1": 1})
        b = Owner({"c2": 2})
        connector_pools.register_pool("a", a)
        connector_pools.register_pool("b", b)
        assert connector_pools.all_connectors() == {"c1": 1, "c2": 2}

    def test_dead_owner_pruned(self):
        class Owner:
            def __init__(self):
                self._connectors = {"c1": 1}

        owner = Owner()
        connector_pools.register_pool("a", owner)
        del owner
        import gc

        gc.collect()
        assert connector_pools.all_connectors() == {}
        # Registry pruned the dead entry.
        assert connector_pools._pools == {}

    def test_sql_agent_registers_itself(self):
        from unittest.mock import patch

        with (
            patch("app.agents.sql_agent.LLMRouter"),
            patch("app.agents.sql_agent.VectorStore"),
            patch("app.agents.sql_agent.CustomRulesEngine"),
            patch("app.agents.sql_agent.ProjectCacheService"),
        ):
            from app.agents.sql_agent import SQLAgent

            agent = SQLAgent()
            agent._connectors["k1"] = "conn"
            assert connector_pools.all_connectors() == {"k1": "conn"}
