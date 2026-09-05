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
- **A test that pins the defect as the requirement has now appeared six times** (add
  `test_analytics_only_pipeline_bounces_to_the_flat_loop` to the five already listed). At six
  it stops being an anecdote and becomes a rate: expect roughly one per task, invert it rather
  than delete it, and say in the new docstring what the old assertion claimed.
- **`git stash push --keep-index` leaves the index intact, so the next `git commit` takes
  everything in it.** Used it to separate a report from a code fix and committed both under the
  report's message — the same mixing as 2026-09-01, made this time *while narrating that I was
  avoiding it*. The check is one command and it is not optional: `git show --stat` before every
  push, because the mistake is invisible in `git status`.
- **A watcher's exit condition must be scoped to the identity being watched.** A deploy monitor
  keyed on "a completed `Deploy to Heroku` exists in the last six runs" reported success a
  minute after merge — matching *yesterday's* deploy while CI was still running and the release
  was still v320. Scope on `headSha`. And never read the word `success` without checking what it
  is success **of**: a false green carrying a machine's signature is worse than no check,
  because nobody argues with it.
- **Before writing "there is no channel for X", grep how the sibling does X.** A carry-over row
  claimed a pipeline stage cannot carry parameters because `PlanStage` has no field, and sized
  the fix at M. `input_context` was already a JSON params channel that `process_data` parses.
  Wrong in mechanism and in size, corrected an hour later — a partial read that reaches a ledger
  is a decision somebody else will make on it.
- **The ordering came from the code, not from usage, and that is a method error rather than a
  slip.** 101 findings and twenty PRs were ranked without once asking how many people are on the
  product. The answer — 17 chat messages in 30 days, 1 verified user, 0 analytics connections —
  was one query away the whole time and would have put row 0.4 first on day one. Measure the
  audience before ranking the work.

