"""Put a real token ceiling on the paid tiers.

Revision ID: c3d4e5f6a7b8
Revises: a1c2e3f4b5d6
Create Date: 2026-09-02

`4f1a29a0e973` activated `base` ($199) and `scale` ($599) with
`daily_token_limit = 0` and `monthly_token_limit = 0`, and `0` means **unlimited**
(`usage_service.py:138` returns early when neither limit is set). Both rows describe
a ceiling in their own `description` — "$30/month of LLM credit at cost" and
"$90/month" — so the row contradicted itself: the sentence sold a cap, the columns
removed one.

Nothing else caught it. `USER_DAILY_TOKEN_LIMIT` / `USER_MONTHLY_TOKEN_LIMIT` are unset
in production, `effective_token_limits` takes the strictest **non-zero** of plan and
config, and `trialing` is in `ACTIVE_STATUSES` — so a 14-day trial, having paid nothing,
ran the agent against the operator's single OpenRouter key with no gate anywhere. The
migration's own comment said the limit "lives on the account's OpenRouter key";
`OpenRouterCreditService.provision` has no caller in the repository.

## Where the numbers come from

Measured against production `token_usage` on 2026-09-02, not chosen:

| | |
|---|---|
| prompt / completion split (`openai/gpt-4o`, all time) | 14 593 199 / 3 768 306 → 79.5% / 20.5% |
| `openai/gpt-4o` list price (fetched from OpenRouter) | $2.50/M prompt, $10.00/M completion |
| blended | **$4.0392 per million tokens** |
| $30 of credit | 7.43 M tokens |
| $90 of credit | 22.28 M tokens |

Rounded to 7.5 M and 22.5 M — 1% above the promised credit, which is the direction that
errs toward the customer. `test_plan_token_ceilings.py` recomputes this and fails if the
constants and the derivation drift apart.

The blend agrees with the project's own earlier arithmetic: `test_plan_catalogue_transition`
records that the retired Pro tier's 15 M tokens were "worth ~$61", i.e. $4.07/M.

## The daily cap

Measured over 79 real user-days: median 540 804, p95 2 111 241, max 4 975 830. The daily
cap is one third of the monthly one — 2.5 M for base, 7.5 M for scale — which is above
p95 and bounds a runaway loop to a third of the month's credit instead of all of it.

The single heaviest user-day on record (4 975 830 tokens, about $20 at the blend above)
**would** exceed base's daily cap. That is the plan's economics rather than a mis-set
number: base includes $30 of credit for the whole month, so it cannot afford a $20 day.

## What this is, and what it is standing in for

A token ceiling is a proxy for a cost ceiling, exact only while the model mix holds.
Switching the default to `anthropic/claude-opus-4.8` ($5/$25) makes the same token count
cost about 2.4x more, and this ceiling would not notice.

The mechanism actually designed for this is already in the schema and dormant.
`b48fcfc1524b` created `llm_credit` — two pockets over one OpenRouter counter, an
`included_grant_usd` that expires monthly and a `purchased_balance_usd` that does not,
money in `Numeric` — and `OpenRouterCreditService.provision` fills it. **Nothing calls
`provision`.** So the dollar ceiling the billing model was built around has never been
armed for a single account, and every request runs against one shared operator key.

That is a separate change (`_sync_subscription` has to provision on activation and revoke
on deletion, and the router has to resolve the per-account key). Until it lands, this is
what stands between a 14-day trial that has paid nothing and an unbounded provider bill,
so it ships now rather than waiting for the better mechanism.

Second gap in the same area, recorded rather than fixed here: `estimated_cost_usd` is NULL
on all 6 771 production rows, because `estimate_cost` reads an in-process cache of the
`/api/models` HTTP response — which the worker process, serving no HTTP, never populates.
The operator therefore has no cost figure for any request ever made.
"""

from alembic import op

revision = "c3d4e5f6a7b8"
down_revision = "a1c2e3f4b5d6"
branch_labels = None
depends_on = None

# Monthly = the credit the plan's own description promises, at the measured blend.
# Daily = one third of it. See the module docstring for the derivation.
BLENDED_USD_PER_MILLION_TOKENS = 4.0392
LIMITS = {
    "base": {"monthly": 7_500_000, "daily": 2_500_000, "promised_usd": 30},
    "scale": {"monthly": 22_500_000, "daily": 7_500_000, "promised_usd": 90},
}


def upgrade() -> None:
    for plan_id, lim in LIMITS.items():
        op.execute(
            "UPDATE plans SET "
            f"monthly_token_limit = {lim['monthly']}, daily_token_limit = {lim['daily']} "
            f"WHERE id = '{plan_id}'"
        )


def downgrade() -> None:
    for plan_id in LIMITS:
        op.execute(
            f"UPDATE plans SET monthly_token_limit = 0, daily_token_limit = 0 WHERE id = '{plan_id}'"
        )
