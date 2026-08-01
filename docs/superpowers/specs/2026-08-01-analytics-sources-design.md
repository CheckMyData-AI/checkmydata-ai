# Stage 2 — approved design: analytics data sources

Brief: `2026-08-01-analytics-sources-brief.md` · Docs study:
`2026-08-01-analytics-sources-docs-study.md` · Module map:
`2026-08-01-analytics-sources-modules.md`

## The one-paragraph shape

Three vendors become three `source_type`s on the existing `Connection` table, each
served by an `AnalyticsSourceAdapter` (a sibling of `DatabaseAdapter` under the
already-generic `DataSourceAdapter` ABC) and registered in the existing
`PIPELINE_REGISTRY`. A scheduled ARQ job pulls vendor reports through an **import
journal** whose watermark is `expected − done`, upserts them into natural-keyed fact
tables, and reports an honest `ok`/`partial`/`failed` outcome. At question time a new
`AnalyticsAgent` reads those tables through vendor-shaped tools and passes its result
through DataGate, truncation/partial caveats, freshness and the AnswerQualityGate
before VizAgent charts it. Credentials live once in an owner-scoped
`vendor_credentials` table and are referenced by many connections.

## Approaches considered

| # | Approach | Verdict |
|---|---|---|
| A | **Plug into the existing `DataSourceAdapter` + `PIPELINE_REGISTRY` seams** | **Chosen.** The seams already exist and already carry a non-DB source (MCP). Adding a third registry entry is a smaller, better-tested change than any parallel structure |
| B | A standalone `analytics` service with its own connection model, scheduler and API surface | Rejected. Duplicates project scoping, membership checks, health, deletion cascade and UI for no gain, and puts tenant isolation on a second, unhardened code path |
| C | Ship each vendor as an MCP server and consume via the existing `query_mcp_source` | Rejected at D1/D2 — no first-class connect/index/health parity, no autonomous collection, and it pushes vendor credentials into a subprocess environment rather than Fernet-at-rest |

## Architecture

```
UI  ConnectionSelector (source-type branch) · VendorCredentialsPanel · ConnectionHealth
                    │
API /api/connections (extended)   /api/vendor-credentials (new)
                    │
       ┌────────────┴──────────────────────────────┐
   COLLECT (write path)                     QUERY (read path)
       │                                          │
 _analytics_collect_cron_loop  (hourly)     OrchestratorAgent
       │  hour-scoped redis lock                  │ query_analytics_source
       │  day-scoped task_id                      ▼
       ▼                                    AnalyticsAgent  (tool-loop)
 task_queue.enqueue("run_analytics_collect")      │
       │  └── in-process fallback (no Redis)      │ reads fact tables
       ▼                                          ▼
 AnalyticsCollectService                    DataGate · truncation caveat
       │                                    Freshness · AnswerQualityGate
       ├─ journal.pending_periods()               │
       │    expected − done (+ tail refetch)      ▼
       ├─ adapter.fetch(period)              VizAgent (unchanged)
       │    typed 401/403/404/429/5xx
       ├─ parse → rows
       ├─ upsert  ON CONFLICT (natural key)
       └─ journal.record(status) → CollectOutcome{ok|partial|failed}
```

### Where the code lives (locked file layout)

