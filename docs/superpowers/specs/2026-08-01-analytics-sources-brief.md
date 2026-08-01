# Task brief — analytics data sources (GA4 · App Store Connect · Google Play)

> Stage-0 intake artifact (task-pipeline). Operator-confirmed before stage 1.

- **Date:** 2026-08-01
- **Task (one line):** Add GA4, App Store Connect and Google Play as first-class data
  sources — connectable like DB connections, queryable by the orchestrator, and
  collected autonomously on schedule.
- **UI verdict:** **yes** — stage-3 super-ux track armed (text-only, see D9).

## Knowledge sources (phase-1 harvest — written BEFORE the first question)

| Source | What it says about this task | Fresh? | Authority | Stale after this run? |
|---|---|---|---|---|
| `backend/app/connectors/base.py:282` | `DataSourceAdapter` ABC already declared "Universal interface for all data sources (databases, **APIs**, etc.)"; `DatabaseAdapter` is only the DB subclass | current | architecture | no |
| `backend/app/pipelines/base.py` + `registry.py` | `DataSourcePipeline` plugin interface (`index`/`sync_with_code`/`get_status`/`get_agent_tools`) + `PIPELINE_REGISTRY` keyed by `source_type` + `register_pipeline()`. Registered today: `database`, `mcp` | current | architecture | **yes — 3 new source types** |
| `backend/app/models/connection.py:24,50` | `source_type` discriminator; MCP carries nullable columns on the **same** table — precedent for a new source type | current | decision | **yes — new columns** |
| `backend/app/agents/tools/mcp_tools.py:11` | `QUERY_MCP_SOURCE_TOOL` **already names "Google Analytics"** as its example — a generic path claims this ground today | current | decision | **yes — reconciled in D2** |
| `backend/app/agents/mcp_source_agent.py` | Precedent non-SQL sub-agent: tool-loop, iteration cap, timeout, truncation, `no_result` on budget exhaustion | current | pattern | no |
| `backend/app/agents/validation.py:107` | `validate_mcp_result` is a **thin status/empty check only** — no DataGate, no truncation caveat, no freshness | current | **finding** | no |
| `backend/app/agents/tools/orchestrator_tools.py:321-345` | Tools gated by `has_connection`/`has_knowledge_base`/`has_mcp_sources`/`has_repo` — the seam for a new source tool | current | architecture | **yes** |
| `backend/app/main.py:730-815` | Hourly wall-clock sync wave: hour-scoped `redis_lock`, per-project schedule hour, day-scoped `task_id`, `task_queue.enqueue` + in-process `coro_factory` fallback | current | pattern | no |
| `backend/app/worker.py:335` | `WorkerSettings.functions` list; `_arq_func_with_timeout` for per-job timeouts | current | convention | **yes — new job** |
| `backend/app/services/ssh_key_service.py:68-92` | **F-SSH-06 owner-strict**: never union `user_id.is_(None)` into a tenant's list — the pattern the new credential table must copy | current | invariant | no |
| `.github/workflows/deploy.yml:3-24` | **CI success on `main` auto-deploys to production** (`checkmydata-api`, `checkmydata-web`, checkmydata.ai). Merging to main *is* deploying | current | **decision (critical)** | no |
| `vision.md` §8 Anti-Vision | "NOT a data warehouse or ETL pipeline — does not store, transform, or move production data" — **direct conflict with the request** | current | **blocking** | **yes — amended (D1)** |
| `vision.md` §7 Invariants | #2 creds encrypted, never returned; #4 learning per-connection; #5 graceful degradation; #7 freshness tracked or marked stale | current | invariant | no |
| `CLAUDE.md` | CI parity commands, **coverage gate 72 %** combined, ruff/mypy exact pins, new env → `config.py` + `.env.example`, **"Ingestion automation (all off by default)"** house rule, `docs/ux/scenarios.md` hard rule | current | convention | **yes** |
| `docs/ux/scenarios.md` SCN-025…037 | Connections scenario family; SCN-027 ("Add an MCP connection") is the closest template | 2026-07-19 | product | **yes — new scenarios** |
| `backend/app/services/encryption.py` | Fernet `encrypt`/`decrypt` on `MASTER_ENCRYPTION_KEY` — the only sanctioned credential-at-rest path | current | convention | no |
| `backend/app/services/indexing_artifacts.py` | Best-effort artifact cleanup on project/connection delete — the model the retention design mirrors | current | pattern | no |
| wiki: `personal-os/concepts/ingestion-contract.md` | Blueprint distilled + **its own recorded weak points**: no schema versioning, no manifest locking, **no retention → infinite growth** | 2026-06 | context | no (other repo) |
| wiki: `personal-os/concepts/{appstore-connect,google-play}-ingest.md` | Per-source specifics from the live implementation | 2026-06 | context | no (other repo) |
| wiki: `checkmydata-ai/checkmydata-ai.md` | Project overview; lists MCPSourceAgent as *the* external-source path | 2026-07-09 | context | **yes — update at stage 9** |
| `CONTEXT.md` / `docs/adr/` | **none found** — decisions live in `docs/*.md` + `CHANGELOG.md`. ADR tree created by this run | — | — | **yes — ADR-0001 created** |

