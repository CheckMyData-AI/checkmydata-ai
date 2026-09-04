"""Cost + complexity estimation helpers (T23).

Pulled out of ``app/api/routes/chat.py`` so the router can focus on HTTP
concerns and so these helpers can be unit-tested in isolation.

Nothing here touches the database. The two SQL/token helpers are pure;
``estimate_cost_async`` delegates the price table to
:mod:`app.services.model_pricing_service`, which owns the fetch and its cache —
this module used to read a route module's private dict instead, which is why
the cost was NULL on every row ever written.
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
    has_subquery = "SELECT" in upper[upper.find("FROM") + 1 :] if "FROM" in upper else False

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


async def estimate_cost_async(
    model: str | None,
    prompt_tokens: int,
    completion_tokens: int,
) -> tuple[float | None, str]:
    """Cost for one call, and where the price came from.

    Returns ``(None, "none")`` when the model is not in the price table — never
    zero, because zero is a claim about money and "unknown" is the truth.

    Replaces a synchronous ``estimate_cost`` that read
    ``app.api.routes.models._cache``: a dict populated only as a side effect of
    an HTTP request to ``GET /api/models``. The worker serves no HTTP, so its
    copy was always empty, and production carried NULL costs on **all 7 664**
    ``token_usage`` rows and **all 222** traces (measured 2026-09-04). Awaiting
    the fetch instead of peeking at its cache is the whole fix; see
    :mod:`app.services.model_pricing_service`.
    """
    from app.services.model_pricing_service import get_price

    price = await get_price(model)
    if price is None:
        return None, "none"
    return (
        round(
            prompt_tokens * price.prompt_per_token + completion_tokens * price.completion_per_token,
            8,
        ),
        price.source,
    )
