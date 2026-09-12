# Product review and backlog — 2026-09-09

A full walk of what is actually built — every feature, the collection paths, the storage, the
analyzer, and how each is represented in the UX — with the problem spots per layer and a
prioritised backlog. This is the **map**; the **evidence** lives in
`docs/audits/2026-09-09-full-system-audit.md` (164 findings, every one carrying an independent
verification verdict). A finding id in brackets (`BILL-01`) points there; nothing is restated
that the audit already proves.

Status vocabulary, used consistently below:

- **working** — built, wired, exercised in production.
- **partial** — built and wired, but a named slice is missing or wrong.
- **built-but-dead** — the code exists end to end and delivers nothing (no caller, no UI entry,
  or a threshold that filters everything).
- **reserved** — deliberately not built yet, refusal in place.

---

## A. Data sources & collection

| What | Status | Notes |
|---|---|---|
| PostgreSQL / MySQL / ClickHouse / MongoDB connectors | working | layered read-only enforcement (engine session + SafetyGuard) on the native path |
| SQLite connector | working | demo path only, not offered in the UI (by design) |
| SSH tunnels | working | TOFU host keys, escaped exec templates, idempotency-aware reconnect (F-SSH-07) |
| **SSH-exec mode** (query via psql/mysql/clickhouse on a bastion) | **partial → dangerous** | the weakest surface in the product: stdin meta-command RCE [`SQL-01`], no engine-level read-only [`SQL-02`], mid-line truncation reported as untruncated [`SQL-04`], template escaping for the wrong quote context [`SQL-13`], unvalidated custom command template [`SQL-06`] |
| SafetyGuard (read-only SQL gate) | partial | dialect-aware comment stripping is solid, but the allow-list passes server-side file-read/SSRF functions [`SQL-11`] and a quoted-identifier CTE write [`SQL-12`] |
| GA4 collection (adapter → journal → fact tables) | working | pagination, quota reading, error taxonomy, per-period isolation — with honesty gaps: quiet day reads as "vendor truncated" [`ANA-01`], quota page discarded [`ANA-02`], one property's 404 poisons the period forever [`ANA-11`], refetch never deletes revised-away rows [`ANA-12`] |
| App Store / Google Play | reserved | 422 on create until m1/m2 fact tables land — correct refusal |
| Git repositories (clone, index, webhook, poll) | working | webhook uses ONE global secret for any project id [`AUTH-05`]; polling/reconciler flags off by house rule |
| MCP sources (external MCP servers as data sources) | working | stage output not chainable (no `query_result`) — documented, not a defect |
| Manual "Collect now" | **built-but-dead for up to 1 h/day** | shares the day-scoped job id with the cron wave; returns `202 queued` while arq refuses the duplicate [`ANA-10`] |

## B. Storage

| What | Status | Notes |
|---|---|---|
| App data: Supabase Postgres 17 (prod) / SQLite (dev) | working | pooler ceiling measured and boot-validated (`DB_CONNECTION_CEILING=40`) |
| Vectors: pgvector (prod) / Chroma (dev), auto-resolved | working | **but the chunk lifecycle loses vectors**: reused docs never re-embedded after a collection drop [`KNOW-01`], regenerated docs delete the file's symbol chunks [`KNOW-02`], line-shifted symbol chunks orphaned [`KNOW-03`] |
| BM25 snapshots (gzip JSON, per-dyno, boot reconcile) | partial | web dyno's corpus frozen at first read until restart [`RET-06`]; rebuilt per-request in ContextPack [`RET-05`] |
| GA4 fact tables (natural-keyed, `Numeric` money) | working | totals sum rows of properties removed from config [`ANA-05`] |
| Chat history + `raw_result` (≤500 rows/answer) | working | contradicts `vision.md` §8's own text [`BIZ-10`]; retained after account deletion in foreign projects [`BIZ-04`] |
| Schema drift: model vs migrations | **partial** | 81 columns nullable in prod and NOT NULL in tests [`DATA-02`], `audit_logs` invisible to Alembic [`DATA-05`], money as Float [`DATA-06`], zero CHECK constraints with a load-bearing status vocabulary [`DATA-04`], `row_count` 32-bit against 64-bit producers [`DATA-03`] |
| Retention | partial | notifications and schedule-run history never pruned; scheduler loop stores uncapped payloads [`COR-07`] |

