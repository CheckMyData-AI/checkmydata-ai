"""R1/C1: Postgres connector opens a DB-enforced read-only session.

When ``ConnectionConfig.is_read_only`` is True, ``PostgresConnector.connect``
must pass ``server_settings={"default_transaction_read_only": "on"}`` to
``asyncpg.create_pool`` so the *database* (not just the app-layer regex) rejects
writes/DDL on read-only connections. When False, the key must be absent/None.

Both create_pool call sites are exercised: the ``connection_string`` branch and
the host/port branch.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.connectors.base import ConnectionConfig
from app.connectors.postgres import PostgresConnector

_READ_ONLY_SETTINGS = {"default_transaction_read_only": "on"}


@pytest.fixture
def mock_create_pool():
    """Patch asyncpg.create_pool with an AsyncMock returning a fake pool."""
    with patch("app.connectors.postgres.asyncpg.create_pool", new=AsyncMock()) as m:
        yield m


async def test_connection_string_read_only_sets_server_settings(mock_create_pool):
    config = ConnectionConfig(
        db_type="postgres",
        connection_string="postgresql://u:p@localhost/db",
        is_read_only=True,
    )
    connector = PostgresConnector()

    await connector.connect(config)

    mock_create_pool.assert_awaited_once()
    kwargs = mock_create_pool.await_args.kwargs
    assert kwargs.get("server_settings") == _READ_ONLY_SETTINGS


async def test_connection_string_writable_omits_server_settings(mock_create_pool):
    config = ConnectionConfig(
        db_type="postgres",
        connection_string="postgresql://u:p@localhost/db",
        is_read_only=False,
    )
    connector = PostgresConnector()

    await connector.connect(config)

    mock_create_pool.assert_awaited_once()
    kwargs = mock_create_pool.await_args.kwargs
    assert kwargs.get("server_settings") is None


async def test_host_port_read_only_sets_server_settings(mock_create_pool):
    config = ConnectionConfig(
        db_type="postgres",
        db_host="db.example.com",
        db_port=5432,
        db_name="mydb",
        db_user="admin",
        db_password="secret",
        is_read_only=True,
    )
    connector = PostgresConnector()

    with patch(
        "app.connectors.postgres._tunnel_mgr.get_or_create",
        new=AsyncMock(return_value=("db.example.com", 5432)),
    ):
        await connector.connect(config)

    mock_create_pool.assert_awaited_once()
    kwargs = mock_create_pool.await_args.kwargs
    assert kwargs.get("server_settings") == _READ_ONLY_SETTINGS


async def test_host_port_writable_omits_server_settings(mock_create_pool):
    config = ConnectionConfig(
        db_type="postgres",
        db_host="db.example.com",
        db_port=5432,
        db_name="mydb",
        db_user="admin",
        db_password="secret",
        is_read_only=False,
    )
    connector = PostgresConnector()

    with patch(
        "app.connectors.postgres._tunnel_mgr.get_or_create",
        new=AsyncMock(return_value=("db.example.com", 5432)),
    ):
        await connector.connect(config)

    mock_create_pool.assert_awaited_once()
    kwargs = mock_create_pool.await_args.kwargs
    assert kwargs.get("server_settings") is None
