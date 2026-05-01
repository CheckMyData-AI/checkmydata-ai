"""Cost + complexity estimation helpers (T23).

Pulled out of ``app/api/routes/chat.py`` so the router can focus on HTTP
concerns and so these helpers can be unit-tested in isolation.

Nothing here touches the database or the HTTP layer — the functions are
pure utilities over SQL strings, token counts, and the cached OpenRouter
pricing table.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_CHARS_PER_TOKEN: int = 4


def compute_sql_complexity(sql: str) -> str:
    """Classify the complexity of a SQL statement for cost/telemetry use.

    Returns one of ``"simple"``, ``"moderate"``, ``"complex"``, ``"expert"``.
    """
    if not sql:
        return "simple"
    upper = sql.upper()
    has_recursive = bool(re.search(r"\bWITH\s+RECURSIVE\b", upper))
    has_cte = bool(re.search(r"\bWITH\b\s+\w+\s+AS\s*\(", upper))
    has_window = bool(re.search(r"\bOVER\s*\(", upper))
    join_count = len(re.findall(r"\bJOIN\b", upper))
    has_subquery = (
        "SELECT" in upper[upper.find("FROM") + 1 :] if "FROM" in upper else False
    )

    if has_recursive:
        return "expert"
    if has_cte and (has_window or join_count > 2):
        return "expert"
    if has_cte or has_window or has_subquery or join_count > 2:
        return "complex"
    if join_count >= 1:
        return "moderate"
    return "simple"


def estimate_tokens(text: str, *, chars_per_token: int = _CHARS_PER_TOKEN) -> int:
    """Approximate a text's token count using the ~4-chars-per-token rule."""
    if not text:
        return 0
    return max(0, len(text) // max(1, chars_per_token))


def estimate_cost(
    model: str | None,
    prompt_tokens: int,
    completion_tokens: int,
) -> float | None:
    """Estimate USD cost using cached OpenRouter pricing data when available.

    Returns ``None`` when pricing data is missing or the model is unknown.
    """
    if not model:
        return None
    try:
        from app.api.routes.models import _cache

        cached = _cache.get("openrouter")
        if not cached:
            return None
        _, models_list = cached
        for m in models_list:
            if m["id"] == model:
                pricing = m.get("pricing", {})
                prompt_price = float(pricing.get("prompt", "0"))
                completion_price = float(pricing.get("completion", "0"))
                return round(
                    prompt_tokens * prompt_price + completion_tokens * completion_price,
                    8,
                )
    except Exception:
        logger.debug("Cost computation failed", exc_info=True)
    return None