**Untouched and not mine:** PR #266 (`fix(knowledge): the counting tokenizer truncated its
own count`) has been open since before this pass.

## The measurement that should reorder this whole ledger — 2026-09-03

Taken from production during A1's post-deploy step, every number a query against the
live database (run inside a dyno, so no credential left Heroku):

| | |
|---|---|
| users | **9**, of which **1** has `email_verified` |
| projects | 3 |
| connections | 3, **all `database`** |
| analytics connections | **0** |
| vendor credentials | **0** |
| analytics imports | **0** |
| chat messages, last 30 days | **17** |
| pipeline runs, last 30 days | **4** |

**A1 fixed a real defect with no current production exposure.** Nobody has connected an
analytics source, so nothing could ever have hit the missing pipeline branch. The same is
true of most of this ledger: PRs #262–#281 corrected defects in a product that ~1 person
is using.

That is not wasted work — the defects are real, #267 was a live cross-tenant breach, and
they all had to be fixed before anyone arrives. But **the ordering was derived from the
code, not from usage**, and it shows. My own review (`target-gap-2026-09-03.html`) ranked
A1 as the top blocker of the target. Structurally it is. In users affected, it is zero.

**And the low usage is not a mystery, it is a consequence already on this board.** The
product cannot be bought: `BILLING_ENABLED=true` with zero `STRIPE_*` variables and
`/api/billing/plans` returning `{"plans":[]}` — row **0.4**, the one row blocked on a
person. Every other row competes for an audience that 0.4 gates.

**What this changes.** Rows whose value is proportional to usage — retrieval quality (C1–C3),
vendor breadth (B2–B4), the data graph (A4) — are worth less than the ledger's ordering
implies until 0.4 lands. Rows that are prerequisites for the first real user surviving —
0.4 itself, the tenant-isolation remainder (1.10–1.12), and the honesty gates already
shipped — are worth more. This is a note, not a re-ranking: re-ranking a board on one
operator's behalf without asking is how a plan stops being theirs.

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
| 1.7 | Force `step_limit_reached` when the 216 s cutoff fires | S | done | `orchestrator.py` — the exhausted-budget branch types every cut-off run `step_limit_reached` instead of returning the ordinary type when the partial answer looked plausible. **The frontend was already right and unreachable**: `sealStateFor` implements SCN-122's "a budget-exhausted run seals Unverified even when a query is attached" by keying on that type, and the backend withheld it from exactly the runs where the seal mattered. The validator call stays — it no longer decides the type, but it raises the errors-screen signal. `tests/unit/test_cutoff_is_visible_to_the_reader.py` (4 cases, 1 red before); **no test in the suite had ever exhausted the step budget**, which is how the branch survived. SCN-055 and SCN-122 updated in the same change |
| 1.8 | Freshness failure must downgrade the seal, not certify the answer | S | done | `context_loader.check_staleness` returns `STALENESS_UNKNOWN_TEXT` instead of `None`, log DEBUG→WARNING; shipped with 1.6 — same seam |
| 1.9 | Pass `tracker` at the three `HybridRetriever` sites | S | todo | Re-verified open 2026-09-05: `hybrid_retriever.py:92-93` already accepts `tracker`/`workflow_id`, and `knowledge_agent.py:66`, `context_loader.py:78`, `knowledge_catalog_service.py:99` all omit both. **Same shape as the forgettable-default sweep, on telemetry rather than tenancy** — the sweep missed it because it keyed on ownership params only, and the consequence is that `retrieval_degraded_total` reads as absent rather than broken |
| 1.10 | Scope `semantic_layer` / `data_graph` / `feed` by the connection's own project | S | done | **Three targets; #290 shipped two.** `feed` was left behind and the row recorded nothing, so "partly done" and "not started" read identically — found again from scratch by the 2026-09-05 AST sweep. `insight_feed_agent.py::run_scan` now guards; `tests/unit/services/test_catalog_scope_is_the_connections_project.py` carries **one assertion per named target** (10 cases, 2 red before) |
| 1.11 | Scope data-validation writes | S | done | #291; `data_validation_service.py`, `benchmark_service.py` (`project_id` keyword-only at the end so no positional caller shifts), `tests/unit/services/test_validation_scope_is_the_connections_project.py` |
| 1.12 | MCP JWT must honour `token_version` | S | done | #289; `app/core/identity.py` (stdlib-only leaf both entry points import), `tests/unit/test_revocation_reaches_every_entry_point.py` |

## P2 — core quality · the layer the product is sold on

| # | Task | Size | Status | Evidence |
|---|---|---|---|---|
| 2.1 | Render `Artifact.title`; dedup on `(title, summary)` | S | todo | |
| 2.2 | Feed symbol chunks into the BM25 corpus | M | todo | Re-verified open 2026-09-05 with both sides: `_run_bm25_build` (`pipeline_runner.py:1392`) rebuilds the snapshot **from `KnowledgeDoc` rows**, while `code_symbol_chunker.py:218` writes symbol chunks under `sym:` ids into the **vector store only** — and says so in its own comment, that BM25 docs are "built separately by the bm25_build stage from the same underlying documents". They are not the same documents. **The two legs of the hybrid retriever index different corpora**, so a query naming a function or class — the natural way to ask about code — reaches the lexical leg only through prose. Directly on the stated target: vector search over a repository to find parts of an implementation |
| 2.3 | Emit whole identifiers as BM25 terms | S | done | `tokenize_code` emits the compound beside its parts — `resolve_sync_status` and `getusername` are terms now, not just `resolve`/`sync`/`status`. BM25 ranks by IDF, so the whole identifier is a **rare** term while its parts are common ones: that is the precision the split was spending. Emitted only when it actually splits, or a plain word would have its term frequency doubled. **`_SCHEMA_VERSION` 2 → 3 ships with it** — the snapshot persists its tokenized corpus, so changing the tokenizer without the bump leaves old tokens on disk against new tokens in the query: a silent no-op that looks like the fix landed. `load()` rejects the mismatch; `indexed_sha` and `SchemaRetriever.has_index` both route through it, so the boot reconcile treats every old snapshot as missing and rebuilds from Postgres — **no re-index, no clone, no operator step**. `tests/unit/knowledge/test_whole_identifiers_are_terms.py` (14 cases, 7 red before) |
| 2.4 | Run DataGate before the truncation return; widen hard checks past 21 keywords | M | todo | |
| 2.5 | Wire the real retriever into the CI eval; stop calling the oracle a gate | L | done | #287; `tests/unit/eval/test_real_retriever_eval.py` in the CI gate, slow variant behind the `slow_eval` marker. **The first fixture reproduced the defect it fixes** — it fed the dense stub every labelled id, so killing the BM25 leg left the gate green |
| 2.6 | `to_thread` the schema BM25 load off the request path | S | todo | |
| 2.7 | Decimal in the loss/opportunity detectors | S | done | **The row's premise was the smaller half.** Precision was never the problem — the detectors compare aggregates the database already summed and render through `:,.0f`. `isinstance(val, (int, float))` is **False for `Decimal`**, which is what asyncpg returns for a Postgres `NUMERIC` and what `connectors/mongodb.py:134` converts `Decimal128` into on purpose, so a revenue column contained no numbers at all. The same guard is **True** for `bool`, so a flag averaged as a measurement. Fixed at five sites through one leaf (`app/core/numeric.py`): both detectors, `viz_agent.py:75` (`SELECT count(*)` got the number card, `SELECT sum(revenue)` fell through to prose) and `stage_validator.py:322`, where the business rule *no negative values* never fired on a NUMERIC column **while reporting itself as checked**. `tests/unit/test_money_is_not_invisible.py` (30 cases, 8 red before; the stage-validator case verified red by restoring the old guard, because it was written after the fix). SCN-057 updated |
| 2.8 | Alias-bind `check_required_filters` | M | todo | |
| 2.9 | Pipeline answer gate must fail closed like the flat loop | S | done | `orchestrator.py::_evaluate_pipeline_answer` — a crashed gate returned `None`, which `build_pipeline_response` reads as **accept**, while the flat loop's `:3410` consulted `answer_validator_fail_closed` and downgraded. One question, two safety postures, and **only the crashing case differed**, which is why no test compared them. **The fail-open was documented** — "to avoid blocking a successful pipeline" — and the fear does not match the mechanism: any non-accept directive maps to `step_limit_reached`, which preserves the answer text and adds the CTA. Nothing was blocked, so the fail-open bought nothing. Returns `warn`, not `block`: parity is about labelling honestly. `tests/unit/test_pipeline_gate_fails_the_same_way.py` (5 cases, 1 red before). SCN-055 updated |
| 2.10 | Prefix-match on delete; symbol chunks are never pruned | M | todo | Re-verified open 2026-09-05, and the mechanism is sharper than the title: it is **two metadata keys for one concept**, not a missing prefix match. `chunker.py:98` gives a prose chunk `source_path`; `code_symbol_chunker.py:87-94` gives a symbol chunk `path` (`REQUIRED_CHUNK_METADATA_KEYS` does not contain `source_path` at all). Both `delete_by_source_path` implementations — `vector_store.py:295` and `pgvector_store.py:283` — filter on `metadata.source_path`, so a re-index replaces a file's prose chunks and its symbol chunks **accumulate forever**. The store ends up holding symbols for code that no longer exists, and dense retrieval returns them: the agent can cite a function deleted months ago. Pairs with 2.2 and 2.3 — all three are the symbol-chunk seam and should ship together |
| 2.11 | Mongo nullability and FKs; ClickHouse primary keys | M | todo | |
| 2.12 | SQLite dialect hints — the demo path has none | S | todo | |
| 2.13 | A test that skips when the subsystem it guards is broken | S | done | `tests/integration/test_demo_routes.py` guarded a tenancy invariant and called `pytest.skip` on a non-200 from `/api/demo/setup` — disarming itself exactly when the demo path had failed. Now asserts. The `import uuid` went with it: it existed only to feed an `assert uuid.UUID` keeping the import used "if the skip fires" |
| 2.14 | Bind telemetry calls statically — a wrong call under a broad `except` is invisible forever | S | done | `tests/unit/test_fire_and_forget_calls_bind.py`, 156 sites bound. Watched fail against the planted original (`result_validation.py:174`, `.inc` → `.increment`). Receivers resolved only where unambiguous: a first pass keyed on bare `tracker`/`metrics` and all three hits were false |
| 2.15 | One answer to "is this a number?" — 23 guards remain in five variants | M | todo | Measured 2026-09-05 after 2.7: `isinstance(x, (int, float))` and its relatives appear **23** more times across `app/`, in five mutually inconsistent forms, of which exactly one is fully correct (`data_gate.py:448`). **Not all are defects and this row must not pretend otherwise** — `llm/router.py:30` reads config, `ga4/adapter.py:119` reads vendor JSON where `Decimal` never occurs, `chart.py:178` has a separate `Decimal` branch two lines below, and `sql_result_reconciliation.py:52` falls through to a string parse that handles it. Each remaining site needs its own reading; the candidates on the DB-value path are `anomaly_intelligence` (4), `data_sanity_checker` (4), `insight_generator` (2), `semantic_layer.py:385`, `data_gate.py:118` (bool) and `chart.py:86`/`:202` (bool). The leaf to route them through now exists |
| 2.16 | One definition of what a BM25 corpus contains | S | done | `pipeline_runner._run_bm25_build` (worker) and `ops/bm25_local_reconcile._build_one` (web) each held their own `KnowledgeDoc -> chunk_document -> (id, text, meta)` loop. Neither was wrong; the risk is directional — a change reaching one and not the other makes the **reader's** corpus differ from the **writer's**, across two Heroku process types with separate disks, and the symptom is retrieval behaving differently depending on which process last wrote the snapshot. Extracted to `app/knowledge/bm25_corpus.py`, duck-typed so it needs no ORM. Prerequisite for 2.2, which is about to change that definition. `tests/unit/knowledge/test_bm25_corpus_has_one_definition.py` (8 cases, 3 red before) |

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
| 0.6 | `estimated_cost_usd` is NULL on all 6 771 production rows: `estimate_cost` reads `app.api.routes.models._cache`, an in-process cache of the `/api/models` HTTP response, which the worker (serving no HTTP) never populates. The operator has no cost figure for any request ever made. | **closed 2026-09-05.** #285 moved the price fetch into `app/services/model_pricing_service.py`, so the worker no longer reads a cache only the web process holds, and `TraceMeta` carries `cost_usd` beside a `price_source` — a figure without its provenance cannot be audited |
| 0.5 | The migration docstring says "no code path could ever set the column True". True of the code; production shows **2 accounts already `true` while unverified**, so someone granted them by hand through the database. The backfill only touched verified users, so it is unaffected — but read the claim as "no path in code", not "never by anyone". | recorded; no action |
| 1.3 | A retention **setting** — letting an operator switch off storing the result table with a message — is the other half of the audit's suggestion. The pages are now true without it; a customer who wants nothing stored still has no switch. | backlog — product decision, needs UX |
| 1.4 | An **upgrade** (base → scale) does not raise the included grant until the next `subscription_cycle` invoice: `provision` returns the existing key before touching `included_grant_usd`, and a proration invoice is deliberately excluded from `_renew_credit`. The customer pays the higher price and keeps the lower allowance for the rest of that month. | backlog — needs a deliberate decision, since granting immediately also double-grants a month already partly consumed |
| post-deploy 0.1 | `HEROKU_SLUG_COMMIT` is unset on `checkmydata-api`, so Sentry's `release` is `None` in production and no stack trace names the commit that caused it. `CLAUDE.md` already records the requirement (`heroku labs:enable runtime-dyno-metadata`); nobody ran it. One command, and it restarts the dynos. | backlog — ops, needs its own moment |
| audit 2026-09-05 | CODEIDX-C20 (Louvain over-merge threshold) and C21 (cluster staleness on re-index) existed as two **empty** `@pytest.mark.skip` placeholders in `test_w2_low_batch.py` — no body, so unskipping them yields a vacuous pass, and meanwhile they counted toward the suite total. Deleted; the behaviours remain unverified and now say so. | backlog — `clustering_enabled` is off by default, so neither is exercised; raise with the flag |
| 0.1 | A `;` inside a string literal still trips the read-only multi-statement refusal (`SELECT * FROM t WHERE name = 'a;b'` is refused). Pre-existing, unchanged by this fix, and a false refusal rather than a false pass. | backlog — needs literal-aware `;` detection, which is a behaviour change to read-only mode |

## Track O — the orchestrator reshape (Ш0 … Ш4)

Opened 2026-09-04 by `docs/reports/orchestrator-reshape-2026-09-04.html`, after the
operator proposed rebuilding the orchestrator from scratch on a TUI coding agent. Both
halves of that were answered from measurement: PI is a layer inversion (it is the
`local-runner` **provider** shape by Fabric's own decision tree), and the Tool Runner is
rejected because production's workhorse model is `openai/gpt-4o` — 6630 calls of 7662,
all through OpenRouter. The route chosen was **reshape, not rebuild**.

| # | Task | Size | Status | Evidence |
|---|---|---|---|---|
| Ш0a | The trace records the routing and the failure kind | M | done | `TraceMeta` required by `finalize_trace`; `app/core/failure_kind.py` defines the four values once; 27 tests, three inverted; #283 |
| Ш0b.1 | Replanning is observable | S | done | `orchestrator:replan` span with the attempt and the failed stage; #285 |
| Ш0b.2 | Cost is actually computed | M | done | `app/services/model_pricing_service.py`; the route now consumes it; #285 |
| Ш0b.3 | The executed plan outlives the resume buffer | S | in review | `plan_json` on `RequestTrace`, migration `d4e5f6a7b8c9`; TTL deliberately unchanged; #286 |
| Ш1 | An eval that runs the real retriever instead of scoring an oracle | L | **next** | folds in P2 row 2.5 — the current gate handed the oracle the answer key, which is why both critical retrieval defects passed CI green |
| Ш2 | One loop: planning becomes a tool, the second execution path goes | L | todo | 14% of requests take Path B; its unique capability (checkpoint) fired **10 times** in the whole history; DataGate, which lives only there, has 16 observations against SQL validation's 5148 |
| Ш3 | One cross-item checker before convergence, six-item contract, four of them code | M | todo | synthesis takes edges straight from the stages, so the diamond trusts its inputs because they arrived |
| Ш4 | The tool layer rebuilt deliberately: strict schemas, closed enums, declared effects, a completion test each | L | todo | the half of the operator's request that was right in full; also the entry to Fabric's declaration gate |

### What Ш0 measured that the audit had not

| | |
|---|---|
| `route` / `complexity` in `request_traces` | `"unknown"` in **222 of 222** |
| `failure_kind` | NULL in **all 56** failed traces and **all 50** query failures |
| Spans matching `replan` | **0** of 48 distinct names |
| `estimated_cost_usd` | NULL on **all 7 664** `token_usage` rows and all 222 traces, every month since April |
| `pipeline_runs` rows holding a plan | **0** — swept at start-up after 7 days, the last four by this session's own deploy |

**ORCH-A03 was not the culprit**, and `CLAUDE.md` needed a correction rather than a
retraction: it does write the router's signals into `context.extra` for the in-memory
collector, but `replace(context, …)` returns a copy, so the caller holding the original
never saw them. The counter was right and the row beside it was empty.

### Carry-over from Ш0

| Finding | Homed |
|---|---|
| An `AgentResponse.error` string is classified coarsely as `fatal` at three trace sites. Nothing today reads that string, and the alternative was the NULL the column already had — but `transient` and `configuration` failures are now indistinguishable from defects on the flat loop. | backlog — needs the error classifier the SQL path already has |
| A pre-existing invalid `# noqa` at `test_suppression_debt_ratchet.py:240` (warning, not error). Untouched deliberately across two runs now. | backlog — trivial |
| The npm audit gate could not tell a registry 503 from a finding, and a red build on a step named *Audit dependencies* reads as "we introduced a vulnerability". Fixed in #284; recorded here because the **class** recurs — a check whose failure mode is indistinguishable from the thing it checks for. | closed (#284) |

