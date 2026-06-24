"""Tests for SSHTunnel.is_alive with restricted-shell accounts."""

import time
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
    async def test_cache_fast_path_skips_probe_when_transport_open(self):
        """R1-7: within the liveness-cache TTL a healthy transport returns True
        without paying for a round-trip probe."""
        tunnel = SSHTunnel()
        tunnel._conn = MagicMock()
        tunnel._listener = MagicMock()
        tunnel._conn.get_extra_info.return_value = MagicMock()
        tunnel._conn.is_closed.return_value = False
        tunnel._conn.run = AsyncMock()
        tunnel._last_alive_check = time.monotonic()

        assert await tunnel.is_alive() is True
        tunnel._conn.run.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_invalidated_when_transport_gone(self):
        """R1-7: a dropped transport inside the cache window must not be trusted —
        the cache is invalidated and the full probe reports dead."""
        tunnel = SSHTunnel()
        tunnel._conn = MagicMock()
        tunnel._listener = MagicMock()
        # Transport gone: both the cache-window check and the full probe read it.
        tunnel._conn.get_extra_info.return_value = None
        tunnel._conn.is_closed.return_value = True
        tunnel._conn.run = AsyncMock()
        tunnel._last_alive_check = time.monotonic()

        assert await tunnel.is_alive() is False
        tunnel._conn.run.assert_not_called()

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


class TestSSHTunnelManagerRefCounting:
    """Re-audit: a tunnel shared by sibling connections must survive until the
    last referencing connection releases it."""

    def _alive_tunnel(self, port: int = 9999) -> SSHTunnel:
        tunnel = SSHTunnel()
        tunnel._conn = MagicMock()
        tunnel._listener = MagicMock()
        tunnel._listener.get_port.return_value = port
        tunnel._local_host = "127.0.0.1"
        tunnel._local_port = port
        tunnel._conn.get_extra_info.return_value = MagicMock()
        tunnel._conn.is_closed.return_value = False
        tunnel._last_alive_check = time.monotonic()
        tunnel.stop = AsyncMock()
        return tunnel

    @pytest.mark.asyncio
    async def test_close_keeps_tunnel_for_sibling_connection(self):
        from app.connectors.base import ConnectionConfig

        mgr = SSHTunnelManager()
        tunnel = self._alive_tunnel()

        # Two connections to the same DB through the same bastion: identical
        # transport identity (shared tunnel key) but distinct connection ids.
        cfg_a = ConnectionConfig(
            db_type="postgresql",
            db_host="db.example.com",
            db_port=5432,
            ssh_host="jump.example.com",
            ssh_port=22,
            ssh_user="tunnel-user",
            connection_id="conn-a",
        )
        cfg_b = ConnectionConfig(
            db_type="postgresql",
            db_host="db.example.com",
            db_port=5432,
            ssh_host="jump.example.com",
            ssh_port=22,
            ssh_user="tunnel-user",
            connection_id="conn-b",
        )
        key = mgr._key(cfg_a)
        assert key == mgr._key(cfg_b)
        mgr._tunnels[key] = tunnel

        # Both connections obtain (and reference) the shared tunnel.
        await mgr.get_or_create(cfg_a)
        await mgr.get_or_create(cfg_b)
        assert mgr._refs[key] == {"conn-a", "conn-b"}

        # Closing A drops only A's reference; the tunnel stays up for B.
        closed = await mgr.close_for_config(cfg_a)
        assert closed is False
        tunnel.stop.assert_not_called()
        assert key in mgr._tunnels
        assert mgr._refs[key] == {"conn-b"}

        # Closing B (the last reference) tears the tunnel down.
        closed = await mgr.close_for_config(cfg_b)
        assert closed is True
        tunnel.stop.assert_awaited_once()
        assert key not in mgr._tunnels
        assert key not in mgr._refs

    @pytest.mark.asyncio
    async def test_force_closes_regardless_of_refs(self):
        from app.connectors.base import ConnectionConfig

        mgr = SSHTunnelManager()
        tunnel = self._alive_tunnel()
        cfg = ConnectionConfig(
            db_type="postgresql",
            db_host="db.example.com",
            db_port=5432,
            ssh_host="jump.example.com",
            ssh_port=22,
            ssh_user="tunnel-user",
            connection_id="conn-a",
        )
        key = mgr._key(cfg)
        mgr._tunnels[key] = tunnel
        mgr._refs[key] = {"conn-a", "conn-b"}

        closed = await mgr.close_for_config(cfg, force=True)
        assert closed is True
        tunnel.stop.assert_awaited_once()
        assert key not in mgr._tunnels
        assert key not in mgr._refs


