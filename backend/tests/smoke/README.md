# Startup smoke suite

Fast, deterministic confirmation that the core machine works on the canonical
billing/subscriptions business scenario. Designed to run at server boot / in
CI in a few seconds (no network, no real LLM, no real DB server).

## Run

```bash
make smoke
# equivalently, from backend/:
.venv/bin/pytest tests/smoke -m smoke -q
```

## What it covers

The scenario is a billing/subscriptions project (we do **not** have its prod
data, so `conftest.py` seeds a representative `orders` schema with FIXED dates
derived from a hardcoded anchor — never `datetime.now()`):

1. **Revenue, last 3 months, by payment method** — runs the real GROUP BY SQL
   against the seeded aiosqlite DB; asserts per-method totals and the grand
   total equal hand-computed values, and that a pre-cutoff row is excluded.
2. **Weekly cohort metrics, last 3 months** — avg order value, purchase count,
   and total revenue per weekly cohort (SQLite `%W`); asserts every cohort.
3. **`SafetyGuard`** (real `app.core.safety`) — blocks UPDATE/DELETE/DROP/INSERT
   and stacked statements in read-only mode; allows a SELECT.
4. **`DataGate`** (real `app.agents.data_gate`) — hard-fails an impossible
   bounded percentage (`conversion_pct = 150`) and a negative count; passes a
   clean revenue result.
5. **`_validate_plan_structure`** (real `app.agents.query_planner`) — a
   well-formed `query_database -> process_data -> synthesize` cohort plan
   validates with no errors.
6. **`route_request`** (real `app.agents.router`, mocked LLM) — classifies the
   revenue question to a usable `RouteResult` (not the error-fallback default).

## Expected numbers (hand-computed from the seed)

Revenue by payment method (cents): `apple=18000`, `card=7500`, `google=5500`;
grand total `31000`. 11 in-window orders (one pre-cutoff order is excluded).

Weekly cohorts (SQLite `%W` label: purchases / total cents / avg cents):
`2026-14: 2 / 4000 / 2000`, `2026-15: 2 / 4000 / 2000`, `2026-16: 1 / 5000 / 5000`,
`2026-18: 1 / 1500 / 1500`, `2026-19: 1 / 2500 / 2500`, `2026-20: 1 / 4000 / 4000`,
`2026-22: 1 / 3000 / 3000`, `2026-23: 1 / 1000 / 1000`, `2026-24: 1 / 6000 / 6000`.

The numbers are recomputed in the tests from `conftest.SEED_ROWS`, so changing
the seed updates the expectations automatically rather than drifting from a
copied magic table.
