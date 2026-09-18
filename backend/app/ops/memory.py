"""Give the allocator's freed arenas back to the operating system (T00-mem).

Freeing a Python object does not lower RSS. glibc keeps the arena, and the platform
counts RSS — so a process that builds a 59 MB corpus, writes it to disk and drops it
still reads as holding it, and Heroku's quota is not interested in the distinction.

Measured on the production corpus (32 571 documents, 2026-09-18, a Standard-1X dyno):
after the boot BM25 rebuild RSS was **376 MB**, and one ``malloc_trim(0)`` took it to
**353 MB** — 23 MB that the process had already stopped using.

Called at the seams where a large transient has just died, never on a request path:
trimming walks the arenas, and doing that per request would trade memory for latency
on the path that has neither to spare.
"""

from __future__ import annotations

import ctypes
import logging

logger = logging.getLogger(__name__)


def release_freed_memory(reason: str) -> bool:
    """Ask glibc to return freed arenas. Returns whether it did; never raises.

    False on any platform without glibc's ``malloc_trim`` — macOS and musl among them,
    which is where the tests run. That is not a failure: those allocators make their
    own decisions, and a boot that cannot trim is exactly as correct as one that can.
    """
    try:
        libc = ctypes.CDLL("libc.so.6")
        trimmed = bool(libc.malloc_trim(0))
    except Exception:
        logger.debug("malloc_trim unavailable (%s)", reason, exc_info=True)
        return False
    logger.info("released freed memory after %s (trimmed=%s)", reason, trimmed)
    return trimmed
