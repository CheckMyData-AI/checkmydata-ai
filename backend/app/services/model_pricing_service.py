"""The model price table, fetched by whichever process needs it (Ш0b · REQ-7).

Measured on production 2026-09-04: ``estimated_cost_usd`` was NULL on **all
7 664** ``token_usage`` rows and **all 222** ``request_traces`` — every month back
to April, in both processes — while 60.2 million tokens were metered exactly. The
operator had no cost figure for any request ever made.

One import caused it. :func:`app.services.cost_estimation_service.estimate_cost`
read ``app.api.routes.models._cache``: an in-process dict populated **only** as a
side effect of somebody requesting ``GET /api/models``. The worker serves no
HTTP, so its copy was always empty; the web dyno's was empty until a user opened
the model picker.

The first design proposed for this was a Redis store, on the reasoning that the
worker could not reach the data. **That reasoning was wrong.** The fetch is an
outbound call to OpenRouter, not to our own API, and any process can make it. The
defect was never reachability — it was that nothing ever *awaited* the fetch,
only peeked at its cache. So this module owns the fetch, and every process warms
its own copy under the TTL that already existed.

It also fixes the direction of a dependency: the fetch used to live in a route
module, which is why the price table was an HTTP handler's side effect. The route
now consumes this service, not the reverse.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

#: Reuses the knob the route already had, so the two cannot disagree about how
#: long a price is good for.
CACHE_TTL_SECONDS = settings.model_cache_ttl_seconds

_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_fetch_lock = asyncio.Lock()


@dataclass(frozen=True)
class ModelPrice:
    """Per-token prices for one model, and where they came from."""

    model: str
    prompt_per_token: float
    completion_per_token: float
    #: A value :class:`~app.core.trace_meta.TraceMeta` accepts, so a cost
    #: recorded anywhere carries the same provenance vocabulary.
    source: str = "process_cache"


async def _fetch_openrouter_models() -> list[dict[str, Any]]:
    """Fetch the catalogue with prices. Patched wholesale in tests."""
    headers: dict[str, str] = {}
    if settings.openrouter_api_key:
        headers["Authorization"] = f"Bearer {settings.openrouter_api_key}"

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(f"{OPENROUTER_BASE_URL}/models", headers=headers)
        resp.raise_for_status()
        raw = resp.json()

    models: list[dict[str, Any]] = []
    for item in raw.get("data", []):
        pricing = item.get("pricing") or {}
        models.append(
            {
                "id": item["id"],
                "name": item.get("name", item["id"]),
                "context_length": item.get("context_length"),
                "pricing": {
                    "prompt": pricing.get("prompt", "0"),
                    "completion": pricing.get("completion", "0"),
                },
            }
        )
    return models


async def price_table() -> list[dict[str, Any]]:
    """The catalogue, from this process's cache or from the vendor.

    A failed fetch is **not** cached. Caching it would turn one outage into a
    whole TTL of missing costs, and the point of this module is that the column
    stops being empty.
    """
    cached = _cache.get("openrouter")
    if cached and time.monotonic() - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    async with _fetch_lock:
        cached = _cache.get("openrouter")
        if cached and time.monotonic() - cached[0] < CACHE_TTL_SECONDS:
            return cached[1]
        try:
            models = await _fetch_openrouter_models()
        except Exception:
            # Telemetry must never fail the request a user is waiting for.
            # Logged at WARNING rather than swallowed: a persistently empty
            # price table is exactly the condition that hid for five months.
            logger.warning("model price table unavailable; costs will be None", exc_info=True)
            return []
        _cache["openrouter"] = (time.monotonic(), models)
        return models


async def get_price(model: str | None) -> ModelPrice | None:
    """Prices for *model*, or ``None`` when the table does not name it.

    ``None`` rather than zero: a model absent from the catalogue has an *unknown*
    price, and zero would be a claim about money.
    """
    if not model:
        return None
    for item in await price_table():
        if item.get("id") != model:
            continue
        pricing = item.get("pricing") or {}
        try:
            return ModelPrice(
                model=model,
                prompt_per_token=float(pricing.get("prompt", "0")),
                completion_per_token=float(pricing.get("completion", "0")),
            )
        except (TypeError, ValueError):
            logger.warning("unparseable pricing for %s: %r", model, pricing)
            return None
    return None


def clear_price_cache() -> None:
    """Drop the cached table. For tests, and for a deliberate refresh."""
    _cache.clear()