```
backend/app/analytics/
  base.py        AnalyticsSourceAdapter(DataSourceAdapter), AnalyticsReport, ReportSpec
  errors.py      AnalyticsAuthError · AnalyticsPermissionError · AnalyticsEmpty
                 · QuotaExhaustedError · AnalyticsTransientError
  http.py        injectable transport: retry/backoff, Retry-After, typed status map
  outcome.py     CollectOutcome — ok | partial | failed  (REQ-008)
  journal.py     watermark = expected − done, + tail refetch   (REQ-005)
  fx.py          frankfurter client + fx_rates upsert          (M1)
  ga4/{adapter,config,reports,collect}.py
  appstore/{...}.py     (M1)
  googleplay/{...}.py   (M2)

backend/app/models/       vendor_credential.py · analytics_import.py
                          analytics_ga4.py · analytics_appstore.py · analytics_googleplay.py
backend/app/pipelines/    analytics_pipeline.py   → registered for all three source types
backend/app/agents/       analytics_agent.py · tools/analytics_tools.py
                          prompts/analytics_prompt.py
backend/app/services/     vendor_credential_service.py · analytics_collect_service.py
backend/app/api/routes/   vendor_credentials.py  (+ connections.py extended)
backend/app/worker.py     run_analytics_collect
backend/app/main.py       _analytics_collect_cron_loop

frontend/src/components/connections/  ConnectionSelector.tsx · ConnectionHealth.tsx (extended)
frontend/src/components/settings/     VendorCredentialsPanel.tsx (new)
frontend/src/lib/api/                 vendor-credentials.ts
```

### Load-bearing invariants this design must preserve

| Invariant | How |
|---|---|
| vision §7 #2 — credentials never exposed | Fernet at rest; `VendorCredential.secret_encrypted` excluded from every response schema; REQ-002 asserts it |
| R3 tenant isolation | `vendor_credentials` owner-strict, copying `ssh_key_service` F-SSH-06 verbatim: **never** union `user_id.is_(None)`. Fact rows carry `connection_id` FK; all reads scope by it |
| vision §7 #5 — graceful degradation | Missing FX ⇒ native amount kept; vendor 404 ⇒ `empty`, not failure; adapter absent ⇒ connection unusable, chat unaffected |
| vision §7 #7 — freshness tracked | Journal carries `fetched_at` + period; the agent's answer states vendor lag and any pending period |
| Both queue paths work | Collection goes through `task_queue.enqueue` with a `coro_factory`, never `arq` directly (REQ-007) |
| Ingestion ships off | `analytics_collect_enabled=False` global; `collection_enabled=True` per connection (D6) |

## UI verdict

**Yes — user-facing.** Design tooling: **text-only** (D9), to be recorded in
`docs/ux/foundation.md` → *Design tooling*. Surfaces: source-type branch in
`ConnectionSelector`, a new `VendorCredentialsPanel` mirroring the SSH-keys panel, a
collection-status row in `ConnectionHealth`. New scenarios trace in
`docs/ux/scenarios.md` per module; `docs/ux/lint.py` gates.

## Every REQ is answered by this design

| REQ | Answered by |
|---|---|
| 001 | `Connection.source_type` extension + nullable DB columns migration |
| 002 | `VendorCredential` model + `vendor_credential_service` (F-SSH-06 owner-strict) |
| 003 | `analytics/ga4/adapter.py` on `analytics/http.py` + `errors.py` |
| 004 | `pipelines/analytics_pipeline.py` registered for `ga4` |
| 005 | `analytics/journal.py` — `expected − done` + tail |
| 006 | `models/analytics_ga4.py` + migration natural-key UNIQUE |
| 007 | `worker.run_analytics_collect` + `main._analytics_collect_cron_loop` |
| 008 | `analytics/outcome.py` |
| 009 | `agents/analytics_agent.py` + `tools/analytics_tools.py` + `has_analytics_sources` gate |
| 010 | `AnalyticsCollectService`/agent wiring into DataGate, freshness, AnswerQualityGate |
| 011 | VizAgent consumes the agent's tabular result unchanged |
| 012 | `ConnectionSelector` / `VendorCredentialsPanel` / `ConnectionHealth` |
| 013 | `docs/ux/scenarios.md` + `docs/ux/foundation.md` |
| 014 | `vision.md` §8 edit + `docs/adr/0001-external-report-cache.md` |
| 015 | no raw persistence by construction; journal prune in the maintenance cron; FK cascade |
| 016–021 | `analytics/appstore/*` + `analytics/fx.py` + `models/analytics_appstore.py` |
| 022–026 | `analytics/googleplay/*` + `models/analytics_googleplay.py` |
| 027–028 | program-level (see module map exception) |

No REQ is unanswered; no REQ requires a design element not listed above.
