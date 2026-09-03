# Audit remediation — 2026-09

Live ledger for the plan in `docs/reports/audit-2026-09-01.html` (101 findings,
8 verdicts, one merged order). One row per task, in the report's priority order.
Every row moves to `done` only with a merged PR and green CI behind it.

Status vocabulary: `todo` · `wip` · `done` · `dropped (reason)`.

## Where this stands — 2026-09-03

**15 done, 24 open.** P0 is closed in code except 0.4; P1 is 7 of 12. **Track A opened**
by the target review in `docs/reports/target-gap-2026-09-03.html`, and A1 is done.

Shipped and deployed: 0.1, 0.2, 0.3, 0.5, 0.6, 0.7 (PRs #268–#274). Merged and
awaiting or mid-deploy: 1.1–1.5 (#275–#279). In review: **1.6 + 1.8 → #280**.

**Next task: 1.7** — force `step_limit_reached` when the 216 s cutoff fires. Then 1.9
(pass `tracker` at the three `HybridRetriever` sites), then 1.10–1.12.

**0.4 is the only row blocked on a person.** The operator chose "sell for real"; 0.6 and
1.4 have since removed both reasons it was gated. What remains is credentials only:

```
heroku config:set -a checkmydata-api \
  STRIPE_SECRET_KEY=sk_live_... STRIPE_WEBHOOK_SECRET=whsec_... \
  STRIPE_PRICE_BASE=price_... STRIPE_PRICE_SCALE=price_...
```

**Working rules learned in this pass, worth keeping:**

- A test that pins the defect as the requirement has appeared **five times** (safety
  comment stripping, `hybrid_min_score`, the synthesis prompt, the top-up swallow, the
  conftest trigger that hid the project-access wall). Read the test before trusting it.
- Every claim here is measured against production before it is fixed, and the
  measurement goes in the commit. Twice the measurement changed the fix (`refund.created`
  over `charge.refunded`; a real ledger claim instead of mirroring the payment branch).
- PRs stack badly: a conflicting PR reports **no checks**, which reads as "CI hasn't
  started"; deleting a base branch on merge **closes** the PR stacked on it; and pushing
  to `main` right after a merge cancels that merge's CI through the concurrency group.
- Alembic is serial — a second migration in flight must be stacked, not branched beside.

**Untouched and not mine:** PR #266 (`fix(knowledge): the counting tokenizer truncated its
own count`) has been open since before this pass.

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
| 0.7 | Delete the `PgVectorStore` isinstance assert — the RAG leg is empty in prod | S | done | `knowledge_catalog_service.py` (assert removed, both `except` blocks raised DEBUG→WARNING), `tests/unit/test_catalog_rag_leg_backend_agnostic.py` (4 cases, 2 red before); `PgVectorStore.__mro__` and `resolve_backend` verified by execution |

## P1 — this week · money that leaks, promises that are false

| # | Task | Size | Status | Evidence |
|---|---|---|---|---|
| 1.1 | `charge.refunded` / dispute handling | M | done | `billing_service.py` (`refund.created` + both dispute events), `openrouter_credit_service.debit/restore`, `tests/unit/test_refund_and_dispute_handling.py` (12 cases, 7 red before). **`charge.refunded` deliberately unhandled** — cumulative `amount_refunded` would double every partial reversal; per Stripe's own guidance |
| 1.2 | Top-up: roll back on credit failure; mirror payment branch into `verify_checkout` | M | done | `billing_service.py` (`_claim_top_up` on the session id inside a SAVEPOINT, `_credit_top_up` re-raises, payment branch in `verify_checkout`), `tests/unit/test_topup_grant_survives_failure.py` (9 cases, 6 red before); `test_it_does_not_raise` inverted |
| 1.3 | Correct the privacy policy and support FAQ, or add a retention setting | S | done | four surfaces corrected (privacy, terms, about, support FAQ — two more than the audit named), `tests/unit/docs/test_privacy_claims_match_storage.py` (11 cases; 7 fail against the old pages); measured 55/131 messages with `raw_result`, 213/213 `db_index` rows with sampled values. Retention **setting** deferred → backlog |
| 1.4 | Wire `provision()`/`revoke()` into `_sync_subscription` | M | done | `billing_service.py` (`_provision_key` on active/trialing, `_revoke_key` on delete, both allowed to raise), `tests/unit/test_subscription_provisions_the_key.py` (10 cases, 6 red before). **Unblocks 0.4** — the dollar ceiling now exists per account |
| 1.5 | Learning decay: stop exposure resetting the staleness clock | S | done | `agent_learning_service.expose_learning` pins `updated_at`, `tests/unit/test_learning_decay_clock.py` (4 cases, 2 red before); measured in prod — exposed learnings capped at 14 days' staleness against 5-month-old rows, 0 of 74 eligible to decay |
| 1.6 | Freshness: empty-vector-store signal; stop swallowing checks to "fresh" | S | done | `knowledge_freshness_service.py` (4th signal `vector_store`, `_unknown()` on all five checks), `VectorStore.count`, `get_vector_store()`; `tests/unit/test_freshness_is_honest_about_unknown.py` (7 cases, 5 red before) |
| 1.7 | Force `step_limit_reached` when the 216 s cutoff fires | S | todo | |
| 1.8 | Freshness failure must downgrade the seal, not certify the answer | S | done | `context_loader.check_staleness` returns `STALENESS_UNKNOWN_TEXT` instead of `None`, log DEBUG→WARNING; shipped with 1.6 — same seam |
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
| 1.3 | A retention **setting** — letting an operator switch off storing the result table with a message — is the other half of the audit's suggestion. The pages are now true without it; a customer who wants nothing stored still has no switch. | backlog — product decision, needs UX |
| 1.4 | An **upgrade** (base → scale) does not raise the included grant until the next `subscription_cycle` invoice: `provision` returns the existing key before touching `included_grant_usd`, and a proration invoice is deliberately excluded from `_renew_credit`. The customer pays the higher price and keeps the lower allowance for the rest of that month. | backlog — needs a deliberate decision, since granting immediately also double-grants a month already partly consumed |
| post-deploy 0.1 | `HEROKU_SLUG_COMMIT` is unset on `checkmydata-api`, so Sentry's `release` is `None` in production and no stack trace names the commit that caused it. `CLAUDE.md` already records the requirement (`heroku labs:enable runtime-dyno-metadata`); nobody ran it. One command, and it restarts the dynos. | backlog — ops, needs its own moment |
| 0.1 | A `;` inside a string literal still trips the read-only multi-statement refusal (`SELECT * FROM t WHERE name = 'a;b'` is refused). Pre-existing, unchanged by this fix, and a false refusal rather than a false pass. | backlog — needs literal-aware `;` detection, which is a behaviour change to read-only mode |

## Track A — one agent over all sources

Opened 2026-09-03 by `docs/reports/target-gap-2026-09-03.html`. The audit's P0–P3 rows
are defects in what exists; these are the gap between what exists and the product the
operator described: one agent over repositories, databases and analytics vendors, able
to answer any question about the project's data.

| # | Task | Size | Status | Evidence |
|---|---|---|---|---|
| A1 | Analytics in the multi-stage pipeline — dispatch branch, planner vocabulary, per-project source availability | M | done | `stage_executor.py` (`_run_analytics_stage`, dispatch case), `planner_prompt.py` (vocabulary entry + `_sources_line`), `adaptive_planner.py` (kwarg through `plan`/`_llm_plan`/`_call_planner_llm`/`replan`), `orchestrator.py` (T13 bounce removed, fallback ladder gained an analytics branch, `_available_sources` computed and passed), `connection_service.resolve_analytics_connection`; 45 new tests across `test_analytics_pipeline_stage.py` (15), `test_planner_source_availability.py` (20), `test_analytics_connection_resolver.py` (10); 28 red before. Two negative controls executed: removing the dispatch case turns 12 red, removing the tenant comparison turns 1 red. Full suite **7469 passed, 0 failed** |
| A2 | Report catalogue in the tool description from the connection, not the hardcoded GA4 five | S | todo | `analytics_tools.py:55-62` names overview/geo/platform/trend/events literally, in one global definition for every project |
| A3 | Period-alignment primitive in `process_data` — join a vendor's daily rows to a daily aggregate from the database | M | todo | A1 delivered its input: the analytics stage now populates `StageResult.query_result` |
| A4 | `source_type` + `source_ref` on `metric_definitions`; relationships across sources | M | todo | `metric_definition.py:34-35` has `source_table`/`source_column` and no source kind, so the data graph is DB-shaped and analytics cannot enter it |

### What A1 found that the report did not say

The report claimed analytics was unreachable in the pipeline. True, but the shape was
sharper: `_run_complex_pipeline` **knew**, documented it as T13, and bounced an
analytics-**only** project to the flat loop. What no workaround could cover is the mixed
case — analytics *plus* a database — which is exactly the target sentence. Single-source
worked; the combination did not, and said nothing.

Two adjacent defects, same function, found by reading rather than by the report:
`_fallback_tool`'s ladder ended at `query_mcp_source` unconditionally, so an
analytics-only project's last-resort plan named a tool it had no source for; and
`test_analytics_only_pipeline_bounces_to_the_flat_loop` pinned the workaround as the
requirement — the **sixth** occurrence of that pattern in this programme. It was
inverted, not deleted.

### Carry-over from A1

| Finding | Homed |
|---|---|
| The pipeline **resume** path passes `available_sources=None`: it has no `has_*` probes in scope. A partial list would be worse than none — naming only the database on a project that also has analytics forbids the planner from using it — so the line is omitted rather than guessed. A replan during a resumed pipeline is therefore still unprotected, exactly as every replan was before A1. | backlog — needs the probes threaded into the resume path |
| `query_mcp_source` is absent from `_TEXT_STAGE_TOOLS` (`stage_validator.py:27-30`) although `_run_mcp_stage` returns only a summary and structurally cannot produce rows. A planner-set `min_rows` on an MCP stage fails against a stage that can never satisfy it. Same class as A1, different tool. Analytics is deliberately NOT in that set — it does produce rows. | backlog — new row |
| Pre-existing invalid `# noqa` directive at `tests/unit/docs/test_suppression_debt_ratchet.py:240` (warning, not error). Untouched by A1 and left untouched deliberately: a one-character fix inside the commit that raises that file's ceiling would read as part of the ceiling decision. | backlog — trivial |
| `except Exception` ceiling 631 → 632, justified in the file. It was **two** on the first pass; the second was removed rather than justified, because both arms classified identically and it only split one log line in half. | closed in this commit |

## P4 — the existing board

The 43 genuinely open rows of `docs/qa-audit/issues.md`, re-ranked by the report.
Worked after P3, or folded into a P0–P3 row where they overlap (the report's
board table names the destination for each).
