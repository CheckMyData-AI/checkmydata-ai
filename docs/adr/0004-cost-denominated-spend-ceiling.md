# ADR-0004 — The ceiling is denominated in dollars, and tokens become the backstop

- **Status:** Accepted, 2026-09-12
- **Deciders:** implementing agent, autonomously, under the operator's standing
  instruction to work the 2026-09-09 backlog without stopping for decisions the code and
  the measurements can settle
- **Amends:** `ADR-0003` — *"The token ceiling is the layer that binds LLM spend"*. That
  decision stands as taken: at the time, `estimated_cost_usd` was NULL on 44% of the last
  thirty days' rows, and a gate cannot be built on a column that is missing for nearly
  half its inputs. ADR-0003 itself named this successor and the three things it needs.
- **Related:** backlog row 1b; findings BILL-01, BIZ-01, DATA-06

## Context

Every tier sells dollars. `base` includes $30 of LLM credit a month, `scale` $90, `team`
$150; `enterprise` promises no monthly cap. That promise reached the gate by division:

    monthly_token_ceiling = promised_usd / BLENDED_USD_PER_MILLION_TOKENS

with the constant set to **$0.25/M against an aggregate of $0.1145/M actually measured on
production** — a 2.2× margin. ADR-0003 named that margin honestly and explained why it is
not caution:

> `agent_llm_model` is a per-project field the customer sets, so they choose the price per
> token and a token ceiling cannot bound dollars exactly.

The margin is the cost of the wrong unit. Both directions are wrong and the ADR measured
both: calibrated on the priciest stream ($1.85/M) the `base` ceiling becomes 16.2M
tokens/month against a real account's **16 464 277 tokens in 30 days** — a bound below
observed use, for the exact workload `base` is sold for. Calibrated on the blend, the
worst case is 120M × $1.84 ≈ **$221 against a $199 subscription**.

What changed is the input. `token_usage.estimated_cost_usd` has carried a value on
**every row since 2026-09-04** (#285, which moved the price fetch out of a cache only the
web process could populate). The 44% NULL rate that disqualified it is entirely older
rows.

## Decision

**Dollars are the gate. Tokens stay as a backstop behind them.**

- `plans` gains `daily_cost_limit_usd` and `monthly_cost_limit_usd`, `Numeric(12,4)`,
  `0` meaning unlimited as it does in every other column on that table.
- `PAID_TIERS` sets them **directly from `PROMISED_CREDIT_USD`** — no blend, no division,
  no margin. Daily is a third of monthly, the same shape the token ceilings use and for
  the same reason: a runaway is bounded within a day rather than a month.
- `check_budget` sums `estimated_cost_usd` over the window and refuses on the dollar
  ceiling first, because that is the ceiling the customer was sold.

### Three consequences, each decided rather than fallen into

**An unpriced row is charged, not forgiven.** `_estimate_cost` returns `None` when the
model is absent from the live OpenRouter catalogue — a native OpenAI/Anthropic model, or
one withdrawn since. Charging zero would be DATA-01's shape on a new column: a figure
computed from an absence, on the number that decides whether to refuse. Such rows are
priced at `UNPRICED_USD_PER_MILLION_TOKENS`, and the response reports how much of the
total was estimated rather than measured, so *"the gate is guessing"* is visible.

**That fallback is the priciest measured stream, not the blend — and the two constants
point in opposite directions on purpose.** For a *ceiling* the blend was right and the
worst case wrong, because the ceiling applies to every token and the cheap indexing
tokens dominate the count. For a *fallback on one unpriceable row* the reverse holds:
under-counting is a door, since an account routing everything through an unpriced model
would escape the gate entirely, and an unpriced model is usually the expensive native
kind. Over-pricing what cannot be priced is conservative; under-pricing it is the hole.

**The token ceiling is not deleted.** Cost accounting can itself fail — an unreachable
price table over a long window — and removing the coarse net would turn that into no gate
rather than a looser one. It is no longer the instrument, so the margin on
`BLENDED_USD_PER_MILLION_TOKENS` is now the backstop's slack rather than the enforcement.

### And the precondition: money stops being a float

DATA-06 ships here rather than separately, because this change turns
`sum(estimated_cost_usd)` from a report into a **gate**. Summing thousands of IEEE-754
doubles is order-dependent: the same month's spend can differ in the last digits between
two calls that see the rows in a different plan order. `app/models/llm_credit.py` already
states the rule for the codebase; `plans.price_usd_month`, `token_usage.estimated_cost_usd`
and `request_traces.estimated_cost_usd` now follow it.

That change has one non-obvious consequence, closed in the same commit: a `Numeric` column
returns `Decimal`, and `plan_catalogue_reconcile` compares each declared field against the
stored one. `Decimal("10.0000") == 10.0` is True, so every price the ladder holds today
happens to survive a plain `!=` — but `Decimal("199.9900") == 199.99` is **False**, and
the first tier priced with real cents would make the reconcile rewrite the whole catalogue
on every boot of every dyno, silently and for ever. The comparison is `Decimal` on both
sides now, and a test exercises exactly the $199.99 case rather than reasoning about it.

## Alternatives rejected

- **Keep tokens and raise the margin.** The margin is the symptom. Raising it widens the
  gap between what a customer is sold and what they are allowed, in whichever direction
  their model choice happens to fall.
- **Replace tokens entirely.** Leaves no gate at all when the price table is unreachable.
- **Refuse an unpriced call.** An outage caused by the price table, on a path whose whole
  purpose is to keep answering.
- **A config env var for the dollar ceiling**, mirroring `USER_*_TOKEN_LIMIT`. Those exist
  so a self-hosted operator paying their own provider bill can set a coarse brake. A
  dollar ceiling is a statement about what a *subscription* includes; giving a self-hosted
  install one would enforce a spend cap nobody sold them.

## Consequences

- The margin no longer stands between the promise and the enforcement: `base` refuses at
  $30 because $30 is what it sells.
- A month's spend is now exact rather than order-dependent.
- `/api/billing/subscription` reports spend and ceiling in dollars, plus how much of the
  spend was estimated.
- `BLENDED_USD_PER_MILLION_TOKENS` still rots as the model mix moves, but rot in the
  backstop's slack is a much smaller claim than rot in the enforcement.
- **Still open:** `P0-1c`, the per-account OpenRouter key on the inference path. Unchanged
  by this: its value is provider-side attribution, and it remains additive against a
  product that is now bounded in the unit it is sold in.
