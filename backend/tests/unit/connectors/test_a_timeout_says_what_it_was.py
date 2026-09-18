"""C-07 and C-09: one timeout must not leave a connector reporting nonsense.

**C-07** — ClickHouse read `self._client` directly in `introspect_schema` and
`test_connection`. One client-side timeout resets that to `None`, so afterwards the
schema came back **empty** (stored by the pipeline as `completed, tables: 0` — a claim
about the customer's database) and the health probe reported the connection down for
ever, because the loop whose job is to notice recovery could not create a session either.

**C-09** — an SSH-exec timeout carried no `error_type`, so the classifier read the prose,
answered `UNKNOWN`, and the agent spent an LLM repair on a query that was not wrong.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.connectors.base import ConnectionConfig
from app.core.error_types import QueryErrorType


def _ch_connector():
    from app.connectors.clickhouse import ClickHouseConnector

    c = ClickHouseConnector()
    c._config = ConnectionConfig(
        db_type="clickhouse", db_host="127.0.0.1", db_port=9000, db_name="mydb"
    )
    c._client = None
    c._client_kwargs = {"host": "127.0.0.1"}
    return c


@pytest.mark.asyncio
async def test_clickhouse_introspection_recreates_the_session_a_timeout_dropped():
    connector = _ch_connector()
    fresh = MagicMock()
    fresh.query.return_value = MagicMock(result_rows=[])

    with patch("app.connectors.clickhouse.clickhouse_connect.get_client", return_value=fresh):
        schema = await connector.introspect_schema()

    assert connector._client is fresh, "the poisoned session was never replaced"
    assert schema.db_type == "clickhouse"


@pytest.mark.asyncio
async def test_clickhouse_health_probe_can_see_a_recovery():
    connector = _ch_connector()
    fresh = MagicMock()

    with patch("app.connectors.clickhouse.clickhouse_connect.get_client", return_value=fresh):
        alive = await connector.test_connection()

    assert alive is True, "after a timeout the connection could never be reported up again"


@pytest.mark.asyncio
async def test_clickhouse_health_probe_drops_a_session_that_still_fails():
    connector = _ch_connector()
    broken = MagicMock()
    broken.query.side_effect = RuntimeError("session is poisoned")

    with patch("app.connectors.clickhouse.clickhouse_connect.get_client", return_value=broken):
        alive = await connector.test_connection()

    assert alive is False
    assert connector._client is None, "a failing session is dropped, not kept for the next query"


@pytest.mark.asyncio
async def test_an_ssh_exec_timeout_is_typed_as_one():
    import asyncssh

    from app.connectors.ssh_exec import SSHExecConnector

    connector = SSHExecConnector()
    connector._config = ConnectionConfig(
        db_type="mysql",
        db_host="10.0.0.5",
        db_port=3306,
        db_name="shop",
        db_user="u",
        ssh_host="bastion.example.com",
        ssh_user="deploy",
    )

    # asyncssh's own TimeoutError is a ProcessError and carries the process's fields;
    # raising the real one is the point — the connector catches that class, not the
    # builtin.
    async def _timeout(*_a, **_kw):
        raise asyncssh.TimeoutError(None, "mysql …", None, None, None, None, b"", b"")

    with patch.object(SSHExecConnector, "_run_command", new=_timeout):
        result = await connector.execute_query("SELECT count(*) FROM huge")

    assert result.error
    assert result.error_type == QueryErrorType.TIMEOUT, (
        "UNKNOWN sends the agent to an LLM repair; TIMEOUT tells it to narrow the query"
    )


@pytest.mark.asyncio
class TestExecModeQualifiesTablesWithTheirDatabase:
    """C-08: `TableInfo.schema` defaults to PostgreSQL's `public`, and MySQL/ClickHouse
    have no such schema — every statistics query qualified `` `public`.`t` ``, a table
    nobody has, and each failure was swallowed to `[]`. The index then described a
    database with no column statistics at all."""

    async def _introspect(self, db_type: str, stdout_by_kind: dict[str, str]):
        from app.connectors.ssh_exec import SSHExecConnector

        connector = SSHExecConnector()
        connector._config = ConnectionConfig(
            db_type=db_type,
            db_host="10.0.0.5",
            db_port=3306 if db_type == "mysql" else 9000,
            db_name="shop",
            db_user="u",
            ssh_host="bastion.example.com",
            ssh_user="deploy",
        )

        async def _run(_self, command, *_args, **_kwargs):
            for kind, out in stdout_by_kind.items():
                if kind in command:
                    return out, "", 0, False
            return "", "", 0, False

        with patch.object(SSHExecConnector, "_run_command", new=_run):
            return await connector.introspect_schema()

    async def test_mysql(self):
        schema = await self._introspect(
            "mysql",
            {
                "information_schema.tables": (
                    "table_name\ttable_rows\ttable_comment\norders\t10\t\n"
                ),
                "information_schema.columns": (
                    "table_name\tcolumn_name\tcolumn_type\tis_nullable\t"
                    "column_default\tcolumn_key\tcolumn_comment\n"
                    "orders\tid\tint\tNO\tNULL\tPRI\t\n"
                ),
            },
        )

        assert [t.schema for t in schema.tables] == ["shop"]

    async def test_clickhouse(self):
        schema = await self._introspect(
            "clickhouse",
            {
                "system.tables": "name\norders\n",
                "system.columns": "table\tname\ttype\norders\tid\tUInt64\n",
            },
        )

        assert [t.schema for t in schema.tables] == ["shop"]
