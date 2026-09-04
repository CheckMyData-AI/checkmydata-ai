import logging
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.api.deps import get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# The cache, its TTL and its lock moved to
# :mod:`app.services.model_pricing_service` on 2026-09-04. They lived here, which
# made the price table an HTTP handler's side effect: the worker never served a
# request, so its copy stayed empty and every cost it wrote was NULL — all 7 664
# rows of them. One table now, owned by the service, read by this route and by
# the cost estimator.

STATIC_MODELS: dict[str, list[dict]] = {
    "openai": [
        {"id": "gpt-4o", "name": "GPT-4o", "context_length": 128000},
        {"id": "gpt-4o-mini", "name": "GPT-4o Mini", "context_length": 128000},
        {"id": "gpt-4-turbo", "name": "GPT-4 Turbo", "context_length": 128000},
        {"id": "gpt-4", "name": "GPT-4", "context_length": 8192},
        {"id": "gpt-3.5-turbo", "name": "GPT-3.5 Turbo", "context_length": 16385},
        {"id": "o1", "name": "o1", "context_length": 200000},
        {"id": "o1-mini", "name": "o1 Mini", "context_length": 128000},
        {"id": "o3-mini", "name": "o3 Mini", "context_length": 200000},
    ],
    "anthropic": [
        {"id": "claude-sonnet-4-20250514", "name": "Claude Sonnet 4", "context_length": 200000},
        {"id": "claude-opus-4-20250514", "name": "Claude Opus 4", "context_length": 200000},
        {"id": "claude-3-5-haiku-20241022", "name": "Claude 3.5 Haiku", "context_length": 200000},
        {"id": "claude-3-5-sonnet-20241022", "name": "Claude 3.5 Sonnet", "context_length": 200000},
    ],
    # Minimal OpenRouter fallback when the live API is unreachable. Keep this
    # list short and focused on reliable, widely-available models — the
    # live endpoint returns the full catalogue normally.
    "openrouter": [
        {
            "id": "anthropic/claude-sonnet-4",
            "name": "Claude Sonnet 4",
            "context_length": 200000,
        },
        {
            "id": "anthropic/claude-3.5-sonnet",
            "name": "Claude 3.5 Sonnet",
            "context_length": 200000,
        },
        {
            "id": "anthropic/claude-3.5-haiku",
            "name": "Claude 3.5 Haiku",
            "context_length": 200000,
        },
        {"id": "openai/gpt-4o", "name": "GPT-4o", "context_length": 128000},
        {"id": "openai/gpt-4o-mini", "name": "GPT-4o Mini", "context_length": 128000},
        {"id": "openai/o1", "name": "o1", "context_length": 200000},
        {"id": "openai/o3-mini", "name": "o3 Mini", "context_length": 200000},
    ],
}


class ModelInfo(BaseModel):
    id: str
    name: str
    context_length: int | None = None
    pricing: dict[str, str] | None = None


def _sort_openrouter_models(models: list[dict]) -> list[dict]:
    """Anthropic models first, then the rest. Each group sorted alphabetically by id."""
    anthropic = []
    others = []
    for m in models:
        if m["id"].startswith("anthropic/"):
            anthropic.append(m)
        else:
            others.append(m)
    anthropic.sort(key=lambda m: m["id"])
    others.sort(key=lambda m: m["id"])
    return anthropic + others


async def _fetch_openrouter_models() -> list[dict]:
    """The catalogue, from :mod:`app.services.model_pricing_service`.

    The fetch and its cache moved into that service on 2026-09-04. They lived
    here, which made the price table an HTTP handler's side effect: the worker
    never served a request, so its copy stayed empty and every cost it wrote was
    NULL. This route is now a consumer of the same table the cost estimator uses,
    so the two cannot drift and the vendor is not called twice.
    """
    from app.services.model_pricing_service import price_table

    return _sort_openrouter_models(list(await price_table()))


@router.get("", response_model=list[ModelInfo])
async def list_models(
    provider: Literal["openrouter", "openai", "anthropic"] = Query(default="openrouter"),
    _user: dict = Depends(get_current_user),
):
    """Return available models for the given LLM provider."""
    if provider == "openrouter":
        # `price_table()` degrades to an empty list rather than raising — it is
        # telemetry for the cost estimator as well as data for this endpoint,
        # and it must never fail a request. An empty table here means the vendor
        # was unreachable, so the static catalogue is the honest answer.
        models = await _fetch_openrouter_models()
        if models:
            return models
        logger.warning("OpenRouter model list unavailable; serving the static catalogue")
        return STATIC_MODELS.get("openrouter", [])

    static = STATIC_MODELS.get(provider)
    if static is not None:
        return static

    return []