Precedence: **code > host docs/ADRs > wiki > memory.** Operator outranks every
document — out loud only.

- **Doc repos / hosted doc systems named:** none beyond this repo; the personal-OS
  ingestion guide arrived as pasted operator context + the wiki pages above.
- **Knowledge wiki:** installed (`~/.obsidian-wiki/config` → `sshlg-projects-vault`).

## Scope

**In scope:** three new `source_type`s (`ga4`, `appstore`, `googleplay`) as first-class
connections; a reusable owner-scoped vendor-credential store; per-vendor adapters +
collection jobs writing to natural-keyed fact tables behind an import journal; an
`AnalyticsAgent` with the honesty gates wired; the connection/credential/collection UI;
scenarios, docs, wiki and an ADR.

**Out of scope / explicitly deferred:**
- OAuth sign-in for Google sources (D4 — paste + reusable table chosen instead).
- GA4 realtime reports and extra Apple analytics report types (D7).
- SQL access over the analytics cache (D2 chose a sub-agent; SQLAgent is not extended).
- Query-repair loop, query-failure learning, SQL reconciliation for analytics (D3).

## Requirements (the REQ spine — frozen; adding is free, removing needs operator agreement)

### M0 — spine + GA4

| ID | Requirement | How it's verified | Status |
|---|---|---|---|
| REQ-001 | `source_type` accepts `ga4`/`appstore`/`googleplay`; DB-specific columns made nullable so a non-DB source persists without sentinels | `tests/unit/models/test_connection_analytics.py::test_analytics_connection_persists_without_db_fields` + `alembic upgrade head` clean on SQLite **and** Postgres | open |
| REQ-002 | `vendor_credentials` table: Fernet-encrypted secret, owner-strict lookup copying F-SSH-06 (never union NULL-owner), never present in any API response | `test_vendor_credentials_owner_strict`, `test_vendor_credential_secret_never_serialized` | open |
| REQ-003 | `GA4Adapter(DataSourceAdapter)` with injectable HTTP: 401→auth, 403→permission, 404→empty, 429/5xx→retry w/ backoff honoring `Retry-After`, quota→`QuotaExhaustedError`; 401/403 never retried | `tests/unit/connectors/test_ga4_adapter.py` — one test per status code + `test_ga4_no_retry_on_auth`; zero network in tests | open |
| REQ-004 | `AnalyticsPipeline` registered in `PIPELINE_REGISTRY` for `ga4`, implementing all four abstract methods | `test_pipeline_registry_resolves_ga4`, `test_analytics_pipeline_implements_interface` | open |
| REQ-005 | Import journal + watermark computed as **expected − done** (not `max(period)`) + tail refetch; re-running a period never duplicates rows | `test_watermark_is_expected_minus_done` (asserts a hole below the high-water mark is refilled), `test_collect_rerun_is_idempotent` | open |
| REQ-006 | GA4 fact tables (overview, geo, platform, trend, events) each with a natural-key UNIQUE and `ON CONFLICT DO UPDATE` | migration + `test_ga4_upsert_respects_natural_key` | open |
| REQ-007 | `run_analytics_collect` ARQ job + hourly cron wave (hour-scoped Redis lock, day-scoped `task_id`) **and** the in-process fallback when `REDIS_URL` is unset | `test_analytics_cron_wave_dispatches_due_only`, `test_analytics_collect_runs_in_process_without_redis` | open |
| REQ-008 | Exit contract: `ok`/`partial`/`failed` — errors with rows written = `partial`, errors with none = `failed`; never reported as success | `test_outcome_contract` parametrized over all three | open |
| REQ-009 | `AnalyticsAgent` + `query_analytics_source` tool gated by `has_analytics_sources`; budget exhaustion returns `no_result`, not a fake answer | `test_orchestrator_exposes_analytics_tool_only_when_source_exists`, `test_analytics_agent_budget_exhaustion_is_no_result` | open |
| REQ-010 | Honesty gates wired: DataGate hard checks, truncation/partial caveat, freshness warning, AnswerQualityGate | `test_analytics_datagate_blocks_impossible_values`, `test_analytics_answer_carries_freshness_caveat`, `test_analytics_partial_data_caveat` | open |
| REQ-011 | Analytics results chart through VizAgent unchanged | `test_analytics_result_renders_chart` | open |
| REQ-012 | UI: source-type branch in `ConnectionSelector`, credential picker, `VendorCredentials` panel, collection status row in `ConnectionHealth` | vitest specs per component + `npx tsc --noEmit` + `eslint --max-warnings=0` | open |
| REQ-013 | UX scenarios for add-GA4-connection, manage-vendor-credentials, collection-status-with-partial-data — traced | `docs/ux/scenarios.md` rows **+ a real scenario-consistency check** `tests/unit/docs/test_ux_scenarios.py` asserting index↔body parity and that every `Coverage:` path resolves. *(Corrected at stage 3: `docs/ux/lint.py` named in the original brief does not exist in this project — see correction note below)* | open |
| REQ-014 | `vision.md` §8 amended with the external-report carve-out + `docs/adr/0001-external-report-cache.md` written | `grep` §8 contains carve-out; ADR file exists with context/decision/consequences | open |
| REQ-015 | Retention: raw vendor payloads never persisted; journal rows pruned > 400 days; connection/project delete cascades all analytics rows | `test_raw_payload_not_written_to_disk`, `test_journal_prune_over_400_days`, `test_delete_connection_cascades_analytics` | open |

