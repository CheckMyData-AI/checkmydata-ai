"""C-03: a tunnel carrying queries is not idle, whatever the clock says.

`touch()` ran only in `SSHTunnelManager.get_or_create`, and a caller reaches that ONCE —
a connection pool then keeps its sockets and queries through them for as long as it
likes. So a `db_index` (budget 1800 s) or the chat's cached connector looked idle to the
30-minute sweep, which closed the SSH connection **under a live pool**; `execute_query`
has no reconnect path, so every remaining table came back `sample_failed`.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

import pytest

from app.connectors.base import ConnectionConfig
from app.connectors.ssh_tunnel import SSHTunnelManager

CONNECTORS = Path(__file__).resolve().parents[3] / "app" / "connectors"


def _config(**over):
    base = dict(
        db_type="postgres",
        db_host="10.0.0.5",
        db_port=5432,
        db_name="db",
        db_user="u",
        db_password="p",
        ssh_host="bastion.example.com",
        ssh_port=22,
        ssh_user="deploy",
    )
    base.update(over)
    return ConnectionConfig(**base)


class _Tunnel:
    def __init__(self) -> None:
        self.last_used = time.monotonic() - 3600

    def touch(self) -> None:
        self.last_used = time.monotonic()

    @property
    def idle_seconds(self) -> float:
        return time.monotonic() - self.last_used

    async def stop(self) -> None:  # pragma: no cover - only on the closing path
        self.stopped = True


@pytest.fixture()
def manager_with_tunnel():
    mgr = SSHTunnelManager()
    config = _config()
    tunnel = _Tunnel()
    mgr._tunnels[mgr._key(config)] = tunnel  # type: ignore[assignment]
    return mgr, config, tunnel


async def test_a_query_keeps_the_tunnel_out_of_the_idle_sweep(manager_with_tunnel):
    mgr, config, tunnel = manager_with_tunnel
    assert tunnel.idle_seconds > 1800, "the tunnel was opened an hour ago"

    assert mgr.note_activity(config) is True

    closed = await mgr.cleanup_idle(max_idle=1800)
    assert closed == 0, "a tunnel that just carried a query is not idle"
    assert mgr._tunnels, "and it is still there for the pool that is using it"


async def test_a_tunnel_nobody_queries_still_closes(manager_with_tunnel):
    mgr, _config_unused, _tunnel = manager_with_tunnel

    closed = await mgr.cleanup_idle(max_idle=1800)

    assert closed == 1, "the sweep still exists: this is not a way to keep tunnels forever"


def test_a_direct_connection_has_nothing_to_touch():
    mgr = SSHTunnelManager()
    assert mgr.note_activity(_config(ssh_host="")) is False


def test_every_tunnelled_connector_marks_its_work():
    """Structural: a connector that opens a tunnel must also say when it uses one.

    On the parse tree, because the point is WHERE the call sits — inside the methods
    that run work — and a grep would accept it anywhere in the file.
    """
    missing: list[str] = []
    for path in sorted(CONNECTORS.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        if "_tunnel_mgr.get_or_create" not in source:
            continue
        tree = ast.parse(source)
        for name in ("execute_query", "introspect_schema"):
            fn = next(
                (
                    n
                    for n in ast.walk(tree)
                    if isinstance(n, ast.AsyncFunctionDef) and n.name == name
                ),
                None,
            )
            if fn is None:
                continue
            if "note_activity" not in ast.dump(fn):
                missing.append(f"{path.name}:{name}")
    assert missing == [], f"these run work through a tunnel without marking it: {missing}"
