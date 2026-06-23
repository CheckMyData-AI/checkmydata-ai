# Module 18 — Semantic layer / Data graph / Temporal / Exploration / Models / Demo — Audit Report

**Round 1** · 2026-06-24 · Scope: `routes/{semantic_layer,data_graph,temporal,exploration,
models,demo}.py`. (Deep handler-logic review of semantic/graph/temporal deferred to R2; this pass
focused on auth scoping + the demo/models surface.)

**Positive notes (verified):**
- These routes are **auth-gated**: every `project_id`-scoped route pairs `get_current_user` with a
  `MembershipService.require_role` check (auth-ref density ≥2 per route across `semantic_layer`
  3 routes / `data_graph` 7 / `temporal` 2 / `exploration` 1). Full per-handler confirmation
  deferred to R2, but the pattern is consistent — no obvious IDOR.
- `models.list_models` requires auth and **does not leak the API key**: `openrouter_api_key` is
  used only in the server→OpenRouter outbound request (`models.py:102-103`); the response is
  model ids/names (`list[ModelInfo]`).
- `demo_setup` requires auth and is rate-limited (3/min).

Severity: 🔴 Critical · 🟠 High · 🟡 Medium · 🟢 Low · ⚪ Info

---

## F-EXP-01 — 🟡 Medium — Demo project is broken/misleading: `:memory:` SQLite, no seeding

**Type:** Bug (feature broken / misleading docstring)
**Location:** `routes/demo.py:22-65` (`demo_setup`): docstring says "seed tables", but the handler
**never seeds**, and the connection is `db_name=":memory:"` SQLite.

**Description.** `demo_setup` creates a "Demo Project" + a SQLite connection pointed at `:memory:`
and claims to seed sample tables — but there is **no seeding code** anywhere (no `CREATE TABLE`/
`INSERT`, no demo-data service). Worse, `:memory:` SQLite is **per-connection**: data created on
one connection is invisible to the next, so even if the frontend tried to seed it post-setup, the
data wouldn't persist across the pooled connector's connections (or process restarts). The result
is a demo project with **no data to query** — the agent will return empty results for every demo
question, undermining the first-run experience (the activation funnel this product is investing in,
per recent dashboard work).

**Impact.** The demo — a key activation/onboarding surface — produces an empty database; users
trying the product via "Demo" get nothing.

**Proposed fix.** Seed a **file-based** SQLite (e.g. `data/demo_{project_id}.db`) with realistic
sample tables + rows during `demo_setup` (idempotently), or point the demo at a shared, read-only,
pre-seeded sample database. Add a smoke test: `demo_setup` → ask a question → assert non-empty
results.

---

## F-EXP-02 — 🟢 Low — Demo connection is created writable (`is_read_only=False`), against read-only-default posture

**Type:** Consistency (vision §7)
**Location:** `routes/demo.py:51` (`is_read_only=False`).

**Description.** Even for a throwaway demo, defaulting the connection to writable contradicts the
"read-only by default" invariant. There's no reason a demo needs DML.

**Proposed fix.** Create the demo connection `is_read_only=True` (the seed step can write
out-of-band before the connection is exposed to the agent).

---

## F-EXP-03 — 🟢 Low — `demo_setup` creates real Project+Connection (quota + clutter, no dedup)

**Type:** Resource / UX
**Location:** `routes/demo.py:32-52`.

**Description.** Each `demo_setup` call creates a real `Project` + `Connection` owned by the user —
counting against plan quotas (cf F-BILL-02) and cluttering the workspace. At 3/min there's no
idempotency/dedup, so repeated clicks spawn multiple identical "Demo Project"s.

**Proposed fix.** Make `demo_setup` idempotent (reuse an existing demo project for the user), and
consider exempting the demo project from plan quotas or auto-expiring it.

---

## F-EXP-04 — ⚪ Info — `models` endpoint discloses which providers are configured

**Type:** Minor info disclosure
**Location:** `routes/models.py:102` (live OpenRouter list when key set, else static).

**Description.** The live-vs-static behaviour reveals to any authenticated user whether a given
provider key is configured. Low sensitivity; noted for completeness.

---

## Test gaps (⚪ Info)

- No smoke test that the demo project returns non-empty results after setup (F-EXP-01).
- No test that the demo connection is read-only (F-EXP-02).
- R2: confirm each `semantic_layer`/`data_graph`/`temporal`/`exploration` handler calls
  `require_role` with the correct minimum role (viewer for reads, editor/owner for builds).

## Summary

| id | sev | one-line |
|----|-----|----------|
| F-EXP-01 | 🟡 | Demo uses `:memory:` SQLite with no seeding → demo project has no data |
| F-EXP-02 | 🟢 | Demo connection created writable, against read-only default |
| F-EXP-03 | 🟢 | `demo_setup` creates real quota-counting Project+Connection, no dedup |
| F-EXP-04 | ⚪ | `models` endpoint discloses configured providers |

**Next-round focus:** per-handler `require_role` minimum-role correctness across semantic_layer
(build = editor?), data_graph, temporal, exploration; semantic-layer LLM normalization injection
surface; data_graph lineage exposure (does it leak cross-connection structure?); temporal analysis
query guarding.