### Working rules this track earned

- **Three blunt-instrument edits in one build, and the third was caught by an assertion on
  the match count before anything was written.** `estimated_cost_usd=` contains
  `cost_usd=` as a substring; an import anchor that also exists indented lands inside a
  function body; a regex that opens two parens must close two. Assert the count, then
  read each site — the count alone is not enough, and the intention is worth nothing.
- **A watcher's exit condition must name what it watches.** A deploy monitor keyed on
  "a completed `Deploy to Heroku` exists in the last six runs" reported success one minute
  after a merge, matching *yesterday's* deploy while CI was still running.
- **Distinguish a test that pins a defect from a test whose subject relocated.** The first
  is now at eight occurrences and is a finding; the second is ordinary maintenance, and
  counting them together inflates the first.
- **A board row naming N targets needs N assertions, or it cannot say what it still
  owes.** Row 1.10 named `semantic_layer`, `data_graph` and `feed`; #290 shipped two and
  the row stayed `todo`, so "partly done" and "not started" looked identical. `feed` was
  found again from scratch a day later by an AST sweep, at full cost. The fix is
  structural, not diligence: the row's test now parametrises over its three targets, so
  the missing one is red rather than absent.
- **A skip decided at runtime disarms the test exactly when its subject is broken.**
  `test_demo_routes.py` guarded a tenancy invariant and skipped on a non-200 from the
  endpoint whose failure it exists to catch. The tell was in the file: an
  `assert uuid.UUID` kept an import used "if the skip fires" — a test written around its
  own escape hatch.
