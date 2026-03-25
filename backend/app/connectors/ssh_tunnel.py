import asyncio
import logging
import time

import asyncssh

from app.connectors.base import ConnectionConfig

logger = logging.getLogger(__name__)

SSH_CONNECT_TIMEOUT = 45
SSH_KEEPALIVE_INTERVAL = 15
SSH_MAX_RETRIES = 2
SSH_RETRY_DELAY = 3


_LIVENESS_CACHE_TTL = 30  # seconds


IDLE_TUNNEL_TTL = 1800  # 30 minutes


class SSHTunnel:
    def __init__(self):
        self._conn: asyncssh.SSHClientConnection | None = None
        self._listener: asyncssh.SSHListener | None = None
        self._local_host: str = "127.0.0.1"
        self._local_port: int | None = None
        self._last_alive_check: float = 0.0
        self._last_used: float = time.monotonic()

    @property
    def local_host(self) -> str:
        return self._local_host

    @property
    def local_port(self) -> int:
        if self._local_port is None:
            raise RuntimeError("Tunnel not started")
        return self._local_port

    async def start(self, config: ConnectionConfig) -> tuple[str, int]:
        if not config.ssh_host:
            raise ValueError("SSH host is required for tunnel")

        connect_kwargs: dict = {
            "host": (config.ssh_host or "").strip(),
            "port": config.ssh_port,
            "username": (config.ssh_user or "").strip(),
            "known_hosts": None,
            "login_timeout": SSH_CONNECT_TIMEOUT,
            "connect_timeout": SSH_CONNECT_TIMEOUT,
            "keepalive_interval": SSH_KEEPALIVE_INTERVAL,
        }
        if config.ssh_key_content:
            key = asyncssh.import_private_key(
                config.ssh_key_content.strip(),
                config.ssh_key_passphrase,
            )

            connect_kwargs["client_keys"] = [key]

        last_exc: Exception | None = None
        for attempt in range(1, SSH_MAX_RETRIES + 1):
            try:
                self._conn = await asyncio.wait_for(
                    asyncssh.connect(**connect_kwargs),
                    timeout=SSH_CONNECT_TIMEOUT + 10,
                )
                break
            except (asyncssh.Error, OSError, TimeoutError) as exc:
                last_exc = exc
                logger.warning(
                    "SSH connect attempt %d/%d failed: %s",
                    attempt,
                    SSH_MAX_RETRIES,
                    exc,
                )
                if attempt < SSH_MAX_RETRIES:
                    await asyncio.sleep(SSH_RETRY_DELAY)
        else:
            raise ConnectionError(
                f"SSH tunnel connection failed after {SSH_MAX_RETRIES} attempts: {last_exc}"
            ) from last_exc

        try:
            self._listener = await self._conn.forward_local_port(
                self._local_host,
                0,  # auto-assign port
                config.db_host,
                config.db_port,
            )
        except Exception:
            self._conn.close()
            self._conn = None
            raise
        self._local_port = self._listener.get_port()
        logger.info(
            "SSH tunnel %s:%d -> %s:%d via %s:%d",
            self._local_host,
            self._local_port,
            config.db_host,
            config.db_port,
            config.ssh_host,
            config.ssh_port,
        )
        return self._local_host, self._local_port

    async def stop(self):
        logger.debug("Stopping SSH tunnel (local_port=%s)", self._local_port)
        if self._listener:
            self._listener.close()
            self._listener = None
        if self._conn:
            self._conn.close()
            await asyncio.sleep(0.1)
            self._conn = None
        self._local_port = None
        self._last_alive_check = 0.0

    _ALIVE_MARKER = "__SSH_TUNNEL_ALIVE__"

    def touch(self) -> None:
        """Mark the tunnel as recently used (resets the idle timer)."""
        self._last_used = time.monotonic()

    @property
    def idle_seconds(self) -> float:
        return time.monotonic() - self._last_used

    async def is_alive(self) -> bool:
        if self._conn is None or self._listener is None:
            return False
        elapsed = time.monotonic() - self._last_alive_check if self._last_alive_check else None
        if elapsed is not None and elapsed < _LIVENESS_CACHE_TTL:
            return True
        try:
            transport = self._conn.get_extra_info("socket")
            if transport is None:
                logger.debug("SSH tunnel is_alive: transport is None")
                return False

            listener_port = self._listener.get_port()
            if not listener_port:
                logger.debug("SSH tunnel is_alive: listener has no port")
                return False

            result = await asyncio.wait_for(
                self._conn.run(f"echo {self._ALIVE_MARKER}", check=False),
                timeout=5,
            )
            if self._ALIVE_MARKER in (result.stdout or ""):
                self._last_alive_check = time.monotonic()
                return True

            # Shell command failed (e.g. nologin/restricted shell) but the SSH
            # connection itself may still be alive with working port forwarding.
            # Verify the transport is open and the listener is still active.
            if result.exit_status is not None and listener_port:
                logger.debug(
                    "SSH tunnel is_alive: shell unavailable (exit=%s, stdout=%r) "
                    "but transport open on port %d",
                    result.exit_status,
                    (result.stdout or "")[:120],
                    listener_port,
                )
                self._last_alive_check = time.monotonic()
                return True

            logger.warning(
                "SSH tunnel is_alive: marker not found and transport unhealthy "
                "(exit=%s, stdout=%r)",
                result.exit_status,
                (result.stdout or "")[:200],
            )
            return False
        except (TimeoutError, asyncssh.Error, OSError) as exc:
            logger.warning("SSH tunnel is_alive check failed: %s", exc)
            return False
        except Exception as exc:
            logger.warning("SSH tunnel is_alive unexpected error: %s", exc)
            return False