### M1 — App Store Connect

| ID | Requirement | How it's verified | Status |
|---|---|---|---|
| REQ-016 | ES256 JWT: `kid` in header, `aud=appstoreconnect-v1`, TTL ≤ 20 min, re-minted per request | `test_asc_jwt_claims_and_header`, `test_asc_jwt_ttl_under_20min` | open |
| REQ-017 | Sales/subscription TSV parse; **Parent Identifier is a SKU, resolved to the parent Apple ID**; suppressed `Subscribers` column never used for active counts (state columns summed instead) | `test_asc_parent_sku_resolves_to_apple_id`, `test_asc_active_subs_ignores_suppressed_column` — on fixture TSV | open |
| REQ-018 | Fiscal-month lookahead (Apple's label leads the calendar ~3 months); 404 on an unclosed period is skipped, not an error | `test_asc_fiscal_lookahead_requests_future_labels`, `test_asc_404_period_is_empty_not_failure` | open |
| REQ-019 | ASC fact tables + journal rows + upsert idempotency | migration + `test_asc_upsert_idempotent` | open |
| REQ-020 | FX: frankfurter/ECB → `fx_rates`; **missing rate ⇒ `amount_usd` NULL, native amount kept, answer says which rows were not converted** | `test_fx_missing_rate_keeps_native_and_flags`, `test_fx_upsert_by_currency_month` | open |
| REQ-021 | App Store connection UI + scenarios traced | vitest + `docs/ux/lint.py` green | open |

### M2 — Google Play

| ID | Requirement | How it's verified | Status |
|---|---|---|---|
| REQ-022 | Dual transport on one service account, two scopes: GCS JSON API (list + `alt=media`, paginated) and Reporting API v1beta1 (`timelineSpec`, `pageToken`) | `test_gp_storage_list_paginates`, `test_gp_reporting_query_pages`, `test_gp_two_scopes_from_one_sa` | open |
| REQ-023 | Object-path conventions: earnings suffix is **non-deterministic** → prefix listing + match; sales deterministic; installs/subs per package | `test_gp_earnings_matched_by_prefix_not_exact_name` | open |
| REQ-024 | Play fact tables + journal + **2-month refetch tail** (a month journaled `empty` today may publish later) | migration + `test_gp_refetch_tail_reopens_empty_month` | open |
| REQ-025 | `earnings_usd` NULL means "payout not yet published", **not** zero — the answer distinguishes them | `test_gp_unpublished_differs_from_zero_in_answer` | open |
| REQ-026 | Google Play connection UI + scenarios traced | vitest + `docs/ux/lint.py` green | open |

### Cross-cutting

| ID | Requirement | How it's verified | Status |
|---|---|---|---|
| REQ-027 | Docs synced: `CLAUDE.md`, `API.md`, `CHANGELOG.md`, `docs/ANALYTICS_SOURCES.md` runbook, `backend/.env.example`, wiki | every stale ledger row above closed; runbook commands resolve | open |
| REQ-028 | Combined coverage stays ≥ 72 % after **each** module | `coverage report --fail-under=72` per module | open |

Status lifecycle written at stage 4, 5 and 10 only: `open` → `planned` → `built` →
`verified` \| `partial` \| `deferred` \| `dropped`.

## Decisions locked

| # | Decision | Chosen | Rationale |
|---|---|---|---|
| D1 | vision §8 conflict | **Cache-with-provenance; amend §8; write ADR-0001** | GA4/ASC/Play are quota-limited, lagging report APIs with no query language — caching is what makes them queryable. Carve-out is explicit, not implicit |
| D2 | Query path | **Dedicated `AnalyticsAgent` sub-agent** *(operator override of the SQL-over-scoped-views recommendation)* | Operator's call. Consequence accepted and carried as REQ-010: SQL-shaped gates are **not** inherited and must be wired deliberately |
| D3 | Which gates wired | **Honesty subset + viz**: DataGate, truncation/partial caveat, freshness, AnswerQualityGate, VizAgent. **Not**: QueryRepairer, query-failure learning, sql_reconciliation | Money/install data must not reach users less validated than SQL data; repair/learning are statement-shaped and meaningless here |
| D4 | Credentials | **Reusable owner-scoped `vendor_credentials` table** *(operator override of the on-connection recommendation)* | Operator's call; one SA can back several connections. R3 risk answered by copying F-SSH-06 owner-strict verbatim (REQ-002) |
| D5 | Decomposition | **M0 spine+GA4 → M1 ASC → M2 Play**, each deploying on its own | Walking skeleton: prove the seam on the cheapest vendor before Apple's fiscal calendar and Play's dual transport |
| D6 | Scheduling | **Mirror the daily-sync wave**; global `analytics_collect_enabled=false`, per-connection `collection_enabled=true` | Reuses a proven multi-dyno-safe pattern; honors the house rule that ingestion automation ships off, without making each new connection a manual step |
| D7 | Data scope | **Blueprint parity** (GA4 5 reports · ASC 6 tables · Play 5 tables) | Proven against live accounts; every gotcha already documented |
| D8 | FX | **Frankfurter/ECB, keyless**; missing rate ⇒ `amount_usd` NULL + native kept. Host corrected at stage 1 to **`api.frankfurter.dev/v1`**; provenance is the **returned** `date`, not the requested one | No new user credential, no cost; degradation never loses the money. ECB skips weekends/holidays, so the returned date is authoritative |
| D9 | Design surface | **Text-only**, recorded in `docs/ux/foundation.md` → Design tooling | Every surface extends already-designed components under `DESIGN_SYSTEM.md`; no new visual language |
| D10 | Branch + deploy | **Standing go per module** *(revised 2026-08-01 — operator: "1, автономно до конца", superseding the earlier stop-at-PR answer)*. One branch per module; on ALL named gates green I merge to `main`, which auto-deploys to **production**; then stage 8 verifies. Any gate red → stop, report, do not merge | Specific standing authorization per the deploy floor: **named target** `checkmydata-api` + `checkmydata-web`; **named preconditions** `ruff format --check` · `ruff check` · `mypy` · backend unit+integration with combined coverage ≥ 72 % · `tsc --noEmit` · `eslint --max-warnings=0` · `vitest` · `docs/ux/lint.py` |
| D11 | Retention | Facts kept; **raw never persisted**; journal pruned > 400 d; delete cascades | Fixes the blueprint's own recorded "no retention → infinite growth" flaw; also sidesteps Heroku's ephemeral FS |
| D12 | Escalation | Vendor-contract surprises + gate failures + new credentials/paid deps | Implementation detail is mine; anything that would shrink a REQ or add a dependency is yours |

## Users & context

- **Who / for what:** existing project owners/editors who already connect databases and
  now want app-revenue, install and analytics questions answered in the same chat, with
  the same traceability.
- **Where it runs:** FastAPI + ARQ worker on Heroku (ephemeral FS — nothing durable on
  disk); Postgres in prod, SQLite in dev; both the ARQ and in-process task paths must work.
- **Constraints:** vendor quotas; 1–7 day data lag (Play earnings ~mid-following-month);
  multi-tenant isolation (R3); credentials Fernet-encrypted, never returned.

## Autonomy (stages 1→10 read this instead of asking)

| Stage | Question | Answer |
|---|---|---|
| run-wide | Model | **Opus 5** (`claude-opus-5`) — top tier available; no per-stage overrides |
| run-wide | Autonomous vs escalate | D12: decide layout/naming/tests/refactors/retry-tuning/migrations; **stop** on vendor-contract conflict, a gate that needs a REQ narrowed, a new credential/paid dep, or anything outward beyond D10 |
| 0 Harvest | Doc sources beyond this repo | Wiki (`sshlg-projects-vault`) — stage 9 **may** write to it. No other repos; no hosted doc systems |
| 1 Docs | External libs/APIs | GA4 Data API v1beta (`google-analytics-data`), App Store Connect API + `PyJWT[crypto]`/`cryptography`, Google Play Cloud Storage JSON API + Play Developer Reporting API v1beta1 (`google-auth`), frankfurter.app. All public → context7, web-search fallback |
| 2 Decompose | Platform? cadence | **Platform** — M0/M1/M2, PR per module (D5, D10) |
| 2–3 Spec | UI verdict | **Yes**; super-ux chain runs per module; no scenario-tracing waiver |
| 3 Design surface | Figma or text-only | **Text-only** (D9); recorded in `docs/ux/foundation.md` |
| 3 Design file | Team/file | N/A — text-only |
| 4–5 Dev | Branch policy | `feat/analytics-m0-ga4`, `feat/analytics-m1-appstore`, `feat/analytics-m2-play` off `main`, built in a worktree. **`main` is off-limits for direct commits.** Conventional commits. Tracker: `BACKLOG.md` |
| 5 Integration | How it lands | **I merge to `main` per module once all gates are green** (D10). No parallel fan-out across modules — they are sequential by design |
| 6 Tests | Command / green | `make test-all` (backend) + `cd frontend && npm test`. Green = 0 failures; combined coverage ≥ 72 %. No known-red baseline |
| 7 Lint | Command | `ruff format --check app/ tests/` · `ruff check app/ tests/` · `mypy app/ --ignore-missing-imports` · `tsc --noEmit` · `eslint . --max-warnings=0` · `pytest tests/unit/docs/test_ux_scenarios.py` *(replaces the non-existent `docs/ux/lint.py`)* |
| 7 Deploy | Target + path | Heroku `checkmydata-api` + `checkmydata-web`, via GH Actions `deploy.yml` on CI success on `main`. Release automation: on. Deploy-from-`main` only |
| 7 Deploy | Authorization | **Standing go, specific** (D10): merge→deploy per module, gated on the eight named checks. Red gate ⇒ stop, no merge. Anything outward beyond this (new infra, env-var changes on the Heroku app, force-push) still asks |
| 8 Post-deploy | Logs / health | Per module after merge: watch GH Actions CI → Deploy, then `heroku logs -a checkmydata-api` for migration + boot, then `GET https://api.checkmydata.ai/api/health` |
| 9 Docs+wiki | Targets | `CLAUDE.md`, `API.md`, `CHANGELOG.md`, `docs/ANALYTICS_SOURCES.md`, `backend/.env.example`, `docs/ux/*`, wiki `projects/checkmydata-ai/*`; **wiki sync = yes** |
| 10 Acceptance | Sign-off / deferrals | Operator signs off; deferrals → `BACKLOG.md` + carry-over ledger |

## Done-criteria

1. A project owner can create a GA4, App Store Connect or Google Play connection in the
   UI using a stored vendor credential, and see it succeed or fail with a specific reason.
2. With `analytics_collect_enabled=true`, data collects on schedule without human action;
   re-running a period never duplicates rows; a partial run reports `partial`, not success.
3. Asking a revenue/installs/traffic question in chat returns an answer that carries its
   freshness and any partial-data caveat, and charts like any other answer.
4. All gates green per module (lint, types, tests, coverage ≥ 72 %, ux-lint), merged to
   `main`, deployed to production, and verified live (migrations applied, clean boot,
   `/api/health` 200).
5. Every REQ accounted for at stage 10 with evidence from a check seen failing once.

## Open assumptions / risks

| # | Assumption / risk | Validation |
|---|---|---|
| A1 | `Connection.db_type`/`db_port`/`db_name` can be made nullable without breaking existing DB rows | Migration tested against a seeded DB in stage 5; REQ-001 asserts both dialects |
| A2 | Vendor report schemas match their published docs | Stage 1 grounds every contract on fetched docs; parsers tested on fixture payloads. **Divergence is a D12 stop-and-ask** |
| A3 | frankfurter.app remains keyless and available | Degradation is designed in (REQ-020): missing rate never loses the amount |
| A4 | `google-analytics-data` + `google-auth` + `PyJWT[crypto]` add acceptable image weight | Measured at stage 6; all are pure-Python or already-transitive |
| A5 | No staging environment exists — production is the only deploy target | **Now load-bearing** after the D10 revision: the eight-gate precondition and per-module (not big-bang) deploys are the only safety net. Each module is additive and feature-flagged off (`analytics_collect_enabled=false`), so a bad deploy degrades to "new source type unusable", not "existing chat broken" |
| **R1** | **D2 (sub-agent over SQL) means every future quality gate must be wired twice** — once for SQL, once for analytics | Recorded here as a standing cost, not a one-off. Revisit if a third non-SQL source appears |