## C. Knowledge & indexing (M1–M6)

| What | Status | Notes |
|---|---|---|
| Checkpointed pipeline, resume, heartbeats, orphan sweep | working | hardened 09-08/09; resume of an interrupted **full** rebuild silently continues as incremental [`KNOW-08`] |
| Document generation + T03 content-hash cache | working | −71 % on warm rebuild, measured in production |
| Code graph (ast_parse → graph_build), IMPORTS resolution | working | full-rebuild path lacks the zero-symbol guard the incremental path has — a parser outage wipes the graph [`KNOW-05`]; incremental CALLS resolution sees only changed files [`KNOW-04`] |
| code_symbol_embed | partial | swallows every failure and reports counts from input [`KNOW-07`] |
| Entity extraction | works | `KNOW-06` closed 2026-09-12: an entity whose defining file was re-read and no longer declares it is dropped; everything else is kept, including an entity whose file could not be read |
| Embedding reconcile (fingerprint → auto reindex) | partial | partial enqueue failure still advances the marker [`OPS-07`]; fingerprint carries a setting inert on the prod backend, so a bump buys a 12 000 s rebuild of identical vectors [`RET-08`] |
| Code↔DB sync (declared > inferred, plausibility gates) | working | phantom tables eliminated (measured 0/250); required-filter guard rewritten |
| Clustering (M6) | built-but-off | flag off; its index exists in migrations and not in models [`DATA-11`] |

## D. Retrieval

| What | Status | Notes |
|---|---|---|
| BM25 leg | working | the only leg actually contributing in production |
| **Dense leg** | **built-but-dead** | `chroma_max_distance=0.45` sits below everything the production embedder emits for correct matches — measured 0/11 survivors [`RET-01`]; degradation labelled "cause unknown" while the filter is the known cause [`RET-04`] |
| RRF fusion + rank cutoff | working | both-legs-empty emits no degradation signal at all [`RET-03`] |
| Reranker | built-but-dead | `ml` extra not in the image; README still sells it as default-on [`BIZ-13`] |
| Retrieval eval (Ш1 real-retriever gate) | partial | builds without the distance filter that killed the dense leg [`RET-02`]; nDCG normalises against retrieved-only [`RET-09`]; floors checked only for being in (0,1] [`TEST-07`] |
| Tokenizer window | partial | fallback under-counts code tokens [`RET-07`] |

## E. Analyzer (orchestrator, agents, gates)

| What | Status | Notes |
|---|---|---|
| Unified router → two execution paths | working | fallback overwrites the router's real verdict in metrics/trace [`ORCH-07`] |
| Path A single loop / Path B pipeline, shared deadline | working | zero-row result fails a pipeline stage but only warns in the loop [`ORCH-02`]; failed synthesis reported as complete [`ORCH-08`] |
| Stage executor, LayerChecker, replan | partial | rejected layer's results seed the replan [`ORCH-03`]; `query_analytics_source` dispatchable but absent from `_VALID_TOOLS`, so planner-validated plans can never contain it [`ORCH-01`] |
| DataGate / StageValidator / AnswerQualityGate | partial | StageValidator built without an LLM router in both pipelines — business-rule validation silently off [`ORCH-04`]; resumed pipeline skips the answer gate and freshness warning [`ORCH-06`]; caveat reads only the last query-bearing stage [`ORCH-09`] |
| ValidationLoop (repair, timeout breaker) | partial | connection error re-runs the identical statement with no idempotency check [`ORCH-11`] |
| AnalyticsAgent honesty gates | partial | grounding satisfied by a catalogue read alone — an invented figure ships uncaveated [`ANA-07`] |
| Learning memory (per-connection, decay, gates) | working | **insights** stored per-connection and injected project-wide — an invariant-4 leak [`BIZ-05`] |
| Investigation subsystem (InvestigationAgent, routes, confirm-fix) | **built-but-dead** | complete backend; the only UI entry (`WrongDataModal`) is never imported — thumbs-down sends a canned English prompt instead [`BIZ-06`] |
| Multilingual answers | partial | every static degradation path (step limit, timeout, stage failure, context overflow) ships hardcoded English exactly when comprehension matters most [`COR-05`] |
| Per-workflow caches on the singleton | partial | sweep keyed on a map only `process_data` writes — SQL results of other workflows leak until restart [`ORCH-05`] |