class TestSSHTunnelManagerKeyCredentialDiscriminator:
    """F-SSH-08 (R3 C5): the tunnel cache key must include a credential
    discriminator so two tenants sharing a bastion host+user but using
    DIFFERENT keys never collide onto one cached tunnel (cross-tenant leak)."""

    def _base_cfg(self, **overrides):
        from app.connectors.base import ConnectionConfig

        defaults = dict(
            db_type="postgresql",
            db_host="db.example.com",
            db_port=5432,
            ssh_host="jump.example.com",
            ssh_port=22,
            ssh_user="tunnel-user",
        )
        defaults.update(overrides)
        return ConnectionConfig(**defaults)

    def test_different_ssh_key_content_yields_different_key(self):
        """Same host/port/user/db, different ssh_key_content, no connection_id →
        the discriminator must keep the cache keys distinct."""
        mgr = SSHTunnelManager()
        cfg_a = self._base_cfg(ssh_key_content="-----TENANT-A-PRIVATE-KEY-----")
        cfg_b = self._base_cfg(ssh_key_content="-----TENANT-B-PRIVATE-KEY-----")
        assert mgr._key(cfg_a) != mgr._key(cfg_b)

    def test_different_ssh_key_passphrase_yields_different_key(self):
        mgr = SSHTunnelManager()
        cfg_a = self._base_cfg(ssh_key_content="-----SHARED-KEY-----", ssh_key_passphrase="pass-a")
        cfg_b = self._base_cfg(ssh_key_content="-----SHARED-KEY-----", ssh_key_passphrase="pass-b")
        assert mgr._key(cfg_a) != mgr._key(cfg_b)

    def test_different_db_password_yields_different_key(self):
        mgr = SSHTunnelManager()
        cfg_a = self._base_cfg(db_user="svc", db_password="secret-a")
        cfg_b = self._base_cfg(db_user="svc", db_password="secret-b")
        assert mgr._key(cfg_a) != mgr._key(cfg_b)

    def test_identical_credentials_yield_same_key(self):
        """Sibling connections with identical credential material still share a
        tunnel — the discriminator must not over-fragment the pool."""
        mgr = SSHTunnelManager()
        cfg_a = self._base_cfg(ssh_key_content="-----SHARED-KEY-----")
        cfg_b = self._base_cfg(ssh_key_content="-----SHARED-KEY-----")
        assert mgr._key(cfg_a) == mgr._key(cfg_b)

    def test_raw_secret_never_appears_in_key(self):
        """The cache key must never embed raw credential material."""
        mgr = SSHTunnelManager()
        secret_key = "-----BEGIN OPENSSH PRIVATE KEY-----SENSITIVE-----"
        secret_pass = "super-secret-passphrase"
        secret_db_pw = "db-password-12345"
        cfg = self._base_cfg(
            ssh_key_content=secret_key,
            ssh_key_passphrase=secret_pass,
            db_user="svc",
            db_password=secret_db_pw,
        )
        key = mgr._key(cfg)
        assert secret_key not in key
        assert secret_pass not in key
        assert secret_db_pw not in key

    def test_key_includes_endpoint_components(self):
        """The host/port/user/db endpoint identity is preserved in the key."""
        mgr = SSHTunnelManager()
        cfg = self._base_cfg(ssh_key_content="k")
        key = mgr._key(cfg)
        assert "jump.example.com" in key
        assert "tunnel-user" in key
        assert "db.example.com" in key
        assert "5432" in key


class TestSSHTunnelPortForwardFailure:
    @pytest.mark.asyncio
    async def test_conn_closed_on_forward_failure(self):
        tunnel = SSHTunnel()
        fake_conn = MagicMock()
        fake_conn.forward_local_port = AsyncMock(side_effect=OSError("port forward failed"))
        fake_conn.close = MagicMock()

        from app.connectors.base import ConnectionConfig

        cfg = ConnectionConfig(
            db_type="postgresql",
            db_host="db.example.com",
            db_port=5432,
            ssh_host="jump.example.com",
            ssh_port=22,
            ssh_user="user",
        )
        tunnel._conn = fake_conn
        with pytest.raises(OSError, match="port forward"):
            tunnel._listener = await fake_conn.forward_local_port(
                "127.0.0.1", 0, cfg.db_host, cfg.db_port
            )
