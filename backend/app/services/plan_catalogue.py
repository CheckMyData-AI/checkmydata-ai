"""The paid tier catalogue, and the meter the tiers are priced on.

**One home for the ladder.** The rows below are what the migration seeds, what the
pricing page renders, and what the tests assert against. A second copy of these numbers
in a migration is a second source of truth that drifts the first time one is edited.

**There is no free tier, deliberately.** The product is sold per project; an account
without a subscription has *no plan*, which is a different thing from the cheapest one.
Resolving an unsubscribed user onto a retired `free` row is what refused a production
code<->DB sync on 2026-09-06 — see ``test_four_tiers_priced_by_data_volume.py``.

**Token ceilings stay 0.** Established by the 2026-08-31 transition and unchanged here:
the spend limit lives on the account's OpenRouter key as a dollar balance, which is the
only place that can enforce it mid-request. A token count in this table would be a second,
weaker copy of that limit.

**The tier axis is data.** The previous catalogue already described `base` as "1 GB index"
and `scale` as "2 GB index per project" while ``plans`` had no column to hold either — a
promise with no meter. ``max_index_bytes`` is that column, and ``estimate_index_bytes`` is
the meter.
"""

from __future__ import annotations

from typing import Any

GB = 1024**3

#: Bytes one indexed code symbol occupies across its row, its embedding and its BM25
#: posting. Measured as an order-of-magnitude figure rather than a precise one: the point
#: of the meter is to place a project on a tier, and a project near a boundary is a
#: conversation with the operator, not an automatic refusal.
BYTES_PER_SYMBOL = 400
#: Bytes one code-graph edge occupies. Edges carry two ids and a kind and nothing else.
BYTES_PER_EDGE = 150
#: A 384-dimension float32 vector, the shape `all-MiniLM-L6-v2` produces.
BYTES_PER_EMBEDDING = 384 * 4


def estimate_index_bytes(
    *,
    docs_bytes: int,
    symbols: int,
    edges: int,
    embeddings: int = 0,
) -> int:
    """Approximate bytes of index held for one project.

    ``docs_bytes`` is the summed length of ``knowledge_docs.content``; the rest are row
    counts. Deliberately an estimate built from counts rather than a storage query: the
    index spans Postgres, a vector store that may be pgvector or Chroma, and gzip
    snapshots on an ephemeral dyno disk, so no single engine can be asked how big it is.
    """
    return (
        max(0, docs_bytes)
        + max(0, symbols) * BYTES_PER_SYMBOL
        + max(0, edges) * BYTES_PER_EDGE
        + max(0, embeddings) * BYTES_PER_EMBEDDING
    )


#: The ladder. ``0`` means unlimited in every numeric column, as it does throughout
#: ``EntitlementService``. ``max_index_bytes`` is per project.
PAID_TIERS: list[dict[str, Any]] = [
    {
        "id": "base",
        "name": "Base",
        "description": (
            "AI data analyst for your own databases and codebase. "
            "1 project, 5 data sources, 1 GB index, $30/month of LLM credit at cost."
        ),
        "price_usd_month": 199,
        "daily_token_limit": 0,
        "monthly_token_limit": 0,
        "max_connections": 5,
        "max_projects": 1,
        "max_index_bytes": 1 * GB,
        "seats": 5,
        "trial_days": 14,
        "is_active": True,
        "sort_order": 10,
    },
    {
        "id": "scale",
        "name": "Scale",
        "description": (
            "3 projects, 15 data sources, 2 GB index per project, $90/month of LLM credit at cost."
        ),
        "price_usd_month": 599,
        "daily_token_limit": 0,
        "monthly_token_limit": 0,
        "max_connections": 15,
        "max_projects": 3,
        "max_index_bytes": 2 * GB,
        "seats": 20,
        "trial_days": 14,
        "is_active": True,
        "sort_order": 20,
    },
    {
        "id": "team",
        "name": "Team",
        "description": (
            "10 projects, 50 data sources, 5 GB index per project, "
            "$150/month of LLM credit at cost."
        ),
        "price_usd_month": 900,
        "daily_token_limit": 0,
        "monthly_token_limit": 0,
        "max_connections": 50,
        "max_projects": 10,
        "max_index_bytes": 5 * GB,
        "seats": 50,
        "trial_days": 14,
        "is_active": True,
        "sort_order": 30,
    },
    {
        "id": "enterprise",
        "name": "Enterprise",
        "description": (
            "Unlimited projects, data sources and index. LLM credit at cost with no monthly cap."
        ),
        "price_usd_month": 1500,
        "daily_token_limit": 0,
        "monthly_token_limit": 0,
        "max_connections": 0,
        "max_projects": 0,
        "max_index_bytes": 0,
        "seats": 0,
        "trial_days": 14,
        "is_active": True,
        "sort_order": 40,
    },
]

#: Retired and kept only so already-sold subscriptions still resolve. Never reactivated.
RETIRED_TIER_IDS = ("free", "pro")
