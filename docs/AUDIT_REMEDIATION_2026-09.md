# Audit remediation — 2026-09

Live ledger for the plan in `docs/reports/audit-2026-09-01.html` (101 findings,
8 verdicts, one merged order). One row per task, in the report's priority order.
Every row moves to `done` only with a merged PR and green CI behind it.

Status vocabulary: `todo` · `wip` · `done` · `dropped (reason)`.

## P0 — today · live breach, live lie, or the product cannot be bought

| # | Task | Size | Status | Evidence |
|---|---|---|---|---|
| 0.0 | Cross-tenant connection scope in all three chat entry points | S | done | #267, `a568448` |
| 0.1 | SafetyGuard: tokenise before stripping comments | M | done | `app/core/safety.py:52-155`, `tests/unit/test_safety_comment_lexing.py` (27 cases, 12 red before); shipped in #268, deployed `abe6245` → Heroku v309, boot clean (`capability check: 4 claims … all satisfied`), health 200 |
| 0.2 | `hybrid_min_score` below `1/(rrf_k+1)` — retrieval discards single-leg hits | S | done | `config.py:801-810`, `hybrid_retriever.py`, `tests/unit/test_hybrid_rrf_floor.py` (10 cases, 8 red before); measured 0/40 single-leg and 82/1600 pairs surviving the old floor; shipped in #269, deployed `6e23eea` |
| 0.3 | Delete the "present this as a complete answer" sentence | S | done | `response_builder.py:335-356`, `tests/unit/test_synthesis_prompt_honesty.py` (7 cases, 5 red before); `test_prompt_instructs_no_limits_mention` inverted; SCN-055 updated |
| 0.4 | Turn selling on for real — three `STRIPE_PRICE_*` + `STRIPE_SECRET_KEY` + `STRIPE_WEBHOOK_SECRET` | S | **blocked** | Operator decision 2026-09-02: sell for real. **Gated on 0.6** — paid tiers carry `token_limit = 0` (unlimited) and no per-account OpenRouter key, so switching billing on first would make the first scripted trial account a five-figure provider bill. Prod measured: `BILLING_ENABLED=true`, zero `STRIPE_*` vars, `/api/billing/plans` → `{"plans":[]}`. Needs the live credentials from the operator |
| 0.5 | Auto-grant `can_create_projects` on email verification | S | done, deployed | `auth_service.py` (verify_email, find_or_create_google_user), migration `a1c2e3f4b5d6`, `tests/unit/test_project_access_grant.py` (6 cases, 3 red before); SCN-004/016 updated; deployed `93cf357`, prod at `a1c2e3f4b5d6`, backfill touched exactly one row |
| 0.6 | A real token ceiling on base/scale before billing is switched on | S | done | migration `c3d4e5f6a7b8` (base 7.5M/mo + 2.5M/day, scale 22.5M + 7.5M), `tests/unit/test_plan_token_ceilings.py` (9 cases; planting the original `0` turns 4 red); blend $4.0392/M measured from prod `token_usage` + fetched OpenRouter pricing |
| 0.7 | Delete the `PgVectorStore` isinstance assert — the RAG leg is empty in prod | S | todo | |

## P1 — this week · money that leaks, promises that are false

| # | Task | Size | Status | Evidence |
|---|---|---|---|---|
| 1.1 | `charge.refunded` / dispute handling | M | todo | |
| 1.2 | Top-up: roll back on credit failure; mirror payment branch into `verify_checkout` | M | todo | |
| 1.3 | Correct the privacy policy and support FAQ, or add a retention setting | S | todo | |
| 1.4 | Wire `provision()`/`revoke()` into `_sync_subscription` | M | todo | |
| 1.5 | Learning decay: stop exposure resetting the staleness clock | S | todo | |
| 1.6 | Freshness: empty-vector-store signal; stop swallowing checks to "fresh" | S | todo | |
| 1.7 | Force `step_limit_reached` when the 216 s cutoff fires | S | todo | |
| 1.8 | Freshness failure must downgrade the seal, not certify the answer | S | todo | |
| 1.9 | Pass `tracker` at the three `HybridRetriever` sites | S | todo | |
| 1.10 | Scope `semantic_layer` / `data_graph` / `feed` by the connection's own project | S | todo | |
| 1.11 | Scope data-validation writes | S | todo | |
| 1.12 | MCP JWT must honour `token_version` | S | todo | |

