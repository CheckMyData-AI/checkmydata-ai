import asyncio
import logging

import asyncssh

from app.connectors.base import ConnectionConfig

logger = logging.getLogger(__name__)


class SSHTunnel:
    def __init__(self):
        self._conn: asyncssh.SSHClientConnection | None = None
        self._listener: asyncssh.SSHListener | None = None
        self._local_host: str = "127.0.0.1"
        self._local_port: int | None = None

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
            "host": config.ssh_host,
            "port": config.ssh_port,
            "username": config.ssh_user,
            "known_hosts": None,
        }
        if config.ssh_key_content:
            key = asyncssh.import_private_key(
                config.ssh_key_content, config.ssh_key_passphrase
            )
            connect_kwargs["client_keys"] = [key]

        self._conn = await asyncssh.connect(**connect_kwargs)

        self._listener = await self._conn.forward_local_port(
            self._local_host,
            0,  # auto-assign port
            config.db_host,
            config.db_port,
        )
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
        if self._listener:
            self._listener.close()
            self._listener = None
        if self._conn:
            self._conn.close()
            await asyncio.sleep(0.1)
            self._conn = None
        self._local_port = None

    async def is_alive(self) -> bool:
        if self._conn is None:
            return False
        try:
            transport = self._conn.get_extra_info("socket")
            return transport is not None
        except Exception:
            return False


class SSHTunnelManager:
    """Pool of SSH tunnels keyed by (ssh_host, ssh_port, ssh_user)."""

    def __init__(self):
        self._tunnels: dict[str, SSHTunnel] = {}

    def _key(self, config: ConnectionConfig) -> str:
        return f"{config.ssh_host}:{config.ssh_port}:{config.ssh_user}:{config.db_host}:{config.db_port}"

    async def get_or_create(self, config: ConnectionConfig) -> tuple[str, int]:
        if not config.ssh_host:
            return config.db_host, config.db_port

        key = self._key(config)
        tunnel = self._tunnels.get(key)

        if tunnel and await tunnel.is_alive():
            return tunnel.local_host, tunnel.local_port

        if tunnel:
            await tunnel.stop()

        tunnel = SSHTunnel()
        host, port = await tunnel.start(config)
        self._tunnels[key] = tunnel
        return host, port

    async def close_all(self):
        for tunnel in self._tunnels.values():
            await tunnel.stop()
        self._tunnels.clear()
