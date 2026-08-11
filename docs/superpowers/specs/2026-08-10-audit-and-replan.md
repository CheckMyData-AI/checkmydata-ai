# Audit of the 2026-08-08…10 run, and a re-planned backlog

**State:** `HEAD 0ef6146`, tree clean, 19 commits, production **v209**.
**New input that changes everything below:** the product is **pre-launch — there are no
users yet.** Every priority in the previous backlog was implicitly ranked as if live
traffic existed. It does not, and that inverts several rankings.

---

## Part 1 — What was actually solved

Each row is shipped and verified, not merely committed.

| # | Problem | Evidence it is solved |
|---|---|---|
| 1 | **A timeout was treated as broken SQL.** Production trace 2026-08-06 11:39: ten `query_repair` calls = 120 280 ms rewriting a correct query; 277 831 ms inside the SQL tool; request killed at the 360 s ceiling | `QueryErrorType` moved to a leaf module, `QueryResult.error_type` added, four connectors set it, classifier honours it at both `QueryResult` call sites. `_MAX_TIMEOUT_REPAIRS = 1`. Probed red→green. **v202** |
| 2 | **The SQL tool loop could not stop.** Bounded only by `max_sql_iterations`; the orchestrator's 180 s budget is checked between *its* iterations and the whole SQL agent runs inside one | Consecutive-timeout breaker + wall-clock deadline, both call-frame locals. `SQL_TIMEOUT_BREAKER_THRESHOLD` rejects non-positive at boot. **v202** |
| 3 | **`finalize_trace` erased what the run measured.** Its UPDATE listed every column unconditionally, so its own parameter defaults nulled a 323 s duration, zeroed the steps and reset route/complexity | UPDATE is now additive; `failure_kind` parameter added (it had none). Test asserts on the emitted statement after the first version was caught passing against a planted defect. **v202** |
| 4 | **Cross-tenant SSH private-key use.** `ssh_key_id` accepted unchecked at write; the internal decrypt path is deliberately unfiltered and trusted that check | Guarded at **four** write sites (`connections` create + merged-row update, `projects`, `repos.add_repository`). Three tests failed against `main` before the fix; the fourth site was found only after the first sweep declared itself done. **v205** |
| 5 | **Cross-tenant MCP adapter swap.** One `MCPSourceAgent` per process; `run()` stashed the caller's adapter on `self` and awaited, `_run_with_adapter` read it back — including at `call_tool` | Adapter threaded as an argument, save/restore deleted. Reproduced first, and the reproduction exposed a second form: the `finally` nulled a live request's adapter, so an innocent request got "MCP tool failed" |
| 6 | **Pre-existing cross-request leak** `SQLAgent._wall_clock_remaining` | Became a parameter; regression test asserts concurrent callers do not observe each other's value. **v202** |
| 7 | **An inference read like a measurement.** LLM-derived conventions and introspected fact reached the prompt in the same voice | `format_derived_age` renders age, silent under a week, escalating past 90 days. No new columns needed — `synced_at` / `indexed_at` already existed and were simply never shown. **v209** |
| 8 | **Two false claims in the docs** | `SYSTEM_ARCHITECTURE.md` on the classifier; `CLAUDE.md`'s `approach`/`route_ms` columns that never existed. Each correction carries its own disproving command |
| 9 | **The project had no retrospective** after four pipeline runs | `docs/superpowers/retro.md` created — 10 standing instructions, 5 earned here |

**Also produced:** a first-pass audit with seven mechanical defect classes swept
repository-wide (all clean — recorded so nobody re-runs them), `docs/DOCMAP.md` (the
project had none), and the code graph — built, with its limits recorded rather than
oversold.

---

## Part 2 — What was NOT solved, honestly

| # | Item | Status |
|---|---|---|
| A | **The timeout fix has never been observed working.** Production has had zero chat traffic since 2026-08-07 | **Cannot be closed by waiting.** Pre-launch, this will not resolve itself — see the re-plan |
| B | **Embeddings are 384-d, not the configured 768-d; the reranker is a no-op** (`config.py:568` still says `reranker_enabled: bool = True`) | Decision taken: **B now, A later** — execute below |
| C | **A flake fails the deploy gate at random** under machine contention | Decision taken: **fix properly** |
| D | **52 `except → pass` blocks untriaged** | Open. Bit this very run: a `TypeError` in a prompt helper was swallowed and silently emptied the critical-warnings block |
| E | **`db-esim` health probe fails every 5 min** | **Re-diagnosed today**: `via_ssh = t`, `ssh_host = 64.188.10.62`. `127.0.0.1` is the *tunnel endpoint* and is correct. The defect is that the tunnel does not re-establish |
| F | Merkle-tree change detection; provenance for `db_index` (the other half of KL-1) | Open, specified |
| G | Not audited at all: frontend, migration reversibility, N+1 / query plans, rate-limit edges, dependency CVEs, analytics collector error paths | Open |

