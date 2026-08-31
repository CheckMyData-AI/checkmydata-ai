# Billing: $90 per project, tokens at cost, and a build that ships without any of it

**Status:** design, approved on the two decisions below. Not implemented.
**Date:** 2026-08-31
**Supersedes:** the per-user plan model in `plans` / `subscriptions` (free/pro/team).

## Why this document exists

The audit of 2026-08-31 (`docs/reports/billing-audit-2026-08-31.html`) measured four
things that together make the current model unusable, and none of them were visible
before because the product cannot price its own LLM calls:

| Measured | Value |
|---|---|
| Recorded LLM cost, all time, 6 771 calls | **$0.00** — `estimate_cost` knows none of the models in production |
| Database occupied by ONE repository's index | **295 MB of 333 MB** (`doc_embeddings` 178, `code_graph_edges` 74, `code_graph_symbols` 43) |
| Worker time for that one project, August | **91.7 h** — 12 % of a $50 dyno |
| Margin of the Pro tier at its own token allowance | **−$12/month**; Team **−$107** |

The cost is per **project** and permanent; the old model billed per **user** and capped
tokens. Those are different things and they never met.

## The model

**Tiers, not quantity.** One subscription per account; the tier is a bundle of limits and
you upgrade when you outgrow any of them.

| | **Base** | **Scale** |
|---|---|---|
| Price / month | **$199** | **$599** *(stated as "500 or 600" — not final)* |
| LLM credit included, at cost | **$30** | **$90** |
| Projects | 1 | 3 |
| Connections (data sources) | 5 | 15 |
| Index footprint per project | 1 GB | 2 GB |
| Data source types | all | all |

The positioning is per workspace, not per repository: this replaces an analyst costing
several thousand a month, and an analyst is not bought by the repository.

> **We take no margin on API tokens in the cloud offering.** The token half of the bill is
> a pass-through, which is why it is quoted in dollars of credit rather than in tokens.

**Limits above are proposals grounded in one measurement, not observed demand.** The single
production repository — 9 981 files — occupies 295 MB and consumed 91.7 worker-hours in
August; three connections consumed 33.9 of those hours. Base is sized so that repository
fits with headroom; Scale doubles the space per project, as specified. They should move
once a second customer exists.

### Why tiers rather than `quantity`

Three limits move together — projects, connections, footprint. `quantity` expresses one
axis and cannot say "more connections *and* more space". A tier can. Stripe prorates
upgrades and the Customer Portal performs them with no custom UI, so the mechanism is
cheaper than the one it replaces.

**This supersedes the earlier decision to use `quantity` = projects.** That choice was made
before connections were known to be a cost driver, and before the price was set per
workspace rather than per project.

**The known weakness, stated rather than discovered:** a tier has a cliff. A customer who
needs a sixth connection pays $400 more for it. That is the cost of the simplicity, and
the alternative — soft limits — was rejected below.

### Correction to the audit of the same day

`docs/reports/billing-audit-2026-08-31.html` records connections as having "marginal cost
≈ 0". **That was true of storage and false of compute**, and pricing was nearly built on
it:

| | storage | compute |
|---|---|---|
| A connection | `db_index` 1.78 MB total, `connections` 64 kB | **33.9 h of 91.7** — 49 runs at **41.5 min** each |
| A repository | 295 MB (`doc_embeddings` 178 + graph 117) | 34.4 h |

A connection is cheap to hold and expensive to keep current, because the schema index
re-runs on a schedule. Charging by data source is therefore justified by cost, not only by
willingness to pay.

### Decision 3 — the included credit scales with the tier

$30 at Base, $90 at Scale, proportional to price. A customer paying $599 runs more
projects and more connections and will burn more; giving both tiers the same $30 would
make the top-up an ordinary monthly event rather than an exception. Measured support: the
August project burned ~$48 on a single repository.

Margin on the token line is zero by design at every tier; the margin is $169 and $509 on
the tier itself.

### Decision 4 — limits are hard

Exceeding a limit is refused with `402` and an upgrade offer, which is what
`enforce_connection_quota` already does. Soft limits were considered and rejected: they
require a second rule for the customer who sits at 200 % of a limit for a year, and that
rule is a negotiation rather than a policy.

**Storage is the limit that most deserves to be hard.** It is the one that is irreversible
without a rebuild and the one that scales worst — 295 MB for one repository against a
500 MB free database tier.

### Decision 1 — the included allowance expires; purchased credit does not

Chosen deliberately over the two simpler options. Rolling everything over grows an
obligation nobody tracks; expiring everything takes money the customer paid for.

This requires **our own ledger on top of the OpenRouter key**, because OpenRouter has one
counter and we have two pockets:

```
spent_this_period   = usage − usage_at_period_start
included_consumed   = min(spent_this_period, included_grant)
purchased_consumed  = max(0, spent_this_period − included_grant)
```

**Spend depletes the included pocket first.** Not an optimisation — if purchased credit
were consumed first, the customer would lose money they paid for every time the included
grant expired unused.

At renewal:

