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


# ---------------------------------------------------------------------------
# F-SSH-09: `_locks` grew one asyncio.Lock per key and nothing removed them
# ---------------------------------------------------------------------------


class TestPerKeyLockLifecycle:
    """`close_for_config`, `cleanup_idle` and `close_all` all pop `_tunnels` and
    `_refs` and none of them touched `_locks`.

    One `asyncio.Lock` per distinct cache key, forever, in a process that lives for
    days. The key carries a credential discriminator, so rotating a password mints a
    new key and a new lock; deleting a connection leaves its lock behind too.

    The trap is the obvious fix: popping a lock that is **held** is worse than the
    leak, because the next caller builds a fresh one and two coroutines enter the
    critical section at once. `locked()` is checked and the pop happens in the same
    synchronous step — on one event loop nothing can interleave between them, and an
    `asyncio.Lock` only queues waiters while it is held, so `not locked()` means
    nobody is queued.
    """

    @staticmethod
    def _cfg(cid: str, host: str = "db.example.com"):
        from app.connectors.base import ConnectionConfig

        return ConnectionConfig(
            db_type="postgresql",
            db_host=host,
            db_port=5432,
            ssh_host="jump.example.com",
            ssh_port=22,
            ssh_user="tunnel-user",
            connection_id=cid,
        )

    def _alive(self):
        t = SSHTunnel()
        t._conn = MagicMock()
        t._listener = MagicMock()
        t._listener.get_port.return_value = 9999
        t._local_host = "127.0.0.1"
        t._local_port = 9999
        t._conn.get_extra_info.return_value = MagicMock()
        t.is_alive = AsyncMock(return_value=True)  # type: ignore[method-assign]
        return t

    @pytest.mark.asyncio
    async def test_closing_a_tunnel_drops_its_lock(self):
        mgr = SSHTunnelManager()
        cfg = self._cfg("conn-a")
        key = mgr._key(cfg)
        mgr._tunnels[key] = self._alive()
        # `get_or_create`'s fast path returns a cached tunnel without taking the lock,
        # and these tests pre-seed one to avoid a real SSH connect — so take it the way
        # the creation path does.
        mgr._get_lock(key)
        await mgr.get_or_create(cfg)
        assert key in mgr._locks

        mgr._tunnels[key].stop = AsyncMock()
        await mgr.close_for_config(cfg, force=True)
        assert key not in mgr._locks, "the lock outlived the tunnel it guarded"

    @pytest.mark.asyncio
    async def test_a_shared_tunnel_keeps_its_lock_until_the_last_reference_goes(self):
        mgr = SSHTunnelManager()
        a, b = self._cfg("conn-a"), self._cfg("conn-b")
        key = mgr._key(a)
        mgr._tunnels[key] = self._alive()
        mgr._get_lock(key)
        await mgr.get_or_create(a)
        await mgr.get_or_create(b)

        await mgr.close_for_config(a)  # one ref released; tunnel stays
        assert key in mgr._locks, "the tunnel is still live, so its lock must stay"

        mgr._tunnels[key].stop = AsyncMock()
        await mgr.close_for_config(b)
        assert key not in mgr._locks

    @pytest.mark.asyncio
    async def test_idle_cleanup_drops_the_lock_too(self):
        mgr = SSHTunnelManager()
        cfg = self._cfg("conn-a")
        key = mgr._key(cfg)
        t = self._alive()
        mgr._tunnels[key] = t
        mgr._get_lock(key)
        await mgr.get_or_create(cfg)
        t.stop = AsyncMock()
        t._last_used = time.monotonic() - 10_000

        await mgr.cleanup_idle(max_idle=1)
        assert key not in mgr._tunnels
        assert key not in mgr._locks

    @pytest.mark.asyncio
    async def test_close_all_drops_every_lock(self):
        mgr = SSHTunnelManager()
        for i in range(3):
            cfg = self._cfg(f"conn-{i}", host=f"db{i}.example.com")
            key = mgr._key(cfg)
            t = self._alive()
            t.stop = AsyncMock()
            mgr._tunnels[key] = t
            mgr._get_lock(key)
            await mgr.get_or_create(cfg)
        assert len(mgr._locks) == 3

        await mgr.close_all()
        assert mgr._locks == {}

    @pytest.mark.asyncio
    async def test_a_held_lock_is_never_dropped(self):
        """Popping a held lock turns a memory leak into two coroutines in one
        critical section, which is the worse of the two problems."""
        mgr = SSHTunnelManager()
        cfg = self._cfg("conn-a")
        key = mgr._key(cfg)
        lock = mgr._get_lock(key)
        await lock.acquire()
        try:
            mgr._release_lock(key)
            assert key in mgr._locks, "a held lock must survive"
        finally:
            lock.release()
        mgr._release_lock(key)
        assert key not in mgr._locks, "and be reclaimed once it is free"

    @pytest.mark.asyncio
    async def test_a_lock_orphaned_while_held_is_reclaimed_later(self):
        """If the lock was busy at close time it is skipped, so something has to come
        back for it — otherwise the leak survives exactly the cases that caused it."""
        mgr = SSHTunnelManager()
        cfg = self._cfg("conn-a")
        key = mgr._key(cfg)
        lock = mgr._get_lock(key)
        await lock.acquire()
        mgr._release_lock(key)  # skipped: held
        lock.release()

        assert key in mgr._locks
        await mgr.cleanup_idle(max_idle=1)  # no tunnels at all, but locks are swept
        assert key not in mgr._locks

    @pytest.mark.asyncio
    async def test_the_sweep_leaves_a_live_tunnel_s_lock_alone(self):
        """ "Orphaned" means the key is gone, not merely that the lock is free.

        Dropping a free lock whose tunnel is still live is not a correctness bug — the
        next caller just builds another — but it makes `_sweep_orphaned_locks` do
        something other than its name, and churns a lock for every live tunnel on every
        idle pass. A plant removing the `key not in self._tunnels` condition was
        invisible until this test existed.
        """
        mgr = SSHTunnelManager()
        cfg = self._cfg("conn-a")
        key = mgr._key(cfg)
        t = self._alive()
        t.stop = AsyncMock()
        mgr._tunnels[key] = t
        mgr._get_lock(key)
        t._last_used = time.monotonic()  # fresh: not idle, so it is not closed

        assert mgr._sweep_orphaned_locks() == 0
        assert key in mgr._locks, "a live tunnel's lock is not orphaned"