## P2 — core quality · the layer the product is sold on

| # | Task | Size | Status | Evidence |
|---|---|---|---|---|
| 2.1 | Render `Artifact.title`; dedup on `(title, summary)` | S | todo | |
| 2.2 | Feed symbol chunks into the BM25 corpus | M | todo | |
| 2.3 | Emit whole identifiers as BM25 terms | S | todo | |
| 2.4 | Run DataGate before the truncation return; widen hard checks past 21 keywords | M | todo | |
| 2.5 | Wire the real retriever into the CI eval; stop calling the oracle a gate | L | todo | |
| 2.6 | `to_thread` the schema BM25 load off the request path | S | todo | |
| 2.7 | Decimal in the loss/opportunity detectors | S | todo | |
| 2.8 | Alias-bind `check_required_filters` | M | todo | |
| 2.9 | Pipeline answer gate must fail closed like the flat loop | S | todo | |
| 2.10 | Prefix-match on delete; symbol chunks are never pruned | M | todo | |
| 2.11 | Mongo nullability and FKs; ClickHouse primary keys | M | todo | |
| 2.12 | SQLite dialect hints — the demo path has none | S | todo | |

## P3 — structure · what lets the same decision be implemented twice

| # | Task | Size | Status | Evidence |
|---|---|---|---|---|
| 3.1 | Move job bodies out of `api/routes/` into services or jobs | M | todo | |
| 3.2 | One `execute_stored_query()` — collapse the five copies | M | todo | |
| 3.3 | Hoist the 867 function-level imports, then add a layer contract | M | todo | |
| 3.4 | Generate `types.ts` from OpenAPI and fail CI on a diff | M | todo | |
| 3.5 | Split `ConnectionSelector` by responsibility | L | todo | |
| 3.6 | Daily-sync heartbeat: match `pipeline_runner`'s fix | S | todo | |
| 3.7 | Extend the silent-degradation ratchet to empty containers | M | todo | |

## Carry-over — found while doing the work, not in the report

| From | Finding | Homed |
|---|---|---|
| 0.1 | `core/sql_parser.py:10-11` strips comments and then string literals with the same quoting-blind regexes. It is **not** a guard — it feeds `extract_tables` for pre-validation and the required-filter guard — so its failure mode is a wrong table list, not an executed statement. Same defect shape, different blast radius. | folded into 2.8 (`Alias-bind check_required_filters`), which already edits that seam |
| 0.6 | `OpenRouterCreditService.provision` has no caller anywhere, so `llm_credit` — the two-pocket dollar ceiling the billing model was designed around (`b48fcfc1524b`) — has never been armed for a single account, and every request runs on one shared operator key. | P1 1.4 (`Wire provision()/revoke() into _sync_subscription`) — now load-bearing for 0.4 |
| 0.6 | `estimated_cost_usd` is NULL on all 6 771 production rows: `estimate_cost` reads `app.api.routes.models._cache`, an in-process cache of the `/api/models` HTTP response, which the worker (serving no HTTP) never populates. The operator has no cost figure for any request ever made. | backlog — new row, not in the audit |
| 0.5 | The migration docstring says "no code path could ever set the column True". True of the code; production shows **2 accounts already `true` while unverified**, so someone granted them by hand through the database. The backfill only touched verified users, so it is unaffected — but read the claim as "no path in code", not "never by anyone". | recorded; no action |
| post-deploy 0.1 | `HEROKU_SLUG_COMMIT` is unset on `checkmydata-api`, so Sentry's `release` is `None` in production and no stack trace names the commit that caused it. `CLAUDE.md` already records the requirement (`heroku labs:enable runtime-dyno-metadata`); nobody ran it. One command, and it restarts the dynos. | backlog — ops, needs its own moment |
| 0.1 | A `;` inside a string literal still trips the read-only multi-statement refusal (`SELECT * FROM t WHERE name = 'a;b'` is refused). Pre-existing, unchanged by this fix, and a false refusal rather than a false pass. | backlog — needs literal-aware `;` detection, which is a behaviour change to read-only mode |

## P4 — the existing board

The 43 genuinely open rows of `docs/qa-audit/issues.md`, re-ranked by the report.
Worked after P3, or folded into a P0–P3 row where they overlap (the report's
board table names the destination for each).
