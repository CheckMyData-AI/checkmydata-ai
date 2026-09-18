"""C-10: a failure on the far side of a tunnel says which side, and gets one rebuild.

`is_alive` runs a shell command over the SSH transport. The **forward** is a separate
channel the bastion can refuse on its own — `AllowTcpForwarding no`, a firewall between
bastion and database, a database that stopped listening — so a retry re-entered the same
"alive" tunnel and failed identically, while the error named `127.0.0.1:<local port>`:
the one address in the story that is never the problem (the 2026-09-05 incident).
"""

from __future__ import annotations

import pytest

from app.connectors.base import ConnectionConfig
from app.connectors.ssh_tunnel import SSHTunnelManager, TunnelledConnectError


def _config(**over):
    base = dict(
        db_type="postgres",
        db_host="10.0.0.5",
        db_port=5432,
        db_name="db",
        db_user="u",
        ssh_host="bastion.example.com",
        ssh_port=22,
        ssh_user="deploy",
    )
    base.update(over)
    return ConnectionConfig(**base)


class _Manager(SSHTunnelManager):
    """A manager whose tunnel is a counter: this is about the retry, not about SSH."""

    def __init__(self) -> None:
        super().__init__()
        self.opened = 0
        self.closed = 0

    async def get_or_create(self, config):
        self.opened += 1
        return "127.0.0.1", 54321

    async def close_for_config(self, config, *, force: bool = False) -> bool:
        self.closed += 1
        return True


@pytest.mark.asyncio
async def test_a_refused_forward_gets_one_rebuild_and_then_says_the_route():
    mgr = _Manager()
    attempts = 0

    async def opener(host: str, port: int):
        nonlocal attempts
        attempts += 1
        raise ConnectionRefusedError(f"[Errno 61] Connection refused to {host}:{port}")

    with pytest.raises(TunnelledConnectError) as excinfo:
        await mgr.open_through(_config(), opener)

    assert attempts == 2, "the forward is rebuilt once before the failure is final"
    assert mgr.closed == 1, "the rebuild is a forced close, not a reuse of the live tunnel"
    message = str(excinfo.value)
    assert "bastion.example.com" in message and "10.0.0.5:5432" in message, (
        "an error about 127.0.0.1 sends the reader to the wrong machine"
    )


@pytest.mark.asyncio
async def test_a_forward_that_heals_on_the_second_try_is_used():
    mgr = _Manager()
    attempts = 0

    async def opener(host: str, port: int):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionRefusedError("refused")
        return "pool"

    assert await mgr.open_through(_config(), opener) == "pool"
    assert (attempts, mgr.closed) == (2, 1)


@pytest.mark.asyncio
async def test_a_direct_connection_is_opened_once_and_its_error_is_its_own():
    mgr = _Manager()
    attempts = 0

    async def opener(host: str, port: int):
        nonlocal attempts
        attempts += 1
        raise ConnectionRefusedError("refused")

    with pytest.raises(ConnectionRefusedError) as excinfo:
        await mgr.open_through(_config(ssh_host=""), opener)

    assert attempts == 1, "there is no tunnel to rebuild"
    assert not isinstance(excinfo.value, TunnelledConnectError)


def test_both_tunnelled_engines_open_through_the_manager():
    from pathlib import Path

    connectors = Path(__file__).resolve().parents[3] / "app" / "connectors"
    for engine in ("postgres.py", "mysql.py"):
        source = (connectors / engine).read_text(encoding="utf-8")
        assert "_tunnel_mgr.open_through(config" in source, f"{engine} opens its pool directly"
