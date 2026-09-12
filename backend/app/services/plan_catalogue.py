"""The paid tier catalogue, and the meter the tiers are priced on.

**One home for the ladder.** The rows below are what the migration seeds, what the
pricing page renders, and what the tests assert against. A second copy of these numbers
in a migration is a second source of truth that drifts the first time one is edited.

**There is no free tier, deliberately.** The product is sold per project; an account
without a subscription has *no plan*, which is a different thing from the cheapest one.
Resolving an unsubscribed user onto a retired `free` row is what refused a production
code<->DB sync on 2026-09-06 — see ``test_four_tiers_priced_by_data_volume.py``.

**The token ceiling is what binds, and this table is where it lives** (D-SPEND-1,
2026-09-11). The previous rule said the opposite — that ceilings stay `0` because "the
spend limit lives on the account's OpenRouter key as a dollar balance, which is the only
place that can enforce it mid-request". That key is minted, encrypted, metered and revoked,
and **no inference call has ever presented it**: `OpenRouterAdapter` binds the shared
operator key at construction and `LLMRouter` carries no account context (BILL-01/BIZ-01,
audit 2026-09-09). So the sentence justified an unarmed gate by pointing at an unarmed gate,
and both belt and braces were off. The key stays — it is attribution at the provider and a
second belt on the OpenRouter path — but the layer that refuses a request is this one.

**The ceilings are derived, never typed.** Each tier promises a dollar figure of LLM credit
in its own description; the token ceiling is that promise divided by one measured blend.
Writing the token count directly is what let a migration and this table hold two different
numbers for the same promise (DATA-01).

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

#: The LLM credit each tier's own description sells, in dollars per month. The single
#: place the promise is a number; the prose repeats it and a test pins the two together.
#: ``enterprise`` is absent deliberately — it promises "no monthly cap", which is ``0``.
PROMISED_CREDIT_USD: dict[str, float] = {"base": 30.0, "scale": 90.0, "team": 150.0}

#: Dollars per million tokens: what turns the promise above into a ceiling the token meter
#: can enforce. **Measured 2026-09-11 against production, then given a named margin.**
#:
#: Production `token_usage` since the 2026-09-10 model switch:
#:
#: | stream | model | $/M blended |
#: |---|---|---|
#: | background | `deepseek/deepseek-v4-flash-0731` | 0.1137 |
#: | indexing | `qwen/qwen3.8-flash` | 0.2686 |
#: | chat | `z-ai/glm-5.2` | 1.84 (catalogue 0.966/3.036 at the measured 58/42 mix) |
#: | **all streams, as actually used** | | **0.1145** |
#:
#: Indexing dominates the token count, so the aggregate sits near the cheapest stream. The
#: figure below is **2.2× that aggregate**, which is the margin for the mix drifting toward
#: chat — not a pretence that every token is a chat token.
#:
#: **Why a margin and not the worst case.** `agent_llm_model` is a per-project field the
#: customer sets (`api/routes/projects.py:52,97`), so they choose the price per token and a
#: token ceiling cannot bound dollars exactly. Calibrating on the most expensive stream
#: bounds the dollars and cuts real work instead: at $1.85/M, `base` would cap at 16.2M
#: tokens a month, and the heaviest real account on production used **16 464 277 tokens in
#: 30 days** — the ceiling would have bound a normal month of the workload `base` is sold
#: for. At the figure below `base` caps at 120M/month, seven times the heaviest observed
#: month, while the worst case — an account routing every token through the priciest chat
#: model — is 120M × $1.84 ≈ $221 against a $199 subscription. Bounded, and roughly the
#: price of the plan.
#:
#: The instrument that needs no margin is dollars: `token_usage.estimated_cost_usd` has
#: been 100% populated since 2026-09-04 (#285), so a cost-denominated gate is now possible
#: and is on the board. Re-measure this constant with::
#:
#:     select model, round((sum(estimated_cost_usd)/nullif(sum(total_tokens),0)*1e6)::numeric,4)
#:     from token_usage where estimated_cost_usd is not null group by model;
BLENDED_USD_PER_MILLION_TOKENS = 0.25

#: What a row nobody could price costs (row 1b). `_estimate_cost` returns ``None`` when
#: the model is absent from the live OpenRouter catalogue — a native OpenAI/Anthropic
#: model, or one withdrawn since. Charging zero is DATA-01's shape all over again: a
#: figure computed from an absence, on the column that now decides whether to refuse.
#:
#: **Deliberately the priciest measured stream, not the blend.** The two constants point
#: in opposite directions and for the same reason. For a CEILING the blend was wrong
#: because it applied to every token, including the cheap indexing tokens that dominate
#: the count. For a FALLBACK on one unpriceable row, under-counting is the hole: an
#: account routing everything through an unpriced model would escape the gate entirely,
#: and an unpriced model is usually a *native* provider model, which is the expensive
#: kind. Over-pricing a row we cannot price is conservative; under-pricing it is a door.
#:
#: 1.85 is the chat stream measured 2026-09-11 (`z-ai/glm-5.2`, catalogue 0.966/3.036 at
#: the observed 58/42 prompt/completion mix).
UNPRICED_USD_PER_MILLION_TOKENS = 1.85


def price_unpriced_tokens(total_tokens: int) -> float:
    """Dollars to charge for tokens whose model carried no price."""
    if total_tokens <= 0:
        return 0.0
    return total_tokens / 1_000_000 * UNPRICED_USD_PER_MILLION_TOKENS


def _cost_ceilings(promised_usd: float) -> tuple[float, float]:
    """(daily, monthly) DOLLAR ceilings for a tier promising *promised_usd* of credit.

    No division, no blend, no margin: the promise is dollars and so is the ceiling.
    Daily is a third of monthly for the same reason it is on the token ceilings — a
    runaway is bounded within one day rather than one month.
    """
    return round(promised_usd / 3, 2), float(promised_usd)


def _ceilings(promised_usd: float) -> tuple[int, int]:
    """(daily, monthly) token ceilings for a tier promising *promised_usd* of credit.

    Rounded to 100 000 tokens: the blend is a measurement with two significant figures and
    a ceiling quoted to the token would claim a precision the input does not have. Daily is
    a third of monthly — enough that a normal day never touches it (the 95th-percentile
    real user-day measured 2 111 241 tokens) and a runaway is bounded within one day rather
    than one month.
    """
    monthly = round(promised_usd / BLENDED_USD_PER_MILLION_TOKENS * 1_000_000, -5)
    return int(round(monthly / 3, -5)), int(monthly)


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
        "daily_cost_limit_usd": _cost_ceilings(PROMISED_CREDIT_USD["base"])[0],
        "monthly_cost_limit_usd": _cost_ceilings(PROMISED_CREDIT_USD["base"])[1],
        "daily_token_limit": _ceilings(PROMISED_CREDIT_USD["base"])[0],
        "monthly_token_limit": _ceilings(PROMISED_CREDIT_USD["base"])[1],
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
        "daily_cost_limit_usd": _cost_ceilings(PROMISED_CREDIT_USD["scale"])[0],
        "monthly_cost_limit_usd": _cost_ceilings(PROMISED_CREDIT_USD["scale"])[1],
        "daily_token_limit": _ceilings(PROMISED_CREDIT_USD["scale"])[0],
        "monthly_token_limit": _ceilings(PROMISED_CREDIT_USD["scale"])[1],
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
        "daily_cost_limit_usd": _cost_ceilings(PROMISED_CREDIT_USD["team"])[0],
        "monthly_cost_limit_usd": _cost_ceilings(PROMISED_CREDIT_USD["team"])[1],
        "daily_token_limit": _ceilings(PROMISED_CREDIT_USD["team"])[0],
        "monthly_token_limit": _ceilings(PROMISED_CREDIT_USD["team"])[1],
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
        # "no monthly cap" has no ceiling to carry, in either unit.
        "daily_cost_limit_usd": 0.0,
        "monthly_cost_limit_usd": 0.0,
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
