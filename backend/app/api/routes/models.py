import logging
import time

import httpx
from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
CACHE_TTL_SECONDS = 3600  # 1 hour

_cache: dict[str, tuple[float, list[dict]]] = {}

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
    now = time.monotonic()
    cached = _cache.get("openrouter")
    if cached:
        ts, data = cached
        if now - ts < CACHE_TTL_SECONDS:
            return data

    headers: dict[str, str] = {}
    if settings.openrouter_api_key:
        headers["Authorization"] = f"Bearer {settings.openrouter_api_key}"

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(f"{OPENROUTER_BASE_URL}/models", headers=headers)
        resp.raise_for_status()
        raw = resp.json()

    models = []
    for item in raw.get("data", []):
        pricing = item.get("pricing")
        models.append(
            {
                "id": item["id"],
                "name": item.get("name", item["id"]),
                "context_length": item.get("context_length"),
                "pricing": {
                    "prompt": pricing.get("prompt", "0") if pricing else "0",
                    "completion": pricing.get("completion", "0") if pricing else "0",
                },
            }
        )

    sorted_models = _sort_openrouter_models(models)
    _cache["openrouter"] = (now, sorted_models)
    return sorted_models


@router.get("", response_model=list[ModelInfo])
async def list_models(provider: str = Query(default="openrouter")):
    """Return available models for the given LLM provider."""
    if provider == "openrouter":
        try:
            return await _fetch_openrouter_models()
        except Exception:
            logger.exception("Failed to fetch OpenRouter models")
            return []

    static = STATIC_MODELS.get(provider)
    if static is not None:
        return static

    return []
