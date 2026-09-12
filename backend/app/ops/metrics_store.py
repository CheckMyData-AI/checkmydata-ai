"""A shared home for counters the worker emits (OPS-03).

`MetricsCollector` is a plain Python singleton holding `defaultdict`s behind a
`threading.Lock`. There is no push, no shared store, and no scrape endpoint in the
worker — the `Procfile`'s `worker` line runs `arq`, not uvicorn. So everything the
ARQ jobs increment (`indexing_runs_total`, `indexing_run_duration_seconds`,
`daily_sync_budget_near_ceiling_total`, `db_index_sample_budget_exhausted_total`)
accumulated in the worker's heap and died with it, while `/api/metrics` rendered the
`web` process's collector, which never saw any of them.

The failure mode is worse than a wrong number. `budget_warning()` fires because a
nightly sync took 6 300 s of its 7 200 s ceiling; the operator opens
`/api/metrics/prometheus` and the counter is **absent entirely** — not zero, absent,
because that name was never emitted in that process. A metric documented as "the
number that says whether `db_index_fetch_samples_budget_seconds` is set too low" has
the same fate.

**The design, and why each part is the way it is.**

- *Nothing on the hot path.* The collector is untouched; a process publishes by
  flushing, and `web` flushes on the read path so the reader's own increments are
  never stale. An increment costs exactly what it cost before.
- *Deltas, not totals.* Two `web` dynos share a namespace, so a flush that wrote the
  cumulative total would have the second clobber the first. `HINCRBYFLOAT` of the
  delta sums correctly across dynos, and it is also what makes a repeated flush from
  one process idempotent rather than doubling.
- *Namespaced by process type, not by boot.* Per-boot keys would grow without bound;
  per-type keys are two, and a restart resetting that namespace's contribution is
  exactly what a Prometheus counter reset already looks like. A TTL refreshed on
  every flush retires a process type nobody runs any more.
- *Optional.* Dev has no Redis, and `/api/metrics` must keep working there. With no
  store the endpoint renders the local collector, which is the previous behaviour.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

#: Key prefix for the per-process counter hashes.
KEY_PREFIX = "metrics:v1:"

#: How long a process type's contribution survives without a flush. Long enough that
#: a worker idle overnight keeps its counters, short enough that a retired process
#: type stops being summed into the page.
TTL_SECONDS = 7 * 24 * 3600

Labels = tuple[tuple[str, str], ...]


def _field(name: str, labels: Labels) -> str:
    """One hash field per (metric, label-set). JSON so the labels survive intact.

    A counter stripped of its labels answers a different question — `indexing_runs_total`
    without `status` cannot say whether anything failed.
    """
    return json.dumps([name, [list(pair) for pair in labels]], separators=(",", ":"))


def _parse_field(raw: str) -> tuple[str, Labels] | None:
    try:
        name, labels = json.loads(raw)
        return str(name), tuple((str(k), str(v)) for k, v in labels)
    except Exception:
        # WARNING rather than debug: nothing in this module writes a field this
        # function cannot read, so reaching here means a metric is being dropped on
        # the floor and the page an operator is reading is missing a series.
        logger.warning("metrics store: unreadable field %r — dropping it", raw[:80])
        return None


class MetricsStore:
    """Publishes one process's counter deltas and reads back the sum of all of them."""

    def __init__(self, redis: Any, *, process: str) -> None:
        self._redis = redis
        self._key = f"{KEY_PREFIX}{process}"
        #: What this store has already published, so a flush sends the delta.
        self._published: dict[str, float] = {}

    async def flush(self, collector: Any) -> int:
        """Publish everything this process has counted since the last flush.

        Returns the number of fields written. Never raises: a metrics publish that
        can fail a request, or fail the job it is measuring, is worse than a gap in
        a graph.
        """
        try:
            snapshot = collector.snapshot_labelled()
        except Exception:
            # Same reasoning: the collector is in-process and cannot fail from an
            # outage, so this is a defect, and its consequence is that this process
            # publishes nothing at all.
            logger.warning(
                "metrics store: could not snapshot the collector — this process is "
                "publishing no counters",
                exc_info=True,
            )
            return 0

        written = 0
        for (name, labels), value in snapshot.items():
            field = _field(name, labels)
            delta = float(value) - self._published.get(field, 0.0)
            if delta == 0.0:
                continue
            try:
                await self._redis.hincrbyfloat(self._key, field, delta)
            except Exception:
                logger.debug("metrics store: flush failed for %s", name, exc_info=True)
                # Leave `_published` alone so the delta is retried on the next flush
                # rather than being silently lost.
                continue
            self._published[field] = float(value)
            written += 1

        if written:
            try:
                await self._redis.expire(self._key, TTL_SECONDS)
            except Exception:
                logger.debug("metrics store: could not refresh the TTL", exc_info=True)
        return written

    async def read_all(self) -> list[tuple[str, Labels, float]]:
        """Every process's contribution, summed. Never raises."""
        totals: dict[tuple[str, Labels], float] = {}
        try:
            async for key in self._redis.scan_iter(match=f"{KEY_PREFIX}*"):
                name = key.decode() if isinstance(key, bytes) else key
                bucket = await self._redis.hgetall(name)
                for raw_field, raw_value in bucket.items():
                    field = raw_field.decode() if isinstance(raw_field, bytes) else raw_field
                    parsed = _parse_field(field)
                    if parsed is None:
                        continue
                    try:
                        value = float(raw_value)
                    except (TypeError, ValueError):
                        continue
                    totals[parsed] = totals.get(parsed, 0.0) + value
        except Exception:
            logger.warning("metrics store: could not read the shared counters", exc_info=True)
            return []
        return [(name, labels, value) for (name, labels), value in totals.items()]


async def render_with_store(collector: Any, store: MetricsStore | None) -> str:
    """The Prometheus body for `/api/metrics/prometheus`.

    With a store: flush this process's own counters first — so the reader is never
    shown a page missing what this very process just counted — then render the sum of
    every process. Without one: the local collector, which is what dev has and what
    this endpoint always did.
    """
    if store is None:
        return collector.render_prometheus()
    await store.flush(collector)
    published = await store.read_all()
    if not published:
        # The store is configured but empty or unreadable. Rendering nothing would
        # turn a Redis problem into "the product has no metrics"; the local view is
        # incomplete but true.
        return collector.render_prometheus()
    return collector.render_prometheus_from(published)


_store: MetricsStore | None = None


def get_metrics_store(process: str | None = None) -> MetricsStore | None:
    """This process's store, or ``None`` when Redis is not available (OPS-03).

    The process name comes from `app.core.release.owner()` — the same function the
    orphan sweep uses to decide whose runs it is looking at — so `web` and `worker`
    name themselves the one way, and a local run with no `DYNO` set falls back to a
    third namespace rather than pretending to be either.
    """
    global _store  # noqa: PLW0603
    from app.core.redis_client import get_redis

    redis = get_redis()
    if redis is None:
        _store = None
        return None
    if _store is None or _store._redis is not redis:
        from app.core.release import owner

        _store = MetricsStore(redis, process=process or owner() or "local")
    return _store