## F. Sprint-1 "Chief Data Brain" modules

All ten shipped per `BACKLOG.md`; audit coverage of them:

| Module | Status | Notes |
|---|---|---|
| Data Graph / Insight Memory / Trust Layer | working | insight scoping leak is `BIZ-05`; models carry the DATA-02 nullable drift heavily (`insight_records` 13 cols, `trust_scores` 9, `metric_definitions` 13) |
| Insight Feed | partial | multi-connection scan reports `connections_scanned` from input [`API-12`] |
| Anomaly / Opportunity / Loss detectors, Action engine | working | not contradicted by the audit; blast radius bounded by insight-memory issues above |
| Reconciliation engine | working | permission gates verified sound (gap-hunter pass) |
| Semantic layer auto-build | working | cross-project hole already fixed (`require_in_project`) |
| Query-less exploration, Temporal engine | working | gates and bounds verified sound |

## G. Product surfaces & UX

| Surface | Status | Notes |
|---|---|---|
| Chat (REST / SSE / WS), reasoning panel, charts | working | stream lock leaks on limiter 429 → session wedged 409 up to 1 h [`API-01`]; per-token smooth scroll [`FE-09`]; timeout misclassified as network — twice, same abort-reason bug [`FE-01`, `FE-08`]; late poll drags the user back to an old session [`FE-02`]; clarification question unanswerable after reload [`FE-05`] |
| Session rotation near context limit | partial | SSE transport only; REST/WS degrade into overflow recovery; the "context utilisation" meter is structurally a constant [`COR-04`] |
| Sidebar rail: Setup / Workspace / Operations + "Needs You" | working | reorganised 09-07/08 (SCN-149/150/151), panels have destinations, mechanical tests pin it |
| Dashboards + shared viewer | working | viewer is membership-gated (no public tokens — verified); failed load renders "Dashboard not found" [`FE-04`] |
| Notes / saved queries | partial | fetch failure indistinguishable from empty [`FE-07`]; **viewer role can execute DML on writable connections** [`COR-06`] |
| Schedules & alerts | **partial** | cron evaluated in UTC against wall-clock UI labels [`COR-01`]; alert conditions evaluated on a truncated head — `pct_change` compares rows 499↔500 forever [`COR-03`]; `notification_channels` accepted, stored, never read — alerts are bell-icon-only [`COR-02`] |
| Notifications | partial | no prune, no delete route [`COR-07`] |
| Feed / insights / knowledge panels | working | routed via `?panel=`, tested |
| Onboarding wizard, readiness gate | working | readiness cache has no TTL — `checkedAt` written, never read [`FE-11`] |
| Billing UI (`/pricing`, portal) | **partial** | FAQ still sells retired Free/Pro tiers [`BIZ-09`]; "Most popular" badge keyed to retired `pro` id never renders |
| Marketing/legal pages | **wrong in places** | Privacy Policy denies the row→LLM flow [`BIZ-03`], omits Stripe/Sentry [`BIZ-11`], describes SQLite/localStorage architecture [`BIZ-15`] |
| MCP server (per-user tokens, ASGI mount) | working | double concurrency-slot acquire [`AUTH-04`]; raw connector exception to the client [`AUTH-06`]; `execute_raw_query` leaves zero audit trail [`BIZ-07`] |
| UX scenario base | partial | 153 scenarios: 141 implemented, 12 draft; flows/screens layers cover data-onboarding scope only; SCR-01 coverage dangles [`TEST-08`]; SCN-052 stale + wrong line ranges [`BIZ-14`]; 166 file:line citations unchecked [`TEST-14`] |
| PWA | absent | manifest + icons only, no service worker — `CLAUDE.md` "PWA-capable" overstates |