class SSHTunnelManager:
    """Pool of SSH tunnels keyed by (ssh_host, ssh_port, ssh_user)."""

    def __init__(self):
        self._tunnels: dict[str, SSHTunnel] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _key(self, config: ConnectionConfig) -> str:
        return (
            f"{config.ssh_host}:{config.ssh_port}:{config.ssh_user}"
            f":{config.db_host}:{config.db_port}"
        )

    def _get_lock(self, key: str) -> asyncio.Lock:
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    _RECONNECT_MAX_ATTEMPTS = 3
    _RECONNECT_BACKOFF_SECONDS = 2

    async def get_or_create(self, config: ConnectionConfig) -> tuple[str, int]:
        if not config.ssh_host:
            return config.db_host, config.db_port

        key = self._key(config)

        tunnel = self._tunnels.get(key)
        if tunnel and await tunnel.is_alive():
            tunnel.touch()
            return tunnel.local_host, tunnel.local_port

        async with self._get_lock(key):
            tunnel = self._tunnels.get(key)
            if tunnel and await tunnel.is_alive():
                tunnel.touch()
                return tunnel.local_host, tunnel.local_port

            if tunnel:
                logger.info("SSH tunnel for %s is dead, attempting reconnect", key)
                await tunnel.stop()

            last_exc: Exception | None = None
            for attempt in range(1, self._RECONNECT_MAX_ATTEMPTS + 1):
                try:
                    tunnel = SSHTunnel()
                    host, port = await tunnel.start(config)
                    self._tunnels[key] = tunnel
                    if attempt > 1:
                        logger.info("SSH tunnel reconnected on attempt %d for %s", attempt, key)
                    return host, port
                except Exception as exc:
                    last_exc = exc
                    logger.warning(
                        "SSH tunnel reconnect attempt %d/%d failed for %s: %s",
                        attempt,
                        self._RECONNECT_MAX_ATTEMPTS,
                        key,
                        exc,
                    )
                    if attempt < self._RECONNECT_MAX_ATTEMPTS:
                        await asyncio.sleep(self._RECONNECT_BACKOFF_SECONDS * attempt)

            raise ConnectionError(
                f"SSH tunnel reconnection failed after "
                f"{self._RECONNECT_MAX_ATTEMPTS} attempts: {last_exc}"
            ) from last_exc

    async def close_for_config(self, config: ConnectionConfig) -> bool:
        """Close the tunnel for a specific connection config, if it exists."""
        if not config.ssh_host:
            return False
        key = self._key(config)
        tunnel = self._tunnels.pop(key, None)
        if tunnel:
            await tunnel.stop()
            logger.info("Closed SSH tunnel for %s", key)
            return True
        return False

    async def cleanup_idle(self, max_idle: float = IDLE_TUNNEL_TTL) -> int:
        """Close tunnels that have been idle longer than *max_idle* seconds."""
        to_remove: list[str] = []
        for key, tunnel in self._tunnels.items():
            if tunnel.idle_seconds > max_idle:
                to_remove.append(key)
        for key in to_remove:
            tunnel = self._tunnels.pop(key, None)
            if tunnel:
                await tunnel.stop()
                logger.info("Closed idle SSH tunnel: %s (idle %.0fs)", key, tunnel.idle_seconds)
        return len(to_remove)

    async def close_all(self):
        for tunnel in self._tunnels.values():
            await tunnel.stop()
        self._tunnels.clear()
