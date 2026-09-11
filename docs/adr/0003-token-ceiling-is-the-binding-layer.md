# ADR-0003 — The token ceiling is the layer that binds LLM spend

- **Status:** Accepted, 2026-09-11
- **Deciders:** implementing agent, autonomously, under the operator's standing
  instruction to work the 2026-09-09 backlog without stopping for decisions the code and
  the measurements can settle
- **Supersedes / amends:** the docstring rule in `backend/app/services/plan_catalogue.py`
  ("Token ceilings stay 0 … the spend limit lives on the account's OpenRouter key as a
  dollar balance, which is the only place that can enforce it mid-request"), established
  2026-08-31
- **Related:** `docs/audits/2026-09-09-full-system-audit.md` findings BILL-01, BILL-02,
  BIZ-01, BIZ-02, DATA-01, API-08, BILL-10; backlog row P0-1

## Context

The product's dominant variable cost is LLM inference, and on 2026-09-09 an audit
established that **nothing bounded it on any account**. Two layers were supposed to:

1. **A per-account OpenRouter key with a dollar ceiling.** Minted by
   `BillingService._sync_subscription`, Fernet-encrypted, metered in two pockets, renewed
   on `subscription_cycle`, revoked on cancellation. It is never presented to the
   provider: `OpenRouterAdapter.__init__` binds `settings.openrouter_api_key` — one shared
   operator key — at construction, and `LLMRouter` carries no account context at all.
   `key_encrypted` is decrypted in exactly one place, inside `provision()`, whose return
   value the only caller discards.
2. **Token ceilings on the plan.** `check_token_budget` at every chat entry point,
   `DbUsageSink` re-checking after each call, `_strictest(plan, config)` combining the two
   sources. All four tiers carried `0`, which means *unlimited*, and the global config
   fallbacks are unset in production. Migration `c3d4e5f6a7b8` wrote real numbers into
   `plans`; `plan_catalogue_reconcile` — running in the FastAPI lifespan, i.e. after the
   release phase — overwrote them with the catalogue's zeros on **every boot**.

The second layer was loosened *because* the first was believed to hold. The catalogue's
own docstring said so in as many words. So the belt was taken off to make room for braces
that were never fitted, and the argument for each was the existence of the other.

## Decision

**The token ceiling is the layer that binds. The per-account key stays, demoted to
attribution at the provider and a second belt on the OpenRouter path.**

Three properties decided it, and all three are checkable:

- **Reach.** `LLMRouter` falls back across OpenAI, Anthropic and OpenRouter. A key-side
  dollar ceiling cannot bind on two of those three, so a deployment configured with an
  `OPENAI_API_KEY` would be uncapped no matter how carefully the key is provisioned. The
  token ceiling counts tokens whoever served them.
- **Cost of arming it.** The token gate is complete and inert: entry check, post-call
  re-check, plan columns, config fallbacks, a `BudgetExceededError` with a user-facing
  message. Arming it is a data change plus wiring six unmetered routers. Arming the key
  instead means threading per-request account context into an adapter constructed once per
  process, at 24 construction sites, and decrypting a spending credential on the request
  path.
- **Failure direction.** A token ceiling that breaks fails *closed* on the next request
  and the user sees a message. A key ceiling that breaks fails at the provider, mid-answer,
  with an error the product cannot explain.

### The numbers are derived, not typed

Each tier's description sells a dollar figure of LLM credit. `PROMISED_CREDIT_USD` holds
that figure once; `BLENDED_USD_PER_MILLION_TOKENS` converts it; `_ceilings()` produces the
pair the catalogue row carries. Writing token counts directly is exactly how a migration
and the catalogue came to hold two different numbers for one promise.

**The blend is the aggregate actually measured, with a stated 2.2× margin — and the first
draft of this decision got it wrong in a way worth recording.** Production after the
2026-09-10 model switch bills $0.1145/M across all streams (background 0.1137, indexing
0.2686, chat ~1.84 at the measured 58/42 prompt-completion mix); indexing dominates the
token count, so the aggregate sits near the cheapest stream.

The first calibration used the *most expensive* stream, $1.85/M, reasoning that an error
costing a customer headroom beats one costing the operator an unbounded bill. Then the same
production database answered the question that reasoning had not asked: the heaviest real
account used **16 464 277 tokens in 30 days**, against the 16 200 000/month that $30 buys
at $1.85/M. The conservative ceiling would have refused an ordinary month of exactly the
workload `base` is sold for — "1 project, 5 data sources, 1 GB index" is that project. A
bound below observed use is not caution, it is a false cut-off with the evidence already in
hand.

Two further facts settle the shape. `agent_llm_model` is a per-project field the **customer**
sets (`api/routes/projects.py:52,97`), so they choose the price per token and no token
ceiling can bound dollars exactly — calibrating on the worst case does not remove that, it
only moves the error onto the customer. And the ceiling's worst case is bounded anyway: at
$0.25/M, `base` caps at 120M tokens, which even entirely through the priciest chat model is
$221 against a $199 subscription.

Resulting ceilings: `base` 40M/day · 120M/month, `scale` 120M · 360M, `team` 200M · 600M,
`enterprise` unlimited. Each monthly figure is seven times the heaviest month ever measured;
each daily figure is ten times the heaviest day (3 968 564).

### D-SPEND-2b — a tier sold without a cap is provisioned no key

`enterprise` is sold as "LLM credit at cost with no monthly cap". `included_grant_usd` is
`NOT NULL`, so "unlimited" cannot be expressed on the row without a schema change, and the
value that *was* being sent — `0.0`, arriving through a `.get(..., 0.0)` default — is the
one reading that contradicts the promise outright: a $0 lifetime ceiling. The tier
therefore gets no key. `key_hash is None` is a state every method in
`OpenRouterCreditService` already handles, so this needs no new column and no new concept.

## Consequences

- **A real ceiling exists on every paid tier for the first time.** An account over its
  daily or monthly ceiling is refused at the chat entry points with an explanatory message.
- **Unattended work is gated at the door, not mid-run.** `may_run_scheduled_work` (2026-09-07)
  decides whether a nightly sync starts; the indexing sinks record without gating, because
  halting a rebuild at document 400 of 758 leaves a half-indexed project and still charges
  for the 400.
- **The blend constant rots when the model mix moves**, and it moved 35× in one day on
  2026-09-10. The constant carries the query that re-measures it, and the derivation is
  pinned by a test, so the rot is visible at one line rather than spread across four.
- **The honest instrument is dollars, and it is now available.** The promise is
  denominated in dollars, the customer picks the price per token, so any token figure is a
  proxy carrying a margin in one direction or a false cut-off in the other.
  `token_usage.estimated_cost_usd` looked unusable — NULL on 44% of the last 30 days'
  rows — until the rows were read by day: **every row since 2026-09-04 has a cost**, and
  the NULLs are entirely older than #285, which moved the price fetch out of a cache only
  the web process could populate. A cost-denominated ceiling therefore needs no blend
  constant and no margin. It needs two columns on `plans`, a unit change in
  `check_budget`, and a decision about what a row with an unresolvable price costs — which
  is a board row of its own, not a rider on this one.
- **BILL-01's other half stays open by choice.** If the per-account key is ever wanted on
  the inference path — for provider-side attribution per customer, which is a real benefit
  this ADR does not deliver — it is now an additive change against a product that is
  already bounded, rather than the only thing standing between an account and an unbounded
  bill.