## H. Commercial layer

| What | Status | Notes |
|---|---|---|
| Four paid tiers, catalogue reconcile, plan grants | working | reconcile **erases** the migration-written token ceilings on every boot [`DATA-01`] |
| **Spend containment** | **built-but-dead, twice** | per-account OpenRouter key never presented to the provider [`BILL-01`/`BIZ-01`]; its ceiling arithmetic forgives in-period spend on every top-up/refund [`BILL-02`]; team/enterprise credit provisions as $0 [`BIZ-02`]; four routes + learning analyzer spend through `NullUsageSink` [`API-08`, `BILL-10`] |
| Stripe webhooks (idempotency ledger) | partial | failed reversal/renewal committed as processed [`BILL-03`, `BILL-08`]; no ordering guard [`BILL-04`]; duplicate-checkout guard reads a webhook-only field [`BILL-05`]; blocking HTTP on the loop [`BILL-07`] |
| Entitlements (quotas, scheduled-work gate, index-quota warning) | working | shipped 09-07/09; degradation direction deliberate and tested |
| **Seats** | **built-but-dead** | priced, stored, returned, carried in Entitlements — enforced nowhere [`BILL-09`] |
| Usage accounting | partial | zero-total fix landed (T09); the NullUsageSink paths above remain the leak |

## I. Ops & platform

| What | Status | Notes |
|---|---|---|
| Worker (ARQ), crons, reaper, orphan sweep | working | hardened 09-08/09; orphan close lacks `finished_at` + catalog entry [`OPS-16`]; requeue budget counts its own reap [`OPS-10`] |
| Cron waves (daily sync, analytics) | partial | dispatch counted from input — a failed enqueue silently skips a project's day [`OPS-17`]; 24 h maintenance cron unreachable on a platform that cycles dynos daily — billing reconcile, telemetry retention, journal prune never run [`OPS-04`] |
| Observability | **partial** | worker never initialises Sentry [`OPS-01`]; worker metrics emitted into a process with no metrics endpoint [`OPS-03`]; capability report counts unevaluated claims as passing [`OPS-13`] |
| Task queue | partial | boot-time Redis failure permanently demotes the process to in-process execution [`OPS-15`]; five `202` endpoints + boot sweep ordering [`OPS-05`, `OPS-02`] |
| Rate limiting | **partial** | keyed on `request.client.host`, which behind Heroku's router is one address for everyone [`API-05`]; two incompatible 429 bodies [`API-06`] |
| Deploy | **broken by construction** | release step cannot fail, health check polls the previous release [`TEST-01`]; **migrations run in no channel the container pipeline uses** [`TEST-15`]; worker release unverified [`TEST-16`]; cancel-in-progress can split backend/frontend versions [`TEST-17`]; web+worker race `alembic upgrade head` with one retry between them [`DATA-10`] |

## J. Quality gates

| What | Status | Notes |
|---|---|---|
| 8 965 tests, 82 % coverage, gates | working | with holes: `DEPRECATED` comment excludes a function from coverage [`TEST-03`]; the gate-guard matches a comment [`TEST-04`]; 72 % still quoted in two contributor-facing docs [`TEST-05`] |
| Smoke suite | built-but-dead in CI | claims "runs at boot / in CI", runs in neither [`TEST-06`] |
| Guards asserting literal source strings | partial | three refactor-fragile greps [`TEST-09`]; contrast test re-implements the alphas it tests [`TEST-10`]; leftover skipifs convert deletions into skips [`TEST-11`] |
| UX scenario tooling | partial | suffixed ids miscredited [`TEST-12`]; line anchors unchecked [`TEST-14`]; screens/flows layer unguarded [`TEST-08`] |

---

## The built-but-dead list, in one place

Code that exists end to end and delivers nothing. Each is either a wiring task or a deletion
decision — carrying them as "features" misleads every reader of the codebase:

1. Per-account OpenRouter credit (provision/renew/top-up/revoke) — never used [`BILL-01`]
2. Paid-tier token ceilings — written by a migration, erased by the reconcile [`DATA-01`]
3. Dense retrieval leg — filtered to zero by its own threshold [`RET-01`]
4. Investigation subsystem UI (`WrongDataModal` + 3 routes + confirm-fix learning) [`BIZ-06`]
5. `send_sample_data_to_llm` — no UI, gates the smaller half [`BIZ-12`]
6. `seats` — priced and unenforced [`BILL-09`]
7. `notification_channels` — accepted, stored, never read [`COR-02`]
8. Reranker — flag + code with no dependency in the image [`BIZ-13`]
9. Smoke suite in CI [`TEST-06`]
10. `X-Total-Count`/`X-Result-Capped` — stripped by CORS before any browser sees them [`API-10`]
11. Context-utilisation meter — reports a constant [`COR-04`]
12. Readiness `checkedAt` — written, never read [`FE-11`]
13. Worker `MetricsCollector` counters — emitted into a process with no endpoint [`OPS-03`]
14. Maintenance-cron members (billing reconcile, retention sweeps) — gated behind uptime the platform never grants [`OPS-04`]
15. `ix_code_graph_symbols_cluster` — exists only where tests can't see it [`DATA-11`]

---

# Backlog

Ordered by what unhandled failure costs. Items reference audit findings; each finding entry
carries its own fix direction, so tasks here name the workstream, not the patch. Effort:
S (< 1 day), M (1–3 days), L (workstream).

## P0 — money, security, data integrity