---

## Part 3 — The four decisions, answered

1. **Stage — pre-launch, no users.** Consequence: anything justified by "users are hitting
   this" loses its rank; anything that makes the product *correct before anyone arrives*
   gains it. Notably **K7 (worker OOM) and K14 (verify in prod) drop**, and **AUD-4 (the
   deploy-gate flake) rises**, because pre-launch means many deploys and a gate that fails
   at random taxes every one of them.
2. **Embeddings — B now, A later.** Free, removes a false claim today.
3. **Flake — fix properly.** Reproduce under contention first; the previous fix was
   validated against a lighter suite than the one that broke it.
4. **`db-esim` — identified.** Correctly configured through a tunnel; the bug is tunnel
   re-establishment, not the host value. Ledger row K9 is rewritten accordingly.

---

## Part 4 — Re-planned backlog, ranked for a pre-launch product

The ordering principle changes from *damage-if-ignored-in-production* to **what makes
the first real user's first question correct**, plus what stops slowing every deploy.

| # | Item | Why here, now | Size |
|---|---|---|---|
| **1** | **AUD-5 / option B — make the retrieval defaults honest.** `reranker_enabled` → `False`, document `CHROMA_EMBEDDING_MODEL` as requiring the optional extra, drop the "default on" claim from `CLAUDE.md` | Free, decided, and it removes a documented lie *before* anyone builds on it. Also the precondition for judging option A honestly later | S |
| **2** | **AUD-4 — fix the deploy-gate flake** | Pre-launch means frequent deploys. A gate that fails at random taxes each one, and the failure mode is silent: the wrong decision looks like the right one | M |
| **3** | **Exercise the timeout fix deliberately** (replaces K14's "wait for traffic") | With no users, waiting never verifies it. Stand up a deliberately stalled database in a test and drive the real path, or point a scratch connection at one. Otherwise this ships unverified forever | M |
| **4** | **KL-1 second half — provenance for `db_index`** (`business_description`, `query_hints`, `data_patterns`) | The first half shipped for `code_db_sync`. The same fields on the DB side are still indistinguishable from fact, and a pre-launch index will be months old by launch | S |
| **5** | **AUD-2 — triage the 52 swallowed exceptions**, ratchet the count | Promoted from #8: it already caused a silent defect *in this run*, and pre-launch is exactly when a hidden failure has no user to report it | M |
| **6** | **K9 — SSH tunnel does not re-establish** (`db-esim` → `64.188.10.62`) | Re-diagnosed today. A source that silently stops answering is worse than one that never worked | M |
| **7** | **KL-2 — Merkle-tree change detection** | Quality-of-life for indexing; no user impact pre-launch | M |
| **8** | **AUD-3 / K11 — finish the singleton state audit** | Two instances found so far, both real, both cross-tenant. The sweep found two more agents holding per-request state; one was benign, one was AUD-6 | S |
| **9** | **K8 — `MCP_ALLOWED_HOSTS` empty** | Hardening; exploitability depends on exposure, which is low pre-launch | S |
| **10** | **AUD-5 / option A — 768-d embeddings + re-index** | Still the largest quality win, still costs dyno memory and a full re-index. **Best done immediately before launch**, so the re-index is not paid twice | L |
| **11** | **K7 — worker OOM** | Demoted: no traffic, and option A will change the memory picture anyway. Re-measure after #10 rather than tuning twice | M |
| **12** | K5 (m0 leftovers), K2 follow-up (reach queries need type inference, not an AST graph) | Small debts | S |

**Demoted deliberately:** K14 as written ("verify on the next real timeout") is not a
task, it is a wish — replaced by #3, which can actually be executed. K7 moves behind the
embedding decision that will change its numbers.

---

## Part 5 — What this run should be measured by

Nine problems solved, two of them cross-tenant leaks of the same shape — *per-request
state on an object that outlives the request*. The first was found by accident when a
change had to cross that boundary; the second by a deliberate sweep the first one
motivated. That sweep is item #8 above and is not finished.

Three of the run's own mistakes were caught and are now standing instructions: a test
that passed against its own planted defect, a branch that was green while missing the
scenario for its own user-facing change, and — three times — an exit code that belonged
to `tail` rather than to `pytest`.
