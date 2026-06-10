"""Registry of live connector pools for the health-check loop.

The periodic health loop in :mod:`app.main` used to reach into
``chat._agent._orchestrator._sql._connectors`` via a fragile ``getattr``
chain, which silently skipped any other pool (Mongo/ClickHouse/MCP
connectors held elsewhere). Pool owners now register themselves here and
the loop probes every registered pool uniformly.

Owners are held via weak references so registration never extends an
object's lifetime; dead entries are pruned on iteration.
"""

from __future__ import annotations

import weakref
from collections.abc import Mapping
from typing import Any

# name -> weakref to the pool owner + attribute holding {key: connector}
_pools: dict[str, tuple[weakref.ref, str]] = {}


def register_pool(name: str, owner: Any, attr: str = "_connectors") -> None:
    """Register *owner*'s ``attr`` dict as a probe-able connector pool."""
    _pools[f"{name}:{id(owner)}"] = (weakref.ref(owner), attr)


def all_connectors() -> dict[str, Any]:
    """Merged ``{connector_key: connector}`` across all live pools.

    Keys from later-registered pools win on collision, which is harmless:
    a key identifies one logical connection target either way.
    """
    merged: dict[str, Any] = {}
    dead: list[str] = []
    for name, (ref, attr) in _pools.items():
        owner = ref()
        if owner is None:
            dead.append(name)
            continue
        pool = getattr(owner, attr, None)
        if isinstance(pool, Mapping):
            merged.update(pool)
    for name in dead:
        _pools.pop(name, None)
    return merged


def reset() -> None:
    """Test hook: drop all registrations."""
    _pools.clear()
