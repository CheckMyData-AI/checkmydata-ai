"""How many repository indexes one process may run at once (OPS-08, PRJ-07 S-04).

`max_jobs = 8` is the worker's overall concurrency, and it is fine for the short jobs it
was chosen for. A repo index is not one: measured at 967 MiB peak before
`EMBEDDING_UPSERT_BATCH_SIZE` was cut to 8, and still over quota at batch 32 on a 1 GiB
Standard-2X — **one of them already exhausts the dyno**, so eight at once is seven more
than fit.

A semaphore rather than `max_jobs = 1`, because that would serialise every other job
behind an index that runs for hours — the analytics collection, the batch runner and the
db-index all fit alongside it and none of them is memory-shaped.

It is acquired inside `app.api.routes.repos.run_repo_index_task`, the one function every
path reaches — the ARQ job, the nightly sync, the run-retry route, the in-process
fallback. It used to live in the ARQ wrapper alone, and the nightly sync calls the task
directly, so N projects due at one hour ran N indexes at once (audit 2026-09-13 S-04).
Per process on purpose: the memory it protects is per dyno.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

MAX_CONCURRENT_REPO_INDEXES = 1

_slots = asyncio.Semaphore(MAX_CONCURRENT_REPO_INDEXES)


@asynccontextmanager
async def repo_index_slot(project_id: str) -> AsyncIterator[None]:
    """Hold one of this process's repo-index slots for the duration of the block.

    A caller waiting here is still a running job, so its own timeout is ticking — the
    right pressure: a queue of indexes that cannot all finish should say so by timing
    out, not by taking the dyno down with an R15 that loses every job on it.
    """
    if _slots.locked():
        logger.info(
            "repo index for project %s is waiting: %d already running (OPS-08)",
            project_id[:8],
            MAX_CONCURRENT_REPO_INDEXES,
        )
    async with _slots:
        yield
