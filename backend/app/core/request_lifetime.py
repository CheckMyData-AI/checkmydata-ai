"""How long a live request can exist, derived from the ceilings that bound it.

Two sweeps guess that a request is dead by its age — the trace buffer's eviction and the
orchestrator's per-workflow cache sweep — and both used a typed 300 s. That is below the
360 s REST/SSE ceiling and the 900 s WebSocket relay, so each evicted LIVE requests: the
trace was written ``failed`` (PRJ-04, 26 rows) and the cache sweep dropped a running
request's SQL results, so ``process_data`` answered "no query results available" (O-07).

Derived, not typed: a constant beside three configurable ceilings is right the day it
is written and wrong the day one of them moves.
"""

from __future__ import annotations

#: Past the longest ceiling, so a request that is merely slow is never mistaken for one
#: that is gone.
MARGIN_SECONDS = 60.0


def longest_request_seconds() -> float:
    from app.config import settings

    return (
        max(
            float(settings.stream_timeout_seconds),
            float(settings.ws_event_relay_timeout_seconds),
            float(settings.agent_wall_clock_timeout_seconds) * 1.2,
        )
        + MARGIN_SECONDS
    )