- **Grade a scan's hits before believing them; a flag is a candidate.** The route-scope
  sweep flagged 11, of which one was real, two were the detector failing to see a guard
  that lives in the service, and eight were correctly scoped. The telemetry-binding sweep
  flagged 3, and all three were the receiver-name map calling a dict `metrics` and a
  `GitTracker` `tracker`. Both numbers are honest only because every hit was read.
- **This board conflicts on every parallel branch, and that is a property of the file.**
  Three PRs in one day each edited it; two hit a merge conflict, resolved the same way
  both times — take main's version, re-apply the single row. It is one dense table that
  every change touches, so branching two features off the same commit guarantees it.
  The cheap remedy is order, not tooling: **merge before branching the next row**, and
  where two are already in flight, rebase the later one before opening its PR. Worth
  saying because the conflict looks like a mistake each time and is not — it is the file
  working as designed, and a resolution done from memory rather than from main's version
  is how a closed row silently reverts to `todo`.
- **The suppression ratchet caught its author, and the answer was to delete the
  suppression.** `app/core/numeric.py` shipped a `value == value` NaN test with a PLR0124
  directive beside it — the idiom every existing call site uses — and the full suite went
  red on `test_suppression_debt_has_not_grown`. The suppression was avoidable
  (`math.isnan` accepts int and float, and the Decimal case already had its own branch),
  and raising a ceiling to keep an avoidable one is how a ratchet stops meaning anything.
  Second-order, worth knowing before writing the explanation: **spelling the directive out
  in a comment re-arms it** — ruff parses a mention as a directive and warns that it is
  malformed. The ratchet itself is not fooled; that was fixed earlier in this programme
  and its regression tests hold. The two tools disagree about what a mention is.

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

