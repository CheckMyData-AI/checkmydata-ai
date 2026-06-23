# Module 14 — Billing & Entitlements — Audit Report

**Round 1** · 2026-06-24 · Scope: `routes/billing.py`, `services/billing_service.py`,
`services/entitlement_service.py`, `routes/usage.py`. (Entitlement enforcement call-sites +
Customer-Portal flow flagged for R2 verification.)

Documented contract (CLAUDE.md): Stripe Checkout + Portal + idempotent webhooks; the webhook is
the single writer of subscription state; `EntitlementService` enforces plan token/connection/
project limits → HTTP 402; token-budget gate on all chat entry points.

**Positive notes (verified — billing security is largely sound):**
- Webhook signature is verified via `stripe.Webhook.construct_event` and **fails closed** when
  `STRIPE_WEBHOOK_SECRET` is unset (`billing_service.py:152-158`); bad signature → 400
  (`billing.py:139-141`).
- **Idempotency is race-safe**: the `StripeEvent` ledger row is inserted **first** and an
  `IntegrityError` on the unique `stripe_event_id` marks the delivery a duplicate
  (`:167-178`) — correct concurrent-delivery handling.
- **Atomic + retry-correct**: `_apply_event` failure does `db.rollback()` + re-raise, so the
  ledger row is rolled back and Stripe retries the event (`:182-187`); success commits ledger +
  state together.
- **Checkout sets identity server-side**: `create_checkout_session` validates `plan_id` against an
  active, purchasable `Plan`, derives `price_id` from that plan, and sets
  `client_reference_id=user.id` + `metadata={user_id, plan_id}` from the **authenticated** user —
  no plan/user spoofing at creation (`:104-126`).
- `_set_status_by_customer` won't reactivate a `canceled` subscription (`:275`).

Severity: 🔴 Critical · 🟠 High · 🟡 Medium · 🟢 Low · ⚪ Info

---

## F-BILL-01 — 🟡 Medium — `_resolve_plan_id` prefers stale `metadata.plan_id` over the live subscription price

**Type:** Bug (entitlement drift / possible over-entitlement)
**Location:** `services/billing_service.py:243-258` (`_resolve_plan_id`): returns
`metadata.plan_id` first, only falling back to price→plan mapping.

**Description.** Plan resolution trusts the subscription object's `metadata.plan_id` ahead of the
**actual price** on the subscription. Metadata is set once at checkout creation. If the customer
later changes plans via the **Customer Portal** (upgrade/downgrade), the subscription's price item
changes but its `metadata.plan_id` typically remains the **original** value. The
`customer.subscription.updated` webhook then resolves to the *old* plan — so a user who downgrades
can keep the **higher** plan's entitlements while paying the lower price (and vice-versa).

**Impact.** Entitlement state can diverge from what the customer actually pays for after a Portal
plan change — including retaining higher limits than paid for.

**Proposed fix.** Make the **price → plan** mapping authoritative (it already exists at
`:248-256`); use `metadata.plan_id` only as a fallback when no price item is present. Add a test:
simulate a `subscription.updated` whose price changed but `metadata.plan_id` is stale → assert the
resolved plan follows the price.

---

## F-BILL-02 — 🟡 Medium — Connection/project quota checks are count-then-compare (TOCTOU → quota bypass)

**Type:** Bug (race / limit bypass)
**Location:** `services/entitlement_service.py` (`PlanLimitReachedError(resource, limit, current)`
implies a `count(*)` vs `max_*` comparison before the route inserts the new row); enforced at the
connection/project create routes.

**Description.** Plan quotas (`max_connections`, `max_projects`) are enforced by counting existing
rows and comparing to the limit, then creating the row in a separate step. There is no DB-level
constraint binding the count to the limit, so two concurrent create requests can both pass the
check before either inserts, letting a user exceed their plan quota.

**Impact.** Paid-tier quota bypass under concurrency (create N+1 connections/projects on an N-cap
plan).

**Proposed fix.** Enforce atomically — e.g. an advisory lock / `SELECT … FOR UPDATE` over the
count, or a transactional insert guarded by a conditional check; alternatively accept eventual
correction via a reconciliation sweep. Add a concurrency test creating up to limit+1.

---

## F-BILL-03 — 🟢 Low — Webhook endpoint is unauthenticated-by-design and unthrottled

**Type:** Hardening
**Location:** `routes/billing.py:129-149` (`/webhook`, no rate limit).

**Description.** The webhook must be public (Stripe calls it) and is correctly signature-gated, but
it has no rate limit. An attacker spamming garbage payloads forces a signature verification per
request. `construct_event` fails fast, so impact is low, but a basic rate limit / body-size cap
adds defense.

**Proposed fix.** Add a modest rate limit and a max body size on `/webhook`; keep signature
verification first.

---

## F-BILL-04 — ⚪ Info — Ledger payload truncated to 64KB

**Type:** Observation
**Location:** `billing_service.py:170` (`json.dumps(...)[:65536]`).

**Description.** The stored event payload is truncated at 64KB. It's audit-only (not used for
logic), so this is fine, but a very large event is partially stored — note it if the ledger is
ever used for replay/reconciliation.

---

## Test gaps (⚪ Info)

- No test that a Portal plan change updates entitlements per the **price**, not stale metadata
  (F-BILL-01).
- No concurrency test that quota limits can't be exceeded by parallel creates (F-BILL-02).
- (Positive coverage worth asserting: duplicate webhook delivery is ignored; failed `_apply_event`
  leaves no ledger row so Stripe retries.)

## Summary

| id | sev | one-line |
|----|-----|----------|
| F-BILL-01 | 🟡 | `_resolve_plan_id` trusts stale `metadata.plan_id` over live price → entitlement drift |
| F-BILL-02 | 🟡 | Connection/project quota check is count-then-compare → TOCTOU bypass |
| F-BILL-03 | 🟢 | `/webhook` has no rate limit / body cap |
| F-BILL-04 | ⚪ | Ledger payload truncated at 64KB (audit-only) |

**Next-round focus:** `UsageService.check_token_budget` accuracy (daily/monthly rollover,
timezone, estimated-vs-actual token reconciliation, negative/refund handling); the 402 gate is
applied on **every** connection/project create path (no ungated creator); `routes/usage.py`
exposure of other users' usage; downgrade grace-period handling (`cancel_at_period_end`).
