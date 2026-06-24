"""R1/C2 — MySQL connector opens a DB-enforced read-only session.

When ``ConnectionConfig.is_read_only`` is True, the connector must pass
``init_command="SET SESSION TRANSACTION READ ONLY"`` to **every**
``aiomysql.create_pool(...)`` call so the database (not just the app-layer
regex) rejects writes. ``init_command`` runs on each new pooled connection;
combined with the existing ``autocommit=True`` (each statement is its own
transaction) any write/DDL raises ``ER_TRANSACTION_READ_ONLY``.

When ``is_read_only`` is False, ``init_command`` must be absent / ``None`` so a
writable connection keeps its normal behaviour.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.connectors.base import ConnectionConfig
from app.connectors.mysql import MySQLConnector

_RO_INIT = "SET SESSION TRANSACTION READ ONLY"


def _make_config(*, is_read_only: bool, use_connection_string: bool) -> ConnectionConfig:
    if use_connection_string:
        return ConnectionConfig(
            db_type="mysql",
            connection_string="mysql://user:pass@db.example.com:3306/appdb",
            is_read_only=is_read_only,
        )
    return ConnectionConfig(
        db_type="mysql",
        db_host="db.example.com",
        db_port=3306,
        db_name="appdb",
        db_user="user",
        db_password="pass",
        is_read_only=is_read_only,
    )


@pytest.fixture
def fake_pool() -> MagicMock:
    pool = MagicMock()
    pool.close = MagicMock()
    pool.wait_closed = AsyncMock()
    return pool


# ---------------------------------------------------------------------------
# connection_string branch
# ---------------------------------------------------------------------------


async def test_read_only_sets_init_command_connection_string(fake_pool: MagicMock) -> None:
    connector = MySQLConnector()
    config = _make_config(is_read_only=True, use_connection_string=True)

    with patch(
        "app.connectors.mysql.aiomysql.create_pool",
        new=AsyncMock(return_value=fake_pool),
    ) as create_pool:
        await connector.connect(config)

    create_pool.assert_awaited_once()
    kwargs = create_pool.await_args.kwargs
    assert kwargs["init_command"] == _RO_INIT
    assert kwargs["autocommit"] is True


async def test_writable_no_init_command_connection_string(fake_pool: MagicMock) -> None:
    connector = MySQLConnector()
    config = _make_config(is_read_only=False, use_connection_string=True)

    with patch(
        "app.connectors.mysql.aiomysql.create_pool",
        new=AsyncMock(return_value=fake_pool),
    ) as create_pool:
        await connector.connect(config)

    create_pool.assert_awaited_once()
    kwargs = create_pool.await_args.kwargs
    assert kwargs.get("init_command") is None
    assert kwargs["autocommit"] is True


# ---------------------------------------------------------------------------
# host/SSH-tunnel branch
# ---------------------------------------------------------------------------


async def test_read_only_sets_init_command_host_branch(fake_pool: MagicMock) -> None:
    connector = MySQLConnector()
    config = _make_config(is_read_only=True, use_connection_string=False)

    with (
        patch(
            "app.connectors.mysql._tunnel_mgr.get_or_create",
            new=AsyncMock(return_value=("127.0.0.1", 13306)),
        ),
        patch(
            "app.connectors.mysql.aiomysql.create_pool",
            new=AsyncMock(return_value=fake_pool),
        ) as create_pool,
    ):
        await connector.connect(config)

    create_pool.assert_awaited_once()
    kwargs = create_pool.await_args.kwargs
    assert kwargs["init_command"] == _RO_INIT
    assert kwargs["autocommit"] is True


async def test_writable_no_init_command_host_branch(fake_pool: MagicMock) -> None:
    connector = MySQLConnector()
    config = _make_config(is_read_only=False, use_connection_string=False)

    with (
        patch(
            "app.connectors.mysql._tunnel_mgr.get_or_create",
            new=AsyncMock(return_value=("127.0.0.1", 13306)),
        ),
        patch(
            "app.connectors.mysql.aiomysql.create_pool",
            new=AsyncMock(return_value=fake_pool),
        ) as create_pool,
    ):
        await connector.connect(config)

    create_pool.assert_awaited_once()
    kwargs = create_pool.await_args.kwargs
    assert kwargs.get("init_command") is None
    assert kwargs["autocommit"] is True
