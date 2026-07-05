"""Process-wide registry of live SQLAgent schema caches.

When a DB index completes or a schema-change alert fires, the stale
``SchemaInfo`` entries for that connection must be evicted from every live
``SQLAgent._schema_cache`` so the next query re-introspects the live schema
instead of serving stale column names for up to 5 minutes.

``SQLAgent`` is per-orchestrator (not a singleton), so a process-wide
weakref registry is required.  Owners register themselves at construction
time; dead owners are pruned on iteration so they never prevent GC.

Design mirrors :mod:`app.core.connector_pools` — a ``dict`` of
``(weakref, cache_attr_name)`` tuples keyed by ``f"{name}:{id(owner)}"``.

Invalidation algorithm
----------------------
The schema cache uses ``connector_key(cfg)`` as its dict key.  That key
embeds ``cid=<connection_id>`` when ``cfg.connection_id`` is set (see
``connectors/base.py::connector_key``).  We therefore scan every live
cache's internal ``_store`` and ``pop`` any key whose string representation
contains the substring ``f"cid={connection_id}"``.

Thread safety
-------------
``TTLCache`` is internally thread-safe via an ``RLock``.  The registry dict
itself is only mutated from within a single event-loop thread (FastAPI/ARQ)
in normal operation, so no extra lock is required.  The iterate-then-prune
pattern (collect dead keys first, then pop) is safe regardless.

Best-effort contract
--------------------
``invalidate_connection`` is best-effort: any exception inside the iteration
loop is caught and logged.  A failed invalidation never crashes a request or
a worker job — the worst outcome is a single extra 300-second stale window,
which is identical to the pre-fix behaviour.
"""

from __future__ import annotations

import logging
import weakref
from typing import Any

logger = logging.getLogger(__name__)

# Registry: unique_key → (weakref to owner, cache attribute name)
_registry: dict[str, tuple[weakref.ref, str]] = {}


def register_schema_cache(owner: Any, cache_attr: str = "_schema_cache") -> None:
    """Register *owner*'s ``cache_attr`` TTLCache for process-wide invalidation.

    Safe to call multiple times for the same object — the second call
    overwrites the previous entry under the same key, which is harmless.
    """
    key = f"{type(owner).__name__}:{id(owner)}"
    _registry[key] = (weakref.ref(owner), cache_attr)


def invalidate_connection(connection_id: str) -> int:
    """Evict all cached ``SchemaInfo`` entries for *connection_id*.

    Iterates every registered live SQLAgent cache and removes keys that
    contain ``f"cid={connection_id}"``.  Dead (GC'd) owners are pruned
    from the registry as they are encountered.

    Returns the total number of cache entries cleared across all agents.
    """
    target_fragment = f"cid={connection_id}"
    cleared = 0
    dead: list[str] = []

    for reg_key, (ref, cache_attr) in list(_registry.items()):
        owner = ref()
        if owner is None:
            dead.append(reg_key)
            continue
        try:
            cache = getattr(owner, cache_attr, None)
            if cache is None:
                continue
            # TTLCache stores entries in cache._store (OrderedDict).
            # We need to find all keys that match the connection fragment
            # and pop them.  We snapshot the keys first to avoid mutation
            # during iteration.
            store = getattr(cache, "_store", None)
            if store is None:
                continue
            matching = [
                k for k in list(store.keys()) if isinstance(k, str) and target_fragment in k
            ]
            for k in matching:
                cache.pop(k)
                cleared += 1
        except Exception:
            logger.debug(
                "schema_cache_registry: error clearing cache for owner=%s connection=%s",
                type(owner).__name__,
                connection_id[:8] if len(connection_id) >= 8 else connection_id,
                exc_info=True,
            )

    for reg_key in dead:
        _registry.pop(reg_key, None)

    if cleared:
        logger.debug(
            "schema_cache_registry: cleared %d cache entries for connection=%s",
            cleared,
            connection_id[:8] if len(connection_id) >= 8 else connection_id,
        )

    return cleared


def reset() -> None:
    """Test hook: drop all registrations."""
    _registry.clear()
