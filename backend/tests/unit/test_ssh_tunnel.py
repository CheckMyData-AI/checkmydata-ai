"""Tests for SSHTunnel.is_alive with restricted-shell accounts."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.connectors.ssh_tunnel import SSHTunnel, SSHTunnelManager


class _FakeRunResult:
    """Mimics asyncssh.SSHCompletedProcess."""

    def __init__(self, stdout: str = "", exit_status: int | None = 0):
        self.stdout = stdout
        self.exit_status = exit_status


class TestSSHTunnelIsAlive:
    @pytest.mark.asyncio
    async def test_alive_with_shell_echo(self):
        tunnel = SSHTunnel()
        tunnel._conn = MagicMock()
        tunnel._listener = MagicMock()
        tunnel._listener.get_port.return_value = 12345

        mock_socket = MagicMock()
        tunnel._conn.get_extra_info.return_value = mock_socket

        result = _FakeRunResult(
            stdout=f"something {SSHTunnel._ALIVE_MARKER} something",
            exit_status=0,
        )
        tunnel._conn.run = AsyncMock(return_value=result)

        assert await tunnel.is_alive() is True

    @pytest.mark.asyncio
    async def test_alive_with_nologin_shell(self):
        """When the SSH user has a nologin shell, the echo command fails
        but the tunnel should still be considered alive if transport is open."""
        tunnel = SSHTunnel()
        tunnel._conn = MagicMock()
        tunnel._listener = MagicMock()
        tunnel._listener.get_port.return_value = 12345

        tunnel._conn.get_extra_info.return_value = MagicMock()

        result = _FakeRunResult(
            stdout="This account is currently not available.\n",
            exit_status=1,
        )
        tunnel._conn.run = AsyncMock(return_value=result)

        assert await tunnel.is_alive() is True

    @pytest.mark.asyncio
    async def test_dead_when_no_connection(self):
        tunnel = SSHTunnel()
        tunnel._conn = None
        assert await tunnel.is_alive() is False

    @pytest.mark.asyncio
    async def test_dead_when_no_listener(self):
        tunnel = SSHTunnel()
        tunnel._conn = MagicMock()
        tunnel._listener = None
        assert await tunnel.is_alive() is False

    @pytest.mark.asyncio
    async def test_dead_when_no_transport(self):
        tunnel = SSHTunnel()
        tunnel._conn = MagicMock()
        tunnel._listener = MagicMock()
        tunnel._conn.get_extra_info.return_value = None
        assert await tunnel.is_alive() is False

    @pytest.mark.asyncio
    async def test_dead_when_listener_has_no_port(self):
        tunnel = SSHTunnel()
        tunnel._conn = MagicMock()
        tunnel._listener = MagicMock()
        tunnel._listener.get_port.return_value = 0

        tunnel._conn.get_extra_info.return_value = MagicMock()

        assert await tunnel.is_alive() is False

    @pytest.mark.asyncio
    async def test_dead_on_timeout(self):
        tunnel = SSHTunnel()
        tunnel._conn = MagicMock()
        tunnel._listener = MagicMock()
        tunnel._listener.get_port.return_value = 12345

        tunnel._conn.get_extra_info.return_value = MagicMock()
        tunnel._conn.run = AsyncMock(side_effect=TimeoutError)

        assert await tunnel.is_alive() is False

    @pytest.mark.asyncio
    async def test_dead_on_oserror(self):
        tunnel = SSHTunnel()
        tunnel._conn = MagicMock()
        tunnel._listener = MagicMock()
        tunnel._listener.get_port.return_value = 12345

        tunnel._conn.get_extra_info.return_value = MagicMock()
        tunnel._conn.run = AsyncMock(side_effect=OSError("broken pipe"))

        assert await tunnel.is_alive() is False


class TestSSHTunnelManagerReuse:
    """Verify that the manager doesn't needlessly kill working tunnels."""

    @pytest.mark.asyncio
    async def test_reuses_alive_tunnel(self):
        mgr = SSHTunnelManager()
        tunnel = SSHTunnel()
        tunnel._conn = MagicMock()
        tunnel._listener = MagicMock()
        tunnel._listener.get_port.return_value = 9999
        tunnel._local_host = "127.0.0.1"
        tunnel._local_port = 9999

        tunnel._conn.get_extra_info.return_value = MagicMock()
        result = _FakeRunResult(
            stdout="This account is currently not available.\n",
            exit_status=1,
        )
        tunnel._conn.run = AsyncMock(return_value=result)

        from app.connectors.base import ConnectionConfig

        cfg = ConnectionConfig(
            db_type="mysql",
            db_host="127.0.0.1",
            db_port=3306,
            ssh_host="jump.example.com",
            ssh_port=22,
            ssh_user="tunnel-user",
        )
        key = mgr._key(cfg)
        mgr._tunnels[key] = tunnel

        host, port = await mgr.get_or_create(cfg)
        assert host == "127.0.0.1"
        assert port == 9999