| # | Task | Refs | Effort |
|---|---|---|---|
| 1 | ✅ **DONE 2026-09-11** (#334, prod v370) — **Spend containment, one layer that actually binds**: fix the two-writer ceiling erasure; decide per-account-key vs token ceilings and wire the chosen one; fix `_limit_for` watermark arithmetic; add team/enterprise to included credit; bind `DbUsageSink` + budget gate on the four bare routers and the learning analyzer | BILL-01/02, BIZ-01/02, DATA-01, API-08, BILL-10 | L |
| 2 | ✅ **DONE 2026-09-11** (#335, prod v372) — **SSH-exec hardening**: SQL via argument not stdin; engine-level read-only in templates; deny file-read/SSRF functions in read-only; fix CTE-write bypass; context-correct escaping; validate custom templates; truncation honesty | SQL-01/02/04/06/11/12/13 | L |
| 3 | ✅ **DONE 2026-09-11** (#336, prod v373) — **Chat-session tenancy**: membership check in `validate_session_access`; NULL owner = orphaned, not public; account deletion deletes/anonymises foreign-project sessions; backfill existing NULLs | AUTH-02/03, BIZ-04 | M |
| 4 | ✅ **DONE 2026-09-11** (#337, #339; prod v377 carries `release (…)`) — **Deploy pipeline that can fail**: `curl -f` + release verification against `head_sha`; a migration step in the channel that actually deploys; worker-release check; un-split cancel scope; advisory lock around migrations | TEST-01/15/16/17, DATA-10 | M |

> **Measured 2026-09-11 while harvesting this row, and it moves TEST-15 from latent to live.** `heroku ps` shows the web formation running `sh -c uvicorn app.main:app …` — **no alembic**. Production's `alembic_version` is `b8c9d0e1f2a3`, which does equal the repository head, so the schema is currently correct; it is correct because the last migration was applied through some other channel, not because this pipeline applies one. The next PR carrying a migration deploys code onto the old schema with every step green.
| 5 | ✅ **DONE 2026-09-11** (#338) — **Legal/marketing truth pass**: Privacy Policy (rows→LLM, Stripe/Sentry, architecture), pricing FAQ retired tiers, README reranker | BIZ-03/09/11/13/15 | S–M |
| 6 | ✅ **DONE 2026-09-11** (#340) — **Stripe webhook robustness**: roll ledger claim back on side-effect failure; ordering guard; checkout-time duplicate guard; plan-id from price; `to_thread` the blocking call | BILL-03/04/05/06/07/08 | M |
| 7 | ✅ **DONE 2026-09-11** — no new hole; see `docs/audits/2026-09-11-security-gap-sweep.md` — **Run the security gap sweep** the spend limit killed: headers/CSP/HSTS, cookie flags, secrets hygiene, webhook replay, WS ticket lifecycle, demo path, key-rotation edges | (open audit item) | M |

**P0-1 closed 2026-09-11** — PR #334, live on production as v370. The token ceiling binds
(`ADR-0003`); `PAID_TIERS` derives the ceilings from each tier's promised dollars and is the
only writer; `_limit_for` anchors on the watermark; all four tiers have an explicit credit
answer and `enterprise` is provisioned no key; six unmetered routers now carry a
`DbUsageSink`, guarded by an AST test. Verified on production: `plans` moved from `0/0` on
every row to `base` 40M/120M, `scale` 120M/360M, `team` 200M/600M, `enterprise` unlimited;
boot logged `Plan catalogue reconciled: 0 inserted, 3 updated, 0 retired`; both
`enterprise` grants unchanged, so no account's behaviour moved.

Two rows leave it, and neither is a leftover of the fix — both are things the work
measured:

| # | Task | Why it is here | Effort |
|---|---|---|---|
| 1b | ✅ **DONE 2026-09-12** (#362, ADR-0004) — **Meter dollars, not tokens.** The promise is dollars, and `agent_llm_model` is customer-settable (`projects.py:52,97`) — so the customer picks the price per token and no token figure can bound dollars exactly. `BLENDED_USD_PER_MILLION_TOKENS` is the margin that gap costs. `token_usage.estimated_cost_usd` is **100% populated since 2026-09-04** (#285), which is what makes this newly possible; the 44% NULL rate that looked disqualifying is entirely older rows. Needs two columns on `plans`, a unit change in `check_budget`, and a decision about what a row with an unresolvable price costs | the margin exists only because the unit is wrong | M |
| 1c | ✅ **DONE 2026-09-12** (#363) — **The per-account OpenRouter key on the inference path.** The difficulty recorded here held: `chat.py` builds `ConversationalAgent()` at MODULE level, so a constructor argument cannot reach the shared router — the key travels in a request-scoped `ContextVar`, the mechanism the MCP principal already uses. It binds on OpenRouter alone and says so; a fallback to OpenAI/Anthropic is now disclosed as leaving the key behind. Was: deliberately not done: it cannot bind on the OpenAI/Anthropic fallbacks and needs per-request account context inside an adapter built once per process. Now an *additive* change against a product that is already bounded, rather than the only thing between an account and an unbounded bill. Its remaining value is provider-side attribution per customer | recorded so "the key is unused" is a decision, not a gap | L |

## P1 — product trust and correctness

| # | Task | Refs | Effort |
|---|---|---|---|
| 8 | ✅ **DONE 2026-09-11** (#342) — **Revive the dense leg**: recalibrate/remove the distance floor against measured distributions; label filter-caused emptiness; build the eval with the production filter; fix nDCG normalisation | RET-01/02/04/09, TEST-07 | M |
| 9 | ✅ **DONE 2026-09-11** (#343, #344, #345; KNOW-06 closed 2026-09-12) — **Vector/chunk lifecycle correctness**: reuse-after-drop re-adds chunks; regenerate stops deleting symbol chunks; changed-file symbol sweep; full-path zero-symbol guard; stale entities; embed-step honesty; force_full-aware resume; CALLS against merged graph | KNOW-01…08 | L |
| 10 | ✅ **DONE 2026-09-11** (#346) — **Claims-from-outcome sweep**: one enqueue-result helper; fix the five 202 routes, both cron dispatchers, feed scan, collect-now dedup lie | API-03/12, OPS-05/17, ANA-10 | M |
| 11 | ✅ **DONE 2026-09-11** (#347 — OPS-01/04/06/09/13; OPS-03/10/15/16 carried to 11b) — **Ops visibility**: Sentry in worker; worker metrics into Redis + merged endpoint; wall-clock-anchored maintenance cron + boot sweep; Redis pool retry; orphan-close bookkeeping; `run_db_index` own timeout | OPS-01/03/04/06/15/16, OPS-09/10/13 | M |
| 12 | ✅ **DONE 2026-09-11** (#348) — **Analyzer honesty**: zero-row ≠ stage failure; resumed path gets gates + freshness; degraded synthesis says so; caveats aggregate all stages; StageValidator gets its router; analytics grounding requires a window; per-property isolation; refetch deletions | ORCH-02/04/06/08/09, ANA-01/02/03/04/07/11/12 | L |
| 13 | ✅ **DONE 2026-09-11** (#349) — **Stream/session UX**: lock release on limiter refusal; abort-reason class fix (both sites); poll guard; 401-only logout; clarification restore; DB session release before streaming | API-01/02, FE-01/02/03/05/08 | M |

## P2 — robustness and performance

| # | Task | Refs | Effort |
|---|---|---|---|
| 14 | ✅ **DONE 2026-09-12** (#350) — Event-loop hygiene: xlsx in threadpool (+63× per-row fix), SQL pagination pushdown, batch bounds + worker routing | API-04/09/11 | M |
| 15 | ✅ **DONE 2026-09-12** (#351) — BM25 lifecycle: shared catalog instance; snapshot staleness by indexed sha | RET-05/06 | M |
| 16 | ✅ **DONE 2026-09-12** (#352) — Schedules & alerts done right: timezone; evaluate-before-truncate; email delivery for `notification_channels`; retention for notifications/runs; seat enforcement | COR-01/02/03/07, BILL-09 | M |
| 17 | ✅ **DONE 2026-09-12** (#353) — Rate limiting per actual client: proxy IPs, per-user keys, one 429 shape | API-05/06 | S |
| 18 | ✅ **DONE 2026-09-12** (#354) — Schema alignment migration: 81 nullables, BigInteger row_count, audit_log import, error_log dedup index, doc_embeddings path index, mcp index parity, CHECK on status vocabularies | DATA-02/03/04/05/07/08/09/11 | M |
| 19 | ✅ **DONE 2026-09-12** (#355) — Orchestrator cache sweep keyed on all maps; replan seed excludes rejected results; idempotency check before transient re-run; `query_analytics_source` into `_VALID_TOOLS`; router verdict preserved; resumed-stage sample labelling | ORCH-01/03/05/07/10/11 | M |
| 20 | ✅ **DONE 2026-09-12** (#356) — MCP surface: single slot acquire; `safe_error` on raw exceptions; audit trail for `execute_raw_query`; per-project webhook secrets; role validation on member update; `get_accessible_projects` through the shared filter | AUTH-04/05/06/07/08, BIZ-07 | M |

## P3 — gates, docs, polish

| # | Task | Refs | Effort |
|---|---|---|---|
| 21 | ✅ **DONE 2026-09-12** (#357) — Test-gate integrity: drop `DEPRECATED` exclusion; YAML-parse the CI guards; fix stale 72 %; smoke into CI; AST-based source guards; contrast test reads real alphas; delete leftover skipifs; reload finalizer | TEST-03…07/09/10/11/13 | M |
| 22 | ✅ **DONE 2026-09-12** (#358) — Scenario tooling: suffixed ids everywhere; line-anchor validation; screens/flows under the same guards; SCN-052 + SCR-01 corrections; CLAUDE.md counts point at `make ux-status` | TEST-08/12/14, BIZ-14 | S–M |
| 23 | ✅ **DONE 2026-09-12** (#359) — Docs truth: vision §8 carve-out for chat rows; API.md rate-limit paragraph regenerated; ANA runbook blockquote; OPS comment/invariant fixes; `query` back-fill on the single-block path | BIZ-08/10, API-13, ANA-08/09, OPS-12 | S |
| 24 | ✅ **DONE 2026-09-12** (#360) — UX polish, and a security finding filed inside it: a project `viewer` could run arbitrary DML against a writable customer connection through notes and batch (COR-06). Plus: failure told apart from absence on three surfaces, a task whose end was missed reconciled terminal, the context meter measures the conversation, degradation answers speak the user's language, the tracker's bounds hold on the web dyno | FE-04/06/07/09/10/11, COR-04/05/06/08 | M |
| 11b | ✅ **DONE 2026-09-12** (#361) — The four #347 carried: worker counters reach the endpoint through a shared store; the reap in flight stops spending its own budget; a boot-time Redis failure is retried with backoff instead of permanently demoting the process; an orphaned run is stamped terminal and catalogued | OPS-03/10/15/16 | M |

## Rows 25–27 — the findings no row ever named (added 2026-09-12)

**Discovered by checking the board against the audit rather than by reading it.** With
all 24 rows ticked, a set-comparison of the 164 finding ids in the audit against every id
the rows reference found **15 with no row at all**. One of them (`TEST-13`) had been
fixed anyway, as a rider on row 21. Fourteen had not.

That is the board's own failure mode, and it is the one this whole programme keeps
meeting: a completeness claim nobody could compute. The rows below carry the remainder,
grouped by seam. The comparison is now a test — `test_every_finding_has_a_row.py` — so
"the board covers the audit" is an exit code rather than an impression.

| # | Task | Refs | Effort |
|---|---|---|---|
| 25 | ✅ **DONE 2026-09-12** — **Unbounded input and two security gaps**: an unverified account can accept another person's invitation; the DNS-rebinding guard runs at save and never at connect; the worker will start eight repo indexes at once on a dyno one of them already exhausts; `backfill_days` is bounded only in the React form | AUTH-01, SQL-07, OPS-08, ANA-06 | M |
| 26 | **Connector correctness**: MySQL's row cap does not stop the transfer and leaves a desynced connection; `format_template` passes a trailing newline through unquoted; schema objects fetched by bare name miss a non-`public` schema; MongoDB columns come from the first document only; a parenthesised SELECT skips the server-side cursor | SQL-03, SQL-05, SQL-08, SQL-09, SQL-10 | M |
| 27 | **Ops and honesty**: `record_run` discards the slot `claim_due` reserved; `TracePersistenceService` buffers every worker workflow in the web process; three routes answer 200 with an error inside, two echoing the raw exception; four steps record a completion nothing reads; the real-retriever gate passes with the dense leg returning nothing | OPS-11, OPS-14, API-07, KNOW-09, TEST-02 | M |

## Product backlog — new work, not fixes

| # | Item | Notes |
|---|---|---|
| N1 | App Store + Google Play collectors (m1/m2) | fact tables + adapters behind the existing journal; unblocks the two reserved source types |
| N2 | Reranker decision | either ship the `ml` extra on a dyno with headroom **plus a full re-index** (384→768 d), or delete the flag and the README claim |
| N3 | Clustering enablement | benchmark first; fix DATA-11 before turning on |
| N4 | Alert delivery channels | email exists (Resend) — wire `notification_channels` to it; webhooks later |
| N5 | Seat management | after BILL-09 enforcement, a members-vs-seats view in Settings |
| N6 | Public dashboard share links | roadmap item; today's viewer is membership-gated by design — a share-token model is a new security surface, design first |
| N7 | Connector expansion (BigQuery, Snowflake, DuckDB) | roadmap holdovers; each needs the full read-only + introspection contract from day one (the IMPORTS lesson: a language the extractor does not know produces silence) |
| N8 | Query result caching with invalidation | roadmap; interacts with freshness invariants |
| N9 | Cost optimisation via model routing | after P0-1 lands — routing spend that is not yet metered correctly optimises the wrong number |
| N10 | 12 draft scenarios | design-approved but unbuilt behaviour; the drafts are the spec |
| N11 | Flows/screens layers beyond data-onboarding | scenarios cover the whole product; the WHY/HOW layers cover one scope |

---

## What this review deliberately does not do

It does not restate evidence (the audit doc holds it), does not fix anything, and does not
re-litigate decisions already recorded as deliberate (`DELIBERATE` config map, reserved
vendors, per-connection learning scope, the entitlements degradation direction). Where a
"problem" turned out to be a recorded decision, it is listed as **working** with a note, not
as debt.
