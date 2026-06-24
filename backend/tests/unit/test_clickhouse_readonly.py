"""C3 (R1): ClickHouse connector opens a DB-enforced read-only session.

When ``ConnectionConfig.is_read_only`` is True, ``connect()`` must pass
``settings={"readonly": 1}`` to ``clickhouse_connect.get_client(...)`` so the
ClickHouse server itself rejects writes / setting changes. When False, the
``settings`` kwarg must be absent (read-write behaviour unchanged).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.connectors.base import ConnectionConfig
from app.connectors.clickhouse import ClickHouseConnector


def _config(*, is_read_only: bool) -> ConnectionConfig:
    # Use the connection_string branch so connect() does not touch the SSH
    # tunnel manager.
    return ConnectionConfig(
        db_type="clickhouse",
        connection_string="clickhouse://user:pass@ch-host:8123/analytics",
        is_read_only=is_read_only,
    )


class TestClickHouseReadOnlySession:
    @pytest.mark.asyncio
    async def test_read_only_passes_settings_readonly_1(self):
        conn = ClickHouseConnector()
        with patch("app.connectors.clickhouse.clickhouse_connect.get_client") as mock_get_client:
            mock_get_client.return_value = MagicMock()
            await conn.connect(_config(is_read_only=True))

        mock_get_client.assert_called_once()
        kwargs = mock_get_client.call_args.kwargs
        assert kwargs.get("settings") == {"readonly": 1}

    @pytest.mark.asyncio
    async def test_writable_omits_settings_kwarg(self):
        conn = ClickHouseConnector()
        with patch("app.connectors.clickhouse.clickhouse_connect.get_client") as mock_get_client:
            mock_get_client.return_value = MagicMock()
            await conn.connect(_config(is_read_only=False))

        mock_get_client.assert_called_once()
        kwargs = mock_get_client.call_args.kwargs
        assert "settings" not in kwargs