### A1 post-deploy — 2026-09-03, release v321

Two legs of the verification trio, and the third is named rather than skipped.

| Leg | Verdict |
|---|---|
| Release carries the commit | **PASS** — v321 at 22:00:51 local, `ee87f74`, previous release was v320 from 2026-09-02 |
| Clean boot | **PASS** — `Capability check: 4 configuration claims verified against the runtime, all satisfied`; embedding and encryption reconcile both `unchanged`; `Application startup complete`; BM25 reconcile `ok`; no traceback, no ERROR. `/api/health` 200 `{"status":"ok"}` in 0.82 s |
| Behaviour observed | **IMPOSSIBLE, not skipped** — production holds 0 analytics connections and 0 vendor credentials, so no project exists on which an analytics stage can be planned. `has_analytics` is False everywhere, the stage is never dispatched, and the only observable change is the `Connected sources:` line for the three database projects — which needs a pipeline run, and there were 4 in 30 days. REQ-1 stays **unit-verified, not product-verified** |

**The monitor lied first, and the lie was almost invisible.** The initial deploy watch broke
on the condition "a completed `Deploy to Heroku` run exists in the last six" — and one did,
from 2026-09-02. It reported `Deploy to Heroku: success` about a minute after the merge,
while CI for `ee87f74` was still running and the live release was still v320. Caught only by
comparing `headSha`, not by reading the word *success*. The replacement watch is scoped to
the SHA. Worth keeping because a false green carrying a machine's signature is worse than no
check: nobody argues with it.