```
purchased_balance    −= purchased_consumed
included_grant        = tier.included_credit_usd   # 30 at Base, 90 at Scale
usage_at_period_start = usage            # read from the key, not computed
limit                 = usage + included_grant + purchased_balance
```

**Open:** on a mid-period upgrade Stripe prorates the tier price. Whether the included
credit is topped up immediately by the difference ($60 on Base→Scale) or waits for the next
renewal is undecided; the arithmetic above waits.

### Decision 2 — one subscription per account, tier-valued

One Stripe `Subscription` per account carrying one item at the tier's price, `quantity: 1`.
Upgrading swaps the price with `proration_behavior: always_invoice`; the Customer Portal
does it unaided.

**Not one subscription per project.** That was the alternative considered: it isolates
cancellation and binds a key to a project cleanly, at the cost of N invoices a month and N
ledgers to reconcile. The account is the unit the customer thinks in, holds the OpenRouter
key, and receives the bill.

## The OpenRouter key is the ledger

Each account gets its own key through the provisioning API, and that key — not our
database — is the source of truth for what has been spent.

| Endpoint | Use |
|---|---|
| `POST /api/v1/keys` | provision on first paid subscription; `limit` in credits, `limit_reset: null` |
| `GET /api/v1/keys/{hash}` | read `limit`, `usage`, `limit_remaining` |
| `PATCH /api/v1/keys/{hash}` | renewal and top-up both raise `limit` |
| `DELETE /api/v1/keys/{hash}` | revoke on cancellation |

**This removes the broken cost estimator from the billing path.** `estimate_cost` reads an
in-process cache of the `/api/models` route (`cost_estimation_service.py:65`), which the
worker — where most calls happen — can never populate. Under per-account keys, OpenRouter
counts and we read. Our own metering stays, for showing the user their spend, but no money
depends on it.

Two consequences that must not be discovered later:

- Provisioning needs a **Management API key**, a higher privilege than the inference key.
  It belongs in the same class as `MASTER_ENCRYPTION_KEY`: never in the repository, never
  in a log line, and not reachable from the OSS build at all.
- **Stripe's fee makes "no markup" untrue at the cent level.** A $20 top-up nets ~$19.12
  after 2.9 % + $0.30. The decision is to **absorb it** rather than credit net-of-fees:
  ~4 % of top-up revenue, against a claim that stays true without a footnote.

## Splitting billing out of the open-source build

### What is actually true today

The repository is **public and MIT-licensed**, with 0 forks and 1 star. `billing_service.py`
has been public since 2026-06-10 across 3 commits.

**Removing it does not unpublish it.** Git history retains every line, and MIT has already
granted irrevocable rights to whoever has a copy. This split protects work that has not
shipped yet; it does not recall what has. Saying so here is cheaper than discovering it
during a licensing conversation.

### The seam, measured

Billing and metering are different layers, and only one of them should leave:

- **Metering stays.** `usage_service`, `token_usage`, `usage_sink` are imported by 8
  modules including the LLM router and the chat path. A self-hoster wants to know what
  they are spending; that is not a commercial feature.
- **Billing leaves.** 7 modules touch it, and four of them
  (`connections.py`, `projects.py`, `membership_service.py`, `demo.py`) only ever ask
  *"may I create another one?"*.

### The shape

```
OSS (public, MIT)
  app/entitlements/base.py       protocol: quotas, token allowance
  app/entitlements/unlimited.py  the default — every quota answers yes
  app/services/usage_service.py  metering, unchanged
  OPENROUTER_API_KEY             bring your own, from env

cloud (private package, installed only in the cloud image)
  StripeEntitlements             plans, subscriptions, quotas
  OpenRouterProvisioner          per-account keys and the two-pocket ledger
  /api/billing/*                 checkout, portal, webhook, reconcile
```

The four call sites depend on the protocol, never on the implementation. The cloud package
registers itself at start-up; when it is absent — which is the OSS build — the unlimited
provider is used and nothing else changes.

**What this is not.** `BILLING_ENABLED` is a runtime flag over code that ships either way;
it does not remove anything from the repository and never did.

## Prerequisites this design does not remove

From the same audit, and unchanged by any of the above:

1. **Three routers meter nothing.** `doc_generator.py:84`,
   `code_db_sync_analyzer.py:211`, `db_index_validator.py:150` build `LLMRouter()` with no
   sink, so ~758 doc-generation calls per rebuild are recorded nowhere. Under per-account
   keys OpenRouter still counts them — the money is right — but our own usage display will
   understate what the customer spent, which is its own kind of lie.
2. **The billing subject is still a user.** `Subscription.user_id`, while the cost is per
   project and a project has members. Moving it is schema work and touches every quota
   check.
3. **Eight defects in the existing Stripe code**, reviewed against
   `sheleg-dev:stripe-billing` on 2026-08-31 — the API version is unpinned, the period is
   read from the subscription instead of its item (moved in `2025-07-30.basil`),
   `billing_mode` is left to an irreversible default, metadata is written once, and there
   is no reconciliation job.