### Found by the post-deploy read, and it is somebody else's paragraph

`grep -ic "vector store"` over 1000 lines of production web log returns **0**.

`CLAUDE.md` states that because `VECTOR_STORE_BACKEND` defaults to `auto`, "the answer is
written nowhere an operator can read, so the boot log names it". The line exists
(`vector_store.py:406` auto-resolved / `:410` pinned) but it is emitted when the store is
**constructed**, and construction is lazy: `main.py:761` builds it inside the freshness
reconciler cron loop — which `freshness_reconciler_enabled` leaves **off by default** — or on
first retrieval use. `capability_report.py:79` calls the pure `resolve_backend`, which logs
nothing, and the success line it does print does not name the store.

So on a quiet dyno the signal added to answer "which store is live?" is never emitted at all,
and the documentation asserts an operator-visible fact the operator cannot see. One line in
the capability report fixes it. Filed rather than fixed here: it is a different concern from
A1 and belongs in its own change.

### Carry-over from A1

| Finding | Homed |
|---|---|
| The pipeline **resume** path passes `available_sources=None`: it has no `has_*` probes in scope. A partial list would be worse than none — naming only the database on a project that also has analytics forbids the planner from using it — so the line is omitted rather than guessed. A replan during a resumed pipeline is therefore still unprotected, exactly as every replan was before A1. | backlog — needs the probes threaded into the resume path |
| `query_mcp_source` is absent from `_TEXT_STAGE_TOOLS` (`stage_validator.py:27-30`) although `_run_mcp_stage` returns only a summary and structurally cannot produce rows. A planner-set `min_rows` on an MCP stage fails against a stage that can never satisfy it. Same class as A1, different tool. Analytics is deliberately NOT in that set — it does produce rows. | backlog — new row |
| Pre-existing invalid `# noqa` directive at `tests/unit/docs/test_suppression_debt_ratchet.py:240` (warning, not error). Untouched by A1 and left untouched deliberately: a one-character fix inside the commit that raises that file's ceiling would read as part of the ceiling decision. | backlog — trivial |
| A pipeline stage cannot carry the `report` / `date_from` / `date_to` hints the flat loop's tool accepts. **Corrected an hour after this row was written:** the first version said `PlanStage` has no parameter field and sized the work at M. There IS a channel — `input_context`, which `_parse_process_data_params` (`stage_executor.py:1205-1223`) already parses as a JSON params dict, `params_json` back-compat wrapper included. So the work is S: read it the same way in the analytics stage. The wrinkle that makes it a decision rather than a chore is that `input_context` is documented **to the planner** as natural language ("describes in natural language what data from the previous stages is required", `planner_prompt.py`) while `process_data` overloads it as JSON. Overloading it a second time deepens an existing ambiguity; giving `PlanStage` a real `params` field resolves it and touches plan persistence. | backlog — S if overloaded, M if resolved properly; needs the call |
| DataGate now runs **twice** over analytics rows — `check_query_result` (value ranges only) inside `AnalyticsAgent`, and the full six-check `check` in `_process_one_stage`. Not redundant, different check sets. Recorded so a later reader does not delete one as duplication. | recorded; no action |
| Raised and **resolved by measurement**: a planner-set `min_rows` on an analytics stage that answers from coverage alone with no rows. Every data-shape check in `StageValidator` is guarded by `if qr:` (`stage_validator.py:135-181`), so a `query_result=None` success skips all of them. `_ensure_validation_criteria` also injects only for `query_database`/`process_data`, and only `min_rows = 0`. No defect. | closed — no change needed |
| `except Exception` ceiling 631 → 632, justified in the file. It was **two** on the first pass; the second was removed rather than justified, because both arms classified identically and it only split one log line in half. | closed in this commit |

## P4 — the existing board

The 43 genuinely open rows of `docs/qa-audit/issues.md`, re-ranked by the report.
Worked after P3, or folded into a P0–P3 row where they overlap (the report's
board table names the destination for each).
