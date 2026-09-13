# Audit — data connections, synchronization and the orchestrator (2026-09-13)

**Question asked:** does connecting a database, Google Play, the App Store and a codebase
actually work; how do synchronization and the orchestrator work; what is wrong in the code
and the architecture; and what is the improvement plan, each item worked out as a
standalone project.

**How it was measured.** Repository at `main` `d0576867` (release **v405** on Heroku).
Production figures come from SQL against the live Supabase database and from
`heroku ps/config/releases`, not from log lines; every code claim carries a `file:line`
that was read, and the two production defects were confirmed at their lines by a second
reader before being ranked. Four subsystem readings were done in parallel (connectors,
analytics sources, indexing/sync, orchestrator) and cross-checked against the production
evidence. No file outside `docs/` was changed by this audit.

**Where it fits.** `docs/audits/2026-09-09-full-system-audit.md` produced 164 findings and
a 31-row board that is now closed (`docs/reports/2026-09-12-remediation-programme.md`).
This audit is narrower and deeper: four subsystems, read after that programme shipped,
with the intent of finding what the programme did not — and what it broke. Two of the
P0s below were introduced *by* remediation PRs (#344 on 2026-09-11, the model switch of
2026-09-10), which is the general lesson of §5.

---

## 1. Verdict in one table

| Subsystem | Works in production? | Confidence | One-line state |
|---|---|---|---|
| Database connection (MySQL over SSH tunnel) | **Yes** | measured: 214 tables indexed, refreshed nightly | The only path anyone has used. Postgres, ClickHouse, MongoDB have never been connected in production and are covered by mocked tests only. |
| Database connection (the other three engines) | Untested in anger | tests stub every driver | Each has at least one contract gap the MySQL path does not (§2.1 F-06…F-11). |
| Google Analytics 4 | Built end to end, **never used** | 0 credentials, 0 fact rows, collector switch unset | Three P1 defects would surface on the first real connection (§2.2). |
| App Store Connect | **No** | enum value + 422 refusal only | UI lets a user store a `.p8` key nothing can use; the LLM tool description promises App Store data. |
| Google Play | **No** | same | Same. |
| Codebase (repository index) | Yes for incremental; **full rebuild broken since 2026-09-11** | measured: P0-B below | Any re-index that reaches `generate_docs` on the production vector backend dies. |
| Code↔DB sync | **Broken since 2026-09-10** | measured: 4 consecutive `store_sync` failures | The map — the product's central artefact — has not updated for four days while the nightly sync reports it ran. |
| Nightly synchronization | Runs, but lies about outcomes | 7 of 17 `daily_sync` runs "failed", all false reaps | Heartbeats land on the wrong row for three of four run kinds. |
| Orchestrator (chat) | Answers simple questions; 35% of real requests failed | 25 traces in 30 days, none since 09-05 | Every failure ran 4.5–6 min against a 180 s "limit" and left a trace that says nothing about why. |

---

## 2. Production evidence

Every figure is the output of a query in this session (`heroku config:get DATABASE_URL`,
`psql`), taken 2026-09-13 ~22:00 UTC.

### 2.0 What is connected

| Source kind | Rows | Note |
|---|---|---|
| `sqlite` connections (demo) | 2 | `source_type=database`, read-only |
| `mysql` connections | 2 | one carries `db_index` (214 tables, last 2026-09-12 22:28 UTC) |
| `postgres` / `clickhouse` / `mongodb` | 0 | never created |
| GA4 vendor credentials / fact rows / journal rows | 0 / 0 / 0 | `ANALYTICS_COLLECT_ENABLED` unset (default off) |
| Projects / repositories | 4 / 1 | one repository (`esim-php`) carries the whole knowledge pipeline |

### 2.0.1 What ran (last 14 days, `indexing_runs`)

| kind | completed | failed | cancelled | note |
|---|---|---|---|---|
| `index_repo` | 19 | 13 | 2 | schedule runs finish in 60–90 s on `no_changes`; 4 orphaned by restarts on 09-09; **1 new defect 09-11** |
| `daily_sync` | 10 | 7 | 0 | all 7 = `stale run reaped` (5 at `repo_index`, 2 at `db_index` on 09-11 22:00 / 09-12 04:00) |
| `db_index` | 7 | 2 | 0 | both `stale run reaped (fetch_samples)` after 1447 s on 09-12; 1 manual failure 09-05 `Can't connect to MySQL server on '127.0.0.1'` |
| `code_db_sync` | 6 | 11 | 0 | **last success 2026-09-09**; 4 consecutive `store_sync` failures since 09-10 |

`error_log`, 14 days: `stale run reaped` at `repo_index` ×7, `code_symbol_embed` ×7,
`graph_build` ×6, `db_index` ×3, `fetch_samples` ×2, `generate_docs` ×2, `analyze_sync` ×1.

### 2.0.2 Chat (`request_traces`, 30 days)

25 traces, 2026-08-17 → 2026-09-05, none since. Excluding 2 `generate_title`:

| status | route | complexity | n | avg s | max s |
|---|---|---|---|---|---|
| failed | unknown | unknown | 8 | 269 | 357.8 |
| completed | query | simple | 7 | 59 | 78.4 |
| completed | unknown | unknown | 5 | 63 | 204.9 |
| completed | direct | simple | 2 | 18 | 19.8 |
| completed | query | moderate | 1 | 18 | 18.2 |

8 of 23 real requests failed (35%); every failure has `route='unknown'`, `failure_kind`
NULL, and 4.5–6 minutes of duration. `error_log` adds
`query/chat: Stale: pipeline_end never received` ×2.

### 2.0.3 The two live defects, confirmed at their lines

**P0-A — code↔DB sync cannot store its result.**
`backend/app/knowledge/code_db_sync_analyzer.py:252-253` hands the model's tool-call
arguments straight to two `Text` columns:

```python
required_filters_json=args.get("required_filters", "{}"),
column_value_mappings_json=args.get("column_value_mappings", "{}"),
```

The schema declares both `type="string"`; the neighbouring field got a guard
(`if isinstance(col_notes, dict): col_notes = json.dumps(col_notes)`, `:242`) and the two
beside it did not. `models/code_db_sync.py:41-42` are `Text`. asyncpg refuses:
`invalid input for query argument $6: {} (expected str)`. The parsing line dates from
2026-03; what changed on 2026-09-10 is `DEFAULT_LLM_MODEL` → `deepseek/deepseek-v4-flash-0731`,
which returns JSON objects where `gpt-4o` returned JSON strings. The test fixture
(`tests/unit/knowledge/test_code_db_sync_analyzer.py:23`) feeds `"required_filters": "{}"` —
it mirrors the schema, not a model. The failure is inside `store_sync` before `commit()`,
so the previous map survives, but freshness marks sync stale after every repo index and
every nightly sync reports `partial`.

**P0-B — every prose/symbol write on the production vector backend fails.**
`backend/app/knowledge/pgvector_store.py:304-306`:

```python
kind_clause = " AND doc_id LIKE 'sym:%'"        # :304
kind_clause = " AND doc_id NOT LIKE 'sym:%'"    # :306
```

is concatenated into the query string executed by psycopg3 (`:308-313`), which parses the
text for `%s/%b/%t` — a bare `%'` inside a literal must be `%%`. Error text matches the
incident verbatim (`only '%s', '%b', '%t' are allowed as placeholders, got '%''`).
Introduced by `bd256428` (#344, 2026-09-11 18:43 UTC); the first failing run started at
19:48 UTC the same day. Call sites: before every `add_documents` in `generate_docs`
(`pipeline_runner.py:~1335`, `:~1440`) and in `code_symbol_embed` (`:~1768`). Chroma is
unaffected, which is why `make setup` and the unit tests (`test_pgvector_store.py`
executes no SQL) stayed green. The 09-11/09-12 schedule runs "completed" because they
exited early on `no_changes` and never reached the step.

---

## 3. Findings by subsystem

Severity: **P0** data loss / silent incorrectness in production now · **P1** a documented
feature is dead, or a budget is not a budget · **P2** fragility with a concrete trigger ·
**P3** hygiene with a concrete cost. Every finding was verified at the cited lines.

### 3.1 Database connections

**How it works.** `POST /api/connections` (`api/routes/connections.py:724-775`): owner role
→ quota → vendor-credential / SSH-key ownership (`:741-747`) → host guard on every host
(`host_guard.py:189-209`) → `ConnectionService.create` (encrypts `db_password`,
`connection_string`, `mcp_env`, `connection_service.py:198-209`). `to_config`
(`:707-860`) is the one funnel: decrypt, resolve SSH key (`:744-749`), parse
pre-commands, **re-run the host guard** (`:826-834`), return `ConnectionConfig` whose
`__repr__` redacts secrets (`connectors/base.py:59-114`). Query: `SQLAgent` → cached
connector per `connector_key(cfg)` (`sql_agent.py:1551-1571`, cap 32) → `ValidationLoop`
→ `SafetyGuard` (`validation_loop.py:110-113`) → `connector.execute_query`. Read-only is
layered: guard + engine session (PG `default_transaction_read_only`, MySQL
`SET SESSION TRANSACTION READ ONLY`, ClickHouse `readonly:1`, SQLite `mode=ro`, Mongo
code-level only). SSH **tunnel**: `SSHTunnelManager.get_or_create` keyed by
bastion+endpoint+credential hash, ref-counted, idle sweep 30 min (`ssh_tunnel.py:292-394`).
SSH **exec**: `get_adapter(ssh_exec_mode=True)` → `SSHExecConnector`, SQL as a client
argument, password on stdin — unless a custom template, which pipes and skips read-only
decoration (`ssh_exec.py:166-197`).

**Backlog row 11.0 (`ssh_key_id` cross-tenant attach) is FIXED — close it.** Ownership is
checked on create (`connections.py:746-747` → `_require_owned_ssh_key`) and on the merged
PATCH row (`:873-875`), pinned by `tests/integration/test_ssh_key_ownership.py`. The
read-time `user_id=None` lookups (chat, worker, scheduler, daily sync — 20 sites) read a
reference verified at write, the same model the vendor-credential fix uses. But the fix
created F-04.

| # | Sev | Finding | Evidence |
|---|---|---|---|
| C-01 | P1 | `db_index` runs are reaped while alive: the time-driven beat lands on `db_index_summary.heartbeat_at`, the reaper judges `indexing_runs.heartbeat_at`, and that row is beaten only when a *table finishes* sampling. Five large tables in flight for >300 s (each `1 sample + K distinct + ≤20 approx_stats` sequential queries at 30 s each) → false `stale run reaped (fetch_samples)`, exactly the two 09-12 reaps. Third occurrence of the "N1 trap" | `db_index_pipeline.py:425-430` → `db_index_service.py:232-239`; `stale_run_reaper.py:48-76`; `run_coordinator.py:606-620` (events beat only on `started`/`completed`); `run_manifests.py:23` |
| C-02 | P1 | Frontend SSH-exec presets reintroduce all three hardened-away surfaces: `{db_password}` on the remote argv (visible in `ps`), custom template ⇒ read-only decoration skipped, SQL piped to stdin (the `\!` surface SQL-01 closed only for built-in templates). Enabling exec mode auto-fills the preset | `frontend/src/components/connections/connection-form-helpers.ts:14-21`; `ConnectionSelector.tsx:920-940, 1354-1366`; `ssh_exec.py:92-96, 146-155, 166-183, 193-197` |
| C-03 | P1 | A tunnel is closed under a live pool: `touch()` runs only in `get_or_create`; the 30-min idle sweep `stop()`s the SSH connection while a `db_index` (budget 1800 s) or the chat's cached connector is mid-query. `execute_query` has no reconnect path → every remaining table `sample_failed` | `ssh_tunnel.py:22, 111-127, 300-307, 376-394`; `main.py:1873`; `mysql.py:314-331` (only introspect retries) |
| C-04 | P1 | Requester-scoped SSH-key resolution silently drops the key for every project member except the uploader (tunnel starts with no `client_keys`, reported as a bastion problem) and 404s their PATCH. Nine sites pass the requester's id; the chat path passes `None` | `connection_service.py:744-749`; `connections.py:973, 1029, 1114, 873-875`; `notes.py:253`, `schedules.py:264`, `health_monitor.py:87`, `connection_learnings.py:248`, `batch_service.py:344`; `ssh_tunnel.py:56-62` |
| C-05 | P2 | `POST /{id}/test` against an unreachable bastion can hold the request ~14 min: tunnel 2× × manager 3× × service 3× = 18 handshakes at 45 s. And the service-level retry catches `(TimeoutError, ConnectionError, OSError)` — pymysql's `OperationalError` is none of these, so the engine production uses is never retried | `ssh_tunnel.py:13, 64-86, 289-335`; `connection_service.py:528-536`; `retry.py:33-52` |
| C-06 | P2 | MySQL/ClickHouse DSN path does not percent-decode credentials and defaults a missing user to `root`; the frontend parser *does* decode, so one string behaves differently per box | `mysql.py:135-148`; `clickhouse.py:99-105`; `frontend/src/lib/connection-string.ts:49-50` |
| C-07 | P2 | ClickHouse: after one timed-out query `introspect_schema` returns an empty schema and `test_connection` reports down (`_client` checked directly, `_get_client()` not used); no `reconnect()` so the health loop cannot heal it; pipeline records `completed, tables: 0` | `clickhouse.py:133-150, 225-245, 358-361`; `db_index_pipeline.py:458-460` |
| C-08 | P2 | ssh-exec on MySQL/ClickHouse qualifies every statistics query with schema `public` (`TableInfo.schema` default) → `` `public`.`t` `` → every `distinct_values`/`approx_stats` fails and is swallowed to `[]` | `ssh_exec.py:462-470, 593, 654-658`; `base.py:197, 488-495, 537-560` |
| C-09 | P2 | ssh-exec timeouts carry no `error_type` → classified `UNKNOWN` → LLM "repair" instead of narrowing | `ssh_exec.py:368-371`; `error_classifier.py:227-236` |
| C-10 | P2 | A forwarded-hop failure is reported as a failure of `127.0.0.1`; `is_alive` proves the SSH transport, never the forward; the retry re-enters the same "alive" tunnel | `ssh_tunnel.py:99-109, 164-167`; the 09-05 incident |
| C-11 | P2 | Mongo introspection has no per-collection isolation: one view/unauthorised collection aborts the whole schema | `mongodb.py:352-397` |
| C-12 | P2 | Project **viewers** can read `ssh_command_template` and `ssh_pre_commands` — free-form shell the UI invites `{db_password}` into | `connections.py:603-604, 790-800`; `base.py:70-72` |
| C-13 | P3 | `ConnectionUpdate` is looser than `ConnectionCreate` (free `str` db_type; different length caps) | `connections.py:423, 507, 833-837` |
| C-14 | P3 | Bad key/passphrase (`KeyImportError` is a `ValueError`, not `asyncssh.Error`) is retried 3× as a network fault, real cause hidden | `ssh_tunnel.py:56-62, 325-335` |
| C-15 | P3 | Frontend/backend validation mismatches: `safePort` silently substitutes 5432 for any engine; form requires key+user where backend accepts host alone; DSN+ssh_host accepted then tunnel bypassed; exec `execute_query` ignores `params` | `connection-form-helpers.ts:69-73`; `ConnectionSelector.tsx:544, 578-585, 697`; `ssh_exec.py:319-334` |
| C-16 | P3 | Dead/duplicated code: `_closed` checked on connectors that never set it; duplicate `_quote_identifier`; unused `_sample_query`/`_build_distinct_query`; `parse_psql_csv/tuples` with no callers | `sql_agent.py:1556`; `ssh_exec.py:648-652`; `db_index_pipeline.py:141-167, 293-314`; `cli_output_parser.py:26-51` |

**Architecture.** One interface exists (`DatabaseAdapter`, `base.py:377-568`) and is
honoured loosely: `reconnect()` for 3 of 6, `error_type` for 5 of 6, `params` for 5 of 6,
and `TableInfo.schema` means four different things. Dialect knowledge lives in **twelve**
hand-maintained lists keyed on `db_type` strings (registry aliases, `_quote_identifier`,
`_noorder_dialects`, `sql_dialect_for`, `error_classifier.DIALECT_MAP` — which has **no
`sqlite`** entry so every untyped SQLite error is `UNKNOWN` — exec templates, output parser,
the create `Literal`, three frontend maps). SQLite is a demo artefact inside the general
funnel: **every** `to_config` for every connection calls `repair_demo_db_if_missing`
(`connection_service.py:809`) and the connector imports `demo_data`. A fifth engine
(BigQuery/Snowflake) does not fit `ConnectionConfig` (no host/port/user/password shape),
needs an entry in all twelve lists, gets wrong quoting from the base SQL helpers, and has
no engine-side read-only session — the analytics spine's `vendor_credential_id +
source_config_json` is already the better credential model for it.

**Tests.** ~300 tests, all with stubbed drivers. Not covered: `IndexingRun` beat during
`fetch_samples` (C-01), tunnel idle sweep vs active pool (C-03), the retry stack (C-05),
DSN decoding (C-06), ClickHouse recovery (C-07), exec qualification/timeout type
(C-08/09), Mongo isolation (C-11), non-uploader key resolution (C-04), exec presets
(C-02), update/create parity (C-13). **No real-driver integration test exists for any
network engine.**

### 3.2 Analytics sources (GA4 · App Store Connect · Google Play)

**Status per vendor.** GA4 is complete: credential (`vendor_credentials.py:62-90`,
Fernet, write-only over HTTP, in key rotation), adapter with offset paging, `keep_empty_rows`,
per-property isolation and quota memory (`analytics/ga4/adapter.py:215-593`), journal
(`analytics/journal.py`), five fact tables with natural-key UNIQUE (`models/analytics_ga4.py`),
hourly wave (`main.py:1088-1246`), three parameterised agent tools (`analytics_agent.py:479-515`),
UI (`ConnectionSelector.tsx:1051-1171`, `ConnectionHealth.tsx:183-410`). **App Store and
Google Play** are an enum value (`analytics/source_types.py:32`), a pipeline-registry
entry, a 422 refusal (`connection_service.py:119-147`), a `ValueError` in `build_adapter`
(`analytics_collect_service.py:227-230`), and — the over-promise — a credential-provider
option in the UI ("App Store Connect — Private key (.p8)", `frontend/src/lib/api/vendor-credentials.ts:48-59`)
that stores an unvalidated secret nothing can use, plus an LLM tool description that
advertises "App Store Connect, Google Play … installs or subscription data"
(`agents/tools/analytics_tools.py:31-33`).

| # | Sev | Finding | Evidence |
|---|---|---|---|
| A-01 | P1 | A period in which one property fails is journalled `ok` → that property's data is permanently missing outside the 2-period tail; the agent renders it as "the vendor truncated this period" (wrong cause), and the tail refetch erases the note. The 2026-09-03 isolation fix made the journal key too coarse | `adapter.py:352-367, 391-406`; `analytics_collect_service.py:623-631`; `journal.py:49, 119-124`; `analytics_agent.py:1055-1063` |
| A-02 | P1 | A revoked/deleted/expired service-account key is classified **transient** (gRPC wraps `RefreshError` as `StatusCode.internal` → HTTP 500) → retried 3× per period, ~450 doomed token refreshes per run, nightly, forever; never stops the report, never writes the `_connect` sentinel. `connect()` only parses the key, no network call | `ga4/config.py:200-217`; `adapter.py:138-140`; `http.py:149-150`; `analytics_collect_service.py:582-596`; verified in installed `google-auth`/`grpcio` |
| A-03 | P1 | The nightly knowledge sync runs the **DB-index pipeline against GA4 connections**: `_active_connections` filters on `is_active` only → `to_config` decrypts the vendor secret for nothing → `get_connector("ga4")` raises `Unsupported adapter` → `indexing_status=failed` on the GA4 row, `any_failure=True`, `code_db_sync` skipped. The first real GA4 connection makes every nightly sync report failure | `daily_knowledge_sync_service.py:293, 375-383, 461, 484-521`; `connectors/registry.py:66`; manual routes guard it (`connections.py:1112, 1470`), the cron does not |
| A-04 | P2 | "Yesterday" is the scheduler's (`Europe/Berlin`) yesterday; GA4 evaluates `date` in the property's timezone → a US property's still-running day is collected at 03:00 Berlin, journalled `ok`, and published as "real measurements". Self-heals only via the tail; `refetch_tail_periods=0` makes it permanent | `analytics_collect_service.py:198, 813-817`; `adapter.py:342, 458`; `analytics_agent.py:1071-1076, 1189-1192` |
| A-05 | P2 | No per-connection collection mutex: `POST /collect` (10/min, per-second task id) plus the cron can run concurrently, each spending full quota; the route's docstring claims the opposite; interleaved sweep `DELETE`s are a plausible deadlock | `connections.py:1688, 1696-1700, 1726`; `main.py:1192`; `analytics_collect_service.py:285-389, 718-726` |
| A-06 | P2 | `query_report` `SUM`s every metric uniformly, including `active_users`, which is a distinct-user count per day — 30 summed days is not "active users last month" — and the tool description promises "metrics are summed" | `analytics_agent.py:842-846, 494-497`; `reports.py:87, 101, 113, 128, 141, 152` |
| A-07 | P2 | Journal prune (400 d by `fetched_at`) vs backfill windows up to 3650 d: pruned periods re-enter `pending` and are mass re-collected (~3000 vendor calls, past the 1800 s job timeout) every ~400 days | `journal.py:229-233, 119-124`; `source_types.py:50`; `connections.py:394-418` |
| A-08 | P2 | UI/prompt promise vs backend: reserved providers offered for credentials; LLM tool text names vendors that cannot exist; `GA4Config` docstring claims the UI nudges `event_names` but the form has no such field, so every GA4 connection collects **all** events; the form edits one property id and silently carries the rest | `vendor-credentials.ts:48-59`; `analytics_tools.py:30-37`; `ga4/config.py:68-70`; `ConnectionSelector.tsx:56-85, 494-505` |
| A-09 | P3 | `AnalyticsEmpty` on a refetched period leaves stale fact rows in place (sweep runs only inside `_upsert`) | `analytics_collect_service.py:521-531, 678` |
| A-10 | P3 | Connection model conflation: ORM default `db_host="127.0.0.1"` cleared only by the route validator; `is_read_only` hard-coded `True` for analytics; `send_sample_data_to_llm` ignored by the agent; `collection_*` on every database row; `ConnectionConfig.db_type` carries the vendor id — the root of `is_queryable_database`, `capability_of`, `_reject_analytics_source` and A-03 | `models/connection.py:41, 79-103`; `analytics_collect_service.py:774-778`; `analytics_agent.py:1085-1094` |
| A-11 | P3 | Quota memory is per adapter instance and per property; a project-wide bucket is recorded under the property that observed it | `adapter.py:258, 553` |
| A-12 | P3 | `has_analytics_sources` cache (60 s) never invalidated; credential lifecycle has no rotation/verify surface, no `last_verified_at`; a cold multi-year backfill is bounded only by the job timeout + a once-a-day task id, mints no `IndexingRun`, is invisible to `/sync-history` | `context_loader.py:59, 204-208`; `vendor_credentials.py`; `config.py:743`; `main.py:1192` |

**Architecture — what a second vendor breaks.** App Store Connect: `GET /v1/salesReports`
returns **gzip TSV** per day, auth is an **ES256 JWT** (`kid`, `iss`, `exp ≤ 20 min`) from a
`.p8`, dates are Pacific, and **404 means "no sales that day"**. Google Play: **UTF-16LE
CSV files in a GCS bucket**, one file per **month** rewritten daily, service-account auth,
no report API. What generalises: `AnalyticsSourceAdapter` (`analytics/base.py:79-131`),
error taxonomy, `retry_async`, the unused-by-GA4 `request_with_retry` (`http.py:241-304`),
journal, `CollectOutcome`, `AnalyticsPipeline`, the vendor-credential store, the 422 that
lifts itself when `FACT_TABLES_BY_SOURCE` gains a key. What is GA4-shaped: (1) `fetch`
= one call per period (Play's unit is a monthly file); (2) the natural-key head is
hard-coded `property_id` in the migration, the sweep scope, the agent and the report spec;
(3) shared `classify_response` maps 404 → invalid-request → *stop the report*, which for
ASC must be `AnalyticsEmpty`; (4) `GA4ReportSpec`/`GA4Field`, `REPORT_BINDINGS`,
`VENDOR_CATALOGUES` are GA4 types the agent binds at import; (5) `build_adapter` is an
if-chain; (6) the secret is one opaque string — ASC needs `key_id + issuer_id + .p8`;
(7) timezone rule is per vendor; (8) the form branch is `isGA4`. Full seam list in §6
PRJ-10.

**Tests.** 199 analytics unit tests + ~200 across agents/services/models/integration/
frontend — good breadth. Missing, each mapped above: google-auth refresh failure (A-02),
per-property journal consequence (A-01), nightly sync over a GA4 row (A-03), property
timezone (A-04), concurrent collections (A-05), non-additive sums (A-06), prune × window
(A-07), provider options ⊆ connectable vendors (A-08), `AnalyticsEmpty` sweep (A-09).

### 3.3 Codebase connection and synchronization

**How it works.** Four entry points reach `IndexingPipelineRunner.run`
(`knowledge/pipeline_runner.py:201`): the manual route (`repos.py:216`), webhook/poll,
the nightly `daily_sync` child (`daily_knowledge_sync_service.py:385-398`, which calls
`run_repo_index_task` **inline** inside the daily job), and direct enqueues from
`reconcile_embeddings`/reaper/orphan sweep. `_run_steps` (`:302`) is an ordered list of
17 steps; `STEP_RESUME_INTENT` (`:159-183`) says which are gated on the checkpoint
(`detect_changes`, `cleanup_deleted`, `project_profile`, `code_symbol_embed`,
`cross_file_analysis`) and which recompute (`ast_parse`, `graph_build` — in-memory state).
`save_incremental` merges by FILE (`code_graph_service.py:115-273`); `force_full` ⇒ full
walk, `save()` delete-then-insert, and **a `force_full` checkpoint is never resumed**
(`repos.py:693`) — every restart begins at `clone_or_pull`, blunted only by the document
cache. Nightly cron: hour-scoped Redis lock, `at=next_hour`, entitlement gate fail-open,
day-scoped task id, 7200 s ceiling covering repo + N × (db_index ≤ 1800 + sync)
(`main.py:916-1078`). Recovery: 30 s beats, reaper 60 s / 300 s, `_is_live`, requeue budget
2 per 6 h, orphan sweep at worker start. The CLAUDE.md asymmetry (incremental prune vs
full keep of unresolved edges) is **closed** — verified by
`test_graph_incremental_writes_a_delta.py` and `test_incremental_sees_the_whole_graph.py`.

| # | Sev | Finding | Evidence |
|---|---|---|---|
| S-01 | **P0** | `store_sync` hands the LLM's dict to two `Text` columns — sync broken since 2026-09-10 (§2.0.3 P0-A) | `code_db_sync_analyzer.py:242, 252-253`; `models/code_db_sync.py:41-42`; `code_db_sync_service.py:40-66` |
| S-02 | **P0** | pgvector `delete_by_source_path(kind=…)` is invalid under psycopg3 — every rebuild that reaches `generate_docs` fails (§2.0.3 P0-B) | `pgvector_store.py:302-313`; `pipeline_runner.py:~1335, ~1440, ~1768`; commit `bd256428` |
| S-03 | P1 | Three run kinds, three beat mechanisms, one right. `index_repo` beats `IndexingRun` unconditioned (correct); `db_index` beats `DbIndexSummary` only; `code_db_sync` beats `CodeDbSyncSummary` only; `daily_sync` parent beats `IndexingRun WHERE status='running'` — the status-conditioned shape removed from `pipeline_runner._hb` on 08-31 "and that is the whole point". Once reaped, the parent can never re-assert liveness and `run_for_project` skips `finish` on a terminal row, so a wrongly reaped daily sync stays `failed: stale run reaped` in `/sync-history` **forever, even when it completed**. Both parent reaps of 09-11/09-12 landed in the same sweep as a child reap — parent and child share one loop and one app-DB pool, and `heartbeat()` opens a fresh session per beat and swallows failures | `db_index_pipeline.py:425-430`; `code_db_sync_pipeline.py:69-74`; `daily_knowledge_sync_service.py:164-172, 197`; `run_coordinator.py:582, 616`; `core/heartbeat.py:41-53` |
| S-04 | P1 | The nightly wave bypasses the one-repo-index-at-a-time slot: `MAX_CONCURRENT_REPO_INDEXES=1` is enforced only inside the ARQ wrapper `run_repo_index`; the daily sync calls `run_repo_index_task` directly under `max_jobs=8`, and the wave enqueues every project of the hour in the same second. Latent on one project; N≥2 projects at one hour ⇒ N concurrent repo indexes on the dyno OPS-08 measured as unable to hold two | `worker.py:234, 262, 558`; `daily_knowledge_sync_service.py:398`; `main.py:998-1020` |
| S-05 | P1 | Private HTTPS repo credentials are plaintext at rest, served to **viewers**, journalled into `IndexingRunEvent.detail` (viewer-readable), logged, and in `.git/config` on disk. There is no token field — `provider=github|gitlab|…` can only work with `https://user:token@…`. Redaction of git errors comes from GitPython, not this repo, and no test pins it. Host-key policy is hard-coded `accept-new` ignoring `SSH_HOST_KEY_POLICY`; passphrase-stripped key material outlives a SIGKILL; `ProjectRepository` rows are dead configuration nothing clones | `repo_url.py:148`; `repos.py:~823`; `pipeline_runner.py:319-336`; `repo_analyzer.py:330-345, 470-524` |
| S-06 | P2 | A failed pipeline leaves its checkpoint `running`: `run()` catches every exception and records `pipeline_failed` but never sets `IndexingCheckpoint.status`; `_run_index_background` calls `mark_failed` only when `run()` *raises*, then proceeds to `_regenerate_overview` and the sync chain as if it succeeded → `is_indexing` true for 300 s, manual route 409, daily sync reports `checkpoint status=running` instead of the exception | `pipeline_runner.py:287-300`; `repos.py:766-776, 831, 243-245`; `daily_knowledge_sync_service.py:417` |
| S-07 | P2 | In-process fallback (no `REDIS_URL`: Compose, DO) has **no recovery** for `index_repo`: reaper requeue and orphan sweep call `enqueue` with no `coro_factory` → `None`; the orphan sweep runs only in `worker.startup`, never in the web lifespan. A web restart mid-`force_full` leaves the fingerprint marker asserting a rebuild that never happens | `stale_run_reaper.py:252`; `orphan_runs.py:~150`; `task_queue.py:216`; `worker.py:370`; `main.py:93-260` |
| S-08 | P2 | Multi-connection and repo-only projects are half-served: `_fetch_live_table_names` and `_maybe_autostart_sync_chain` use the **first** connection only; nightly sync loops connections sequentially inside one 7200 s job (4 × 1800 s `fetch_samples` exhausts the night); a project with a repository and **no** DB connection is never nightly indexed | `repos.py:630, 898-925`; `daily_knowledge_sync_service.py:132-134, 286` |
| S-09 | P2 | `_fetch_live_table_names` connects to the customer DB with no timeout, **before** the heartbeat opens — a hanging tunnel >300 s is reaped before the pipeline starts | `repos.py:722, ~760, 898-925` |
| S-10 | P2 | Interrupted checkpoints older than 24 h are deleted at every web boot (by `updated_at`); a run whose next night was skipped loses resume state on the next deploy | `main.py:120`; `CheckpointService.cleanup_stale` |
| S-11 | P3 | Resume pulls the working tree past the checkpoint's `head_sha`: `clone_or_pull` always re-runs while `detect_changes` is restored → docs stamped with the old sha describe newer file contents | `pipeline_runner.py:322-344` |
| S-12 | P3 | Residual inline work on the loop (seconds, not the 300 s class): binary pre-filter `open()` per changed file, `chunk_document` per doc, graph row materialisation, `existing_docs_map` holding every document's prose; up to three `CodeGraph` copies during incremental `graph_build`; three beat sessions every 30 s per `index_repo` run on a pooler with a hard ceiling | `pipeline_runner.py:413-421, 1050, 1362, 1446, 1707, ~1990-2100`; `code_graph_service.py:63-70, 429-432` |
| S-13 | P3 | DST arithmetic in both cron loops is wall-clock: spring-forward skips an hour, fall-back runs hour 2 during the repeated hour 1 | `main.py:1067, 1233` |
| S-14 | P3 | LLM cost surface: `generate_docs` (sem 3, doc cache, failure-ratio gate, **no absolute cap on docs or tokens per run**), `analyze_sync`, `validate_tables`, `_regenerate_overview` after every index *and* sync; the only gating budget is the owner preflight on the nightly path | `pipeline_runner.py:1068, 1281`; `code_db_sync_pipeline.py:282-284` |

**Architecture.** Not a DAG — an ordered list with implicit state: each step reads and
writes `_PipelineState` fields with no declared inputs/outputs; `STEP_RESUME_INTENT` is a
test-checked comment, not a mechanism; `run_manifests.py` is a *display* ordering separate
from execution. The checkpoint model is adequate for incremental runs and **inadequate for
full runs, which have no resumable state at all** — the most expensive run in the product
is the only one that restarts from zero. One `AsyncSession` is held open for a multi-hour
run. The two hourly waves are acknowledged copy-paste ("deliberately the same shape",
`main.py:1096`), ~120 lines each, so the 09-08 hour fix had to be applied twice. The
worker/web split is coherent in intent (`allow_in_process=False`) and leaky in practice:
`index_repo` runs on web in fallback mode, the orphan sweep exists only on the worker, the
memory slot only on the ARQ wrapper, BM25 rebuilt per process.

**Tests.** 1062 tests across knowledge/ops/services. Incident classes from CLAUDE.md still
without a regression test: (a) a beat that stops re-asserting after a wrong reap — none for
`daily_sync`; (b) any beat on `db_index`/`code_db_sync` `IndexingRun` rows inside a step;
(c) SQL text validity on the production vector backend; (d) LLM tool-call arguments not
matching their declared type; (e) fallback-mode recovery; (f) credential redaction in
journal/log strings.

### 3.4 Orchestrator

**How it works.** Three transports build one process-level `ConversationalAgent`
(`chat.py:63`): REST wraps `_agent.run` in `wait_for(360 s)` (`:407`); SSE runs it as a task
and relays events (`:1120-1226`, ceiling 480 s + 20 s grace); **WS awaits it with no
`wait_for`** (`:1869`). `OrchestratorAgent.run` (`orchestrator.py:766`): stale-result
sweep (`:778`), resume check (`:786`), capability probes (`:796-802`), `route_request` —
one LLM JSON call, `_DEFAULT_ROUTE` on any failure (`:818`; `router.py:311-313`),
`context = replace(context, extra={…route…})` (`:833`), `_wf_routing[wf_id]` (`:855`),
then `direct` / **Path B** `_run_complex_pipeline` (`:2403`, planner → `StageExecutor` with
≤3 parallel stages and one shared deadline → replans ≤2 → synthesis → gate) / **Path A**
`_run_tool_loop` (`:1246-2374`, 1130 lines: prompt assembly, 20-iteration loop with
step/time budget, dispatch, result folding, synthesis-on-exhaustion, answer gate, viz,
metrics, follow-ups, response). `_execute_resume` (`:3020-3179`) is a third tail.
Per-workflow state lives in eight dicts on the singleton (`:398-435`) drained by `pop_*`
and swept by age; a process-wide `Semaphore(2)` throttles tool calls for all users (`:436`).
Sub-agent contract: `BaseAgent.run(ctx, **kwargs)` hides five signatures; results consumed
via `getattr(result, "answer", "")`; only `SQLAgent` and `AnalyticsAgent` produce a
`QueryResult` — `search_codebase`, `analyze_git`, `query_mcp_source`, `analyze_results`
stages return summaries nothing downstream can compute on.

**Why the production traces look the way they do.**

- *`route='unknown'` on every failure.* Routing reaches the trace only via the normal
  return path (`core/agent.py:106-110`). The `except`/`finally` (`:115-127`) emit
  `pipeline_end failed` with no routing and no kind. The row that survives is written by
  the buffer flush (`trace_persistence_service.py:503-518`) with server defaults; the REST
  abnormal path finalizes a synthetic `unknown-{session}` id that cannot match the row
  (`chat.py:82-104, 436, 460`), the SSE disconnect finalizer returns without finalizing
  (`:891-916`), and **WS has no error finalization at all** (`:2067`). So a
  `failed + unknown` row is, by construction, a run killed from outside or one that
  outlived the trace buffer.
- *358 s against 180.* `wall_clock_start` is set at `orchestrator.py:1427`, after router,
  history summariser, retrieval and rules; it is checked only at iteration top (`:1471-1500`)
  with a hard break at 1.2× (`:1693`); `LLMRouter.complete` **has no deadline parameter**
  (`llm/router.py:300-370`: 3 attempts × 120 s HTTP timeout on OpenRouter + backoff =
  366 s for one call); Path B passes **nothing** to the SQL agent (`stage_executor.py:786`);
  Knowledge/Git/MCP/Analytics agents have no deadline parameter; the learning analyzer runs
  an LLM call after every `execute_query` (`sql_agent.py:595`); emergency synthesis, answer
  validator, viz (15 s), localize (12 s) follow. Realistic sum ≈ 330–360 s; structural
  worst case unbounded. Three outer retry wrappers can never fire because the router
  converts every failure into `LLMAllProvidersFailedError`, which is not in
  `RETRYABLE_LLM_ERRORS` (`router.py:427-445`; `errors.py:145-150`).
- *`failure_kind` NULL.* Two writers, both in `chat.py` (`:163-166`, `:445/:469/:1141`);
  the flush never sets it; `finalize_trace` writes it only when non-None (`:275-286`).
- *"Stale: pipeline_end never received".* `_cleanup_stale_buffers` evicts any buffer older
  than **300 s** (`trace_persistence_service.py:25, 560-599`), persists a synthetic failed
  end (duration = sweep tick, i.e. 300–360 s — **357.8 s is that number**), drops every later
  span, and a completed run keeps the error message and the `error_log` row. The threshold
  is below every transport ceiling (360 / 480 / ∞), so any request the transports permit to
  run past 5 min is recorded as failed and truncated. The client sees nothing.

| # | Sev | Finding | Evidence |
|---|---|---|---|
| O-01 | **P0** | Learning exposure/credit is dead on every request: `replace(context, extra={…})` at routing builds a **new dict**; sub-agents write `exposed_learning_ids` into copies; `ConversationalAgent.run` reads the original → `AgentResponse.exposed_learning_ids` always `[]`, `credit_validated_learnings` a no-op, thumbs-up/down attribution finds nothing, `times_applied` never moves (R4-1..3 inert). Tests assert on the ctx handed to the SQL agent, never on the response | `orchestrator.py:833-841`; `core/agent.py:92-94`; `sql_agent.py:264, 2172-2177`; `chat_feedback.py:77-121, 366-369` |
| O-02 | **P0** | `total_duration_ms` on every completed SQL answer is overwritten with the **last query's DB time**: `QueryResult.execution_time_ms` defaults to `0.0` (never `None`), all three transports pass it, `finalize_trace` writes any non-None. The 59 s "avg" for `query/simple` above must be re-derived from spans | `connectors/base.py:312`; `chat.py:623, 1424, 2003`; `trace_persistence_service.py:275-286` |
| O-03 | P1 | Killed runs leave a trace with no routing, no failure kind, (REST) a second orphan row; WS has no error finalization | `core/agent.py:115-127`; `chat.py:82-104, 436, 460, 891-916, 2067`; `trace_persistence_service.py:503-518` |
| O-04 | P1 | Requests over 300 s are recorded failed and lose the rest of their history (above) | `trace_persistence_service.py:25, 192-194, 560-599`; `config.py:977-978` |
| O-05 | P1 | 180 s is advisory: Path B stages and every non-SQL sub-agent run outside the shared deadline; `LLMRouter.complete` has no deadline; the dispatcher's 3 SQL-agent re-runs reuse one `remaining_wall_seconds` snapshot | `stage_executor.py:786, 230, 120-133`; `tool_dispatcher.py:48, 160, 513-560`; `router.py:300-370`; `openrouter_adapter.py:125` |
| O-06 | P1 | Finalization races the buffer flush: `_persist_workflow` is `create_task`ed on `pipeline_end`; `finalize_trace` does `SELECT … LIMIT 1` then INSERT → two rows per `workflow_id` (indexed, not unique); later `LIMIT 1` with no ORDER BY picks one arbitrarily | `trace_persistence_service.py:202, 243-249, 308-353`; `models/request_trace.py:40` |
| O-07 | P1 | `_cleanup_stale_results(300)` evicts **live** requests: `_wf_seen` is stamped once and never refreshed; a request past 5 min loses routing, SQL bucket (`process_data` then answers "no query results available"), correction count and suspicious flag as soon as any other request starts | `orchestrator.py:778-779, 806`; `tool_dispatcher.py:583-588` |
| O-08 | P1 | Cancellation is swallowed in viz (`except (Exception, CancelledError)`) and localize; a REST `wait_for` timeout does not stop the run — the tail completes after the handler returned 504 and released the limiter slot. No transport cancels on client disconnect (SSE hands the task to a 390 s background finalizer; WS observes disconnect only afterwards; REST is not cancelled by Starlette) | `orchestrator.py:2183-2190`; `localize.py:97-99`; `chat.py:427-451, 668-671, 1482-1493` |
| O-09 | P1 | The gate pipeline diverges across Path A / Path B / resume in ten places: `DataGate.check` never runs on Path A; Path B never sets `_wf_suspicious` (auto-investigate cannot fire for pipeline answers) and applies no result-gate correction budget; `AnswerQualityGate` conditional on A, always on B; truncation caveat in Python only on B; reconciliation scrub only on A; viz/follow-ups only on A; metrics vocabulary differs; resume records no metrics, no `_wf_plan`, passes `available_sources=None` | table in the working notes; anchors `sql_agent.py:1071-1122`; `stage_executor.py:466, 486, 830-880, 1415-1435`; `orchestrator.py:2043, 2092, 2248, 2633-2660, 3020-3179` |
| O-10 | P2 | SSE/WS latch onto the **first** `pipeline_start` in the project, not their own: a second request by the same user (3 allowed) or a background `index_repo` starting in the project makes the stream relay a foreign workflow, break on its end, cancel the real run and report "Request timed out" | `chat.py:1070-1073, 1166-1168, 1228-1247, 1602-1604` |
| O-11 | P2 | Exceptions become text the model reasons over, sometimes raw: SQLAlchemy error text (statement + parameters) from `manage_rules`/`list_rules`; `f"{type(exc).__name__}: {exc}"` for unknown exceptions mid-loop | `tool_dispatcher.py:1046-1048, 1074-1076, 1212-1216, 1322-1326`; `orchestrator.py:3629-3630` |
| O-12 | P2 | DB rows reach the orchestrator prompt undelimited: up to 50 rows as bare `" | ".join`, 200 aggregation rows, `rows[:5]`/`[:10]` in synthesis, samples in stage context; learnings, insights, planner-written descriptions and the user's `modification` injected verbatim with no size cap — the generic `untrusted_data_section` names them but nothing marks boundaries (BIZ-03's indirect-injection surface, still open at these sites) | `tool_dispatcher.py:437-470, 660-672`; `stage_executor.py:711-722, 1393-1397, 1405-1410, 1477-1487`; `stage_context.py:293-299`; `context_loader.py:352-357, 396-401` |
| O-13 | P2 | Nested retry surface: 20 × 3 × 10 × 3 with one time snapshot per orchestrator iteration; `process_data` parsed by two parsers from two shapes; two tool vocabularies (planner vs flat loop) — 5 tools only in A, 2 only in B | `tool_dispatcher.py:513, 526, 592-635`; `stage_executor.py:1236-1282`; `orchestrator_tools.py:321-358`; `query_planner._CREATE_PLAN_TOOL` |
| O-14 | P2 | The router's fallback is persisted as a real decision (`explore/moderate/2`); traces cannot distinguish "the router said explore" from "the router did not answer" | `router.py:57-63, 219-222, 311-338`; `orchestrator.py:855` |
| O-15 | P2 | Span time misattributed (`db_query` spans include LLM repair + learning-analyzer time); router backoff emits no event; `request_summary` logged only on success; `MetricsCollector` is an in-memory deque reset on restart | `sql_agent.py:378-396, 595`; `router.py:353, 367`; `orchestrator.py:2237-2247`; `metrics.py:56` |
| O-16 | P3 | Process-wide tool semaphore; `checkpoint` persisted as a failed trace + `error_log` row; `PipelineRun` left `executing` on any pipeline exception; `current_stage_idx` set to the batch's last stage before any runs (resume excludes siblings that never completed); auto-investigation consumes the **owner's** chat concurrency slot for 12 iterations; `_fallback_to_unified` re-enters `run()` and re-runs probes | `orchestrator.py:436, 1019, 2395, 2609-2612`; `trace_persistence_service.py:478-485`; `stage_executor.py:303-305`; `data_investigations.py:420` |

**Architecture.** `orchestrator.py` (3721 lines) is a composition root, a router, two
executors, a gate applier, a persistence layer, a metrics emitter and a response builder
in one class (line map in the working notes: `:362-445` composition, `:766-1006` run,
`:1246-2374` tool loop, `:2403-2675` pipeline, `:2990-3312` resume + persistence,
`:3314-3573` retry wrapper + two answer-gate entry points). Path A is a dynamic single-node
graph, Path B a static DAG, resume a third copy; the same sub-agents, gates, deadline,
trace and response shape, implemented three times with the divergences in O-09. Budgets
are three clocks that do not talk and none reaches the LLM router. Tool definitions are
five lists cross-checked by a test after the fact. The eval harness (`backend/app/eval/`)
measures retrieval precision/recall and code-graph quality; it can measure **neither**
routing accuracy, plan quality, gate precision/recall, latency against budget, nor
end-to-end answer correctness, and there is no replay over `request_traces.plan_json` +
spans.

**Tests.** 43 files, strong on the happy paths and the recorded ORCH-* fixes. Untested
failure modes: a sub-agent that outlives a deadline it was never given; a request cancelled
inside viz or localize; two concurrent requests where one exceeds 300 s; a WS request that
raises; a checkpoint's trace/error-log side effect; exposure ids across the `replace()`
boundary; two rows with one `workflow_id`; client disconnect mid-run (no test cancels the
agent task or asserts LLM/DB work stops); SSE latching onto a foreign `pipeline_start`.

---

## 4. Cross-cutting architecture assessment

Five patterns account for most of the 60 findings above. Naming them matters more than
any single fix, because the next feature will repeat them unless the shape changes.

1. **The truth is computed from the input, not the outcome.** A status written before the
   work is checked (S-03 parent stays `failed` after completing; O-14 default route stored
   as a decision; A-01 `ok` for a period one property missed; S-06 checkpoint `running`
   after failure). The 09-09 audit named this as R3; it is still the dominant shape.
2. **A beat on the wrong row.** Four run kinds, four heartbeat writers, three of them
   ticking a row the reaper does not read (S-03, C-01). CLAUDE.md records the same trap
   twice already. The fix is structural — one `RunBeat(run_id)` — not another patch.
3. **Boundaries that do not carry the contract.** `replace()` copies lose writes (O-01);
   deadline not threaded through `AgentContext` → sub-agents → `LLMRouter` (O-05); `TraceMeta`
   not on the `pipeline_end` event (O-03); `user_id` semantics differ per call site (C-04);
   tool-call argument types trusted from the model (S-01). Each is a value that should
   travel on the object that crosses the boundary and instead travels by convention.
4. **Type-keyed if-chains instead of a registry.** Twelve dialect lists (§3.1);
   `build_adapter` if-chain and `FACT_TABLES_BY_SOURCE` dict (§3.2); two tool
   vocabularies and two `process_data` parsers (O-13); two copy-pasted hourly waves (§3.3).
   Adding an engine, a vendor or a tool means finding every list.
5. **Remediation without a dialect-true test.** Both P0s were introduced by remediation
   work and passed CI: one because the test fixture mirrored the schema rather than a
   model, one because no test executes SQL text on the production vector backend. The
   guard the programme needs is not more tests of the same shape but tests against the
   *runtime* that differs from dev: psycopg, asyncpg, a model that returns objects.

---

## 5. Improvement plan — each item a standalone project

Fourteen projects. Each is sized so one engineer (or one `task-pipeline` run) can carry it
from spec to production without another project in flight, has a measurable acceptance
gate, and names what it deliberately does not do. Sizes: **S** ≤ 2 engineer-days,
**M** 3–7, **L** 8–15, **XL** > 15 (phased). Order in §5.15. Every project that touches
user-facing behaviour updates `docs/ux/scenarios.md` in the same change; every one ships
through `/task-pipeline` with its own CHANGELOG entry added in the merge pass, not on the
branch (see the conflicted-PR note in CLAUDE.md).

### PRJ-01 — Production hotfix wave (S, ship first, one PR)

- **Goal.** Restore the two broken production paths and the two silent orchestrator
  corruptions within one deploy, each with a test that fails on `main` today.
- **Scope.** (1) S-01: coerce `required_filters`/`column_value_mappings` (and any future
  JSON-ish arg) in one helper — `json.dumps` when not `str`, `json.loads` round-trip
  validation, invalid → `"{}"` + WARNING. (2) S-02: `LIKE 'sym:%%'` or bind the pattern;
  add a psycopg compile test for both `kind` branches. (3) O-02: pass
  `total_duration_ms=None` at `chat.py:623, 1424, 2003` (three one-line edits).
  (4) O-01: mutate `context.extra` in place at `orchestrator.py:833` (or drain
  `exposed_learning_ids` via `_wf_*`/`pop_*` like routing) and assert on
  `AgentResponse.exposed_learning_ids` in `test_agent.py`.
- **Out of scope.** Anything structural; the heartbeat work (PRJ-02).
- **Acceptance.** Four new tests red on `main`, green on the branch. After deploy: a
  hand-enqueued `force_full` re-index of `esim-php` reaches `pipeline_end`; the next
  `code_db_sync` completes (`indexing_runs.status='completed'`, `code_db_sync.updated_at`
  moves); a thumbs-up on a SQL answer increments `times_applied`; a new completed trace
  has `total_duration_ms ≈ SUM(trace_spans.duration_ms)`.
- **Post-deploy ops (done by the engineer, not handed over).** Enqueue the rebuild, watch
  for `pipeline_end`, confirm the sync row, record the four measurements in the PR.
- **Risk.** A full rebuild of `esim-php` needs an uninterrupted ~1.5 h window (warm doc
  cache) — do not merge anything else to `main` until it finishes.

### PRJ-02 — Run liveness: one heartbeat, one truth (M)

- **Goal.** No run kind can be reaped while its process is alive, and no reaped run stays
  `failed` after completing. Closes S-03, C-01, S-06, S-09, part of S-12.
- **Scope.** A single `RunBeat(run_id)` writer (reuse `run_coordinator._run_beat`) that
  ticks `IndexingRun.heartbeat_at` by id, **unconditioned on status**, used by
  `db_index_pipeline`, `code_db_sync_pipeline`, the `daily_sync` parent and the repo
  index; drop the three summary-row-only beats (keep the summary rows' own `heartbeat_at`
  as a derived field or remove it). Make `run_for_project` call `_reconcile_reaped_run`
  when the parent was reaped. Open the heartbeat before `_fetch_live_table_names` and give
  that call a timeout. On pipeline failure set `IndexingCheckpoint.status`, stop the
  overview/sync chain, and surface the exception in `_repo_index_outcome`. Log
  `heartbeat writer failed (N consecutive)` at WARNING so pool exhaustion becomes visible.
- **Out of scope.** Changing reaper timeouts; the pipeline DAG (PRJ-06).
- **Acceptance.** Tests: for each of the four run kinds, a stalled step >`timeout` with a
  live task keeps `IndexingRun.heartbeat_at` advancing; a beat after a reap flips nothing
  but re-asserts; a `daily_sync` parent reaped then completed reads `completed` in
  `/sync-history`. Production: 14 days after deploy, `error_log` shows **zero**
  `stale run reaped` rows for runs that later emitted `pipeline_end`.
- **Dependencies.** None. **Risk.** Low; the shape already exists for `index_repo`.

### PRJ-03 — One request deadline, honoured everywhere (M)

- **Goal.** `agent_wall_clock_timeout_seconds` becomes a bound, not advice. Closes O-05,
  O-08, O-13 (time part), O-07.
- **Scope.** Add `deadline: float | None` to `AgentContext`, established once per request
  before routing (so pre-loop LLM calls count); thread it into every sub-agent `run()`
  (SQL, Knowledge, Git, MCP, Analytics, Investigation, Viz) and into
  `LLMRouter.complete(..., deadline=)`, which clamps each attempt's HTTP timeout to
  `min(adapter_timeout, remaining)` and refuses to start an attempt with < N s left; Path B
  passes the pipeline deadline into `_run_sql_stage`; the dispatcher re-measures
  `remaining` between its retries. Remove the `CancelledError` swallows in viz and
  localize; make REST's `wait_for` timeout and SSE/WS client disconnect **cancel** the
  agent task (SSE background finalizer bounded by the same deadline). Move the eight
  `_wf_*` dicts into a per-request `RequestState` on the context (or a ContextVar) and
  delete the age sweep. Delete the three dead retry wrappers or make them reachable.
- **Out of scope.** Trace content (PRJ-04); path unification (PRJ-05).
- **Acceptance.** Tests: a sub-agent handed 2 s remaining returns within 3 s; an LLM stub
  that hangs is cut at the deadline on both paths; `wait_for` timeout cancels the task
  (no `tracker.end completed` afterwards); two concurrent requests, one >300 s, neither
  loses state. Production: 30 days after deploy, `MAX(total_duration_ms)` over completed
  and failed traces ≤ `agent_wall_clock_timeout_seconds × 1.2` + tail allowance, and no
  trace > `stream_timeout_seconds`.
- **Dependencies.** PRJ-01 (O-02) for the duration figure to be trustworthy.

### PRJ-04 — Trace truth and failure taxonomy (M)

- **Goal.** Every request — completed, failed, killed, disconnected — leaves exactly one
  `request_traces` row whose `route`, `complexity`, `failure_kind`, `error_message` and
  `total_duration_ms` are what happened. Closes O-03, O-04, O-06, O-14, O-15, O-16
  (checkpoint), and answers "why did this take 90 s".
- **Scope.** Carry `TraceMeta` (routing tuple, failure kind, exposure ids, "router
  defaulted" flag) on the `pipeline_end` `WorkflowEvent.extra` so `_persist_workflow`
  writes it; make `ConversationalAgent.run`'s `finally` drain routing into that event;
  make `RequestTrace.workflow_id` UNIQUE and `finalize_trace` an upsert (no
  `SELECT … LIMIT 1` race); remove the synthetic `unknown-{session}` id; add WS error
  finalization; raise `_STALE_BUFFER_SECONDS` above the largest transport ceiling and mark
  the buffer provisional instead of failed; map `checkpoint` to its own status, not
  `failed`; classify `failure_kind` from the stage classifier and the exception type at
  the point of failure; split the `db_query` span from the LLM repair and learning-analyzer
  spans; emit router attempt/backoff events; log `request_summary` on every terminal.
- **Out of scope.** Persisting `MetricsCollector` (belongs with PRJ-13).
- **Acceptance.** Tests: REST timeout, SSE disconnect + raise, WS raise, orchestrator raise
  and stale-buffer eviction each leave one row with non-`unknown` route and a non-NULL
  kind; a completed run never carries `Stale: …`. Production: 30 days after deploy,
  `COUNT(*) WHERE route='unknown' AND status='failed'` is 0 and
  `COUNT(DISTINCT workflow_id) = COUNT(*)`.
- **Dependencies.** PRJ-03 (the deadline gives the failure kinds a meaning).

### PRJ-05 — One executor, one gate pipeline (XL, phased)

- **Goal.** Path A, Path B and resume become one `GraphExecutor` over a typed node
  contract with a declared `GatePipeline`, so O-09's ten divergences cannot exist.
- **Phases (each independently shippable, behaviour-preserving).**
  1. Extract `_run_tool_loop` into `assemble_prompt / iterate / fold_results / finish`
     with the same locals as arguments; reuse `finish` (answer gate, viz, follow-ups,
     metrics, response) for Path B and resume. Closes the viz/follow-up/metrics halves of
     O-09.
  2. One `ToolRegistry` entry per tool (declaration, pydantic argument model, handler,
     budget class, dedup key) consulted by both `get_orchestrator_tools` and the planner's
     `_CREATE_PLAN_TOOL`; one `process_data` parser. Closes O-13; the argument model is
     also where S-01's class dies for chat tools.
  3. Typed `NodeResult(table: QueryResult | None, text, failure: Failure(kind, message) | None)`
     returned by every sub-agent; `StageResult` and the flat-loop tool message derived from
     it; `search_codebase`/`analyze_git`/`query_mcp_source`/`analyze_results` populate
     `table` where they have rows. Closes the "nothing downstream can compute on it"
     property.
  4. `GatePipeline = [ResultValidation, DataGate, StageValidator, LayerChecker,
     AnswerQualityGate, TruncationCaveat, ReconcileAndScrub, Localize]` applied by the
     executor at every terminal on every path; `_wf_suspicious` set from the pipeline path
     too. Closes O-09.
  5. `GraphExecutor` runs both a static plan and the incremental "ask the model, run the
     chosen tools" plan through one node interface; delete `_execute_resume` as a separate
     tail; fix `current_stage_idx` bookkeeping for parallel batches; persist `PipelineRun`
     on failure.
- **Out of scope.** New agent capabilities; prompt wording.
- **Acceptance.** Per phase: the existing 43 orchestrator test files stay green and a new
  parity test asserts the same gate set ran on A, B and resume for the same fixture
  question. End state: `orchestrator.py` < 800 lines; a test enumerates tools from the
  registry and fails if any handler, schema or planner vocabulary entry is missing;
  `agent-evals`-style trajectory fixtures (PRJ-13) pass unchanged across the phases.
- **Dependencies.** PRJ-03 and PRJ-04 first (they define the budget and record objects the
  executor carries). **Risk.** Highest in the plan; the phasing is the mitigation.

### PRJ-06 — Indexing pipeline as a declared DAG with a resumable full rebuild (L)

- **Goal.** Steps declare `reads`/`writes`/`resume: GATED | RECOMPUTE`; a runner enforces
  `writes ⊆ persisted` before skipping a GATED step; the full rebuild resumes. Closes
  S-06, S-10, S-11, S-12, S-14 (cap), and the "ordered list with implicit state" assessment.
- **Scope.** `Step` objects replacing the 1250-line `_run_steps`; `generate_docs`,
  incremental `graph_build`, the beat writer and `_record_and_finish` extracted to their
  own modules; per-step sessions instead of one multi-hour `AsyncSession`; checkpoint
  records `head_sha` of the tree the steps ran against and `clone_or_pull` checks it out
  on resume (S-11); a `force_full` checkpoint **is** resumable — `save()` becomes
  "delete what the previous full attempt did not rewrite" keyed by run id, so a rebuild
  interrupted at 63% continues from 63%; checkpoint cleanup by `updated_at` extended to
  "older than the next scheduled run + 24 h"; the display manifest generated from the step
  list; an absolute per-run cap on generated docs/tokens with a `partial` outcome instead
  of an unbounded bill; `to_thread` for the four inline loops in S-12.
- **Out of scope.** New extractors; retrieval changes.
- **Acceptance.** Tests: a step whose `writes` are not persisted cannot be skipped on
  resume; a `force_full` run killed after `generate_docs` resumes at `code_symbol_embed`
  (counted operations, not time); the graph produced by "full" equals "interrupted full +
  resume" on the fixture repo. Production: a deliberately interrupted full rebuild of
  `esim-php` completes in `< 0.5 ×` the cold time on the second attempt.
- **Dependencies.** PRJ-02. **Risk.** Medium; the checkpoint tables already exist.

### PRJ-07 — Scheduling and recovery that work in every deployment (M)

- **Goal.** The nightly wave respects the memory slot, serves every project shape, and the
  recovery machinery works without Redis. Closes S-04, S-07, S-08, S-13, A-03, and the two
  copy-pasted waves.
- **Scope.** One `HourlyWave(name, select_due, enqueue)` used by both waves (and the DST
  fix applied once, via `zoneinfo`-aware next-hour computation); acquire
  `_repo_index_slots` inside `run_repo_index_task`; the daily sync skips analytics
  connections with a recorded `skipped` reason (A-03), loops **all** connections for the
  live-table cross-reference and the sync chain, runs per-connection `db_index` as
  separate child jobs with their own ceilings (so four connections do not share one
  night), and indexes repo-only projects; in-process fallback registers `coro_factory`s for
  every job the reaper/orphan sweep re-enqueues and runs the orphan sweep in the web
  lifespan too.
- **Acceptance.** Tests: two projects at one hour ⇒ one repo index at a time; a GA4
  connection in a project ⇒ nightly `daily_sync` `completed` with a `skipped` child;
  a repo-only project appears in the wave; fallback mode: a reaped `index_repo` is
  re-enqueued and an orphaned one is put back on web restart; both waves share one
  implementation (a test imports the class from both call sites). Production: `daily_sync`
  failure rate over 14 days < 5% and every failure carries a real error.
- **Dependencies.** PRJ-02.

### PRJ-08 — Connection layer correctness (M)

- **Goal.** The MySQL-over-SSH path and its siblings stop failing for reasons the user
  cannot see. Closes C-02…C-15.
- **Scope.** Touch the tunnel from `execute_query`/`introspect_schema` (idle = no
  ref-holder has *queried*); one retry policy at one layer with a route-level deadline on
  `/test`, retrying on the drivers' actual exception types; wrap forwarded-hop connect
  errors with `via SSH tunnel <bastion> → <db_host>:<port>` and force-recreate the tunnel
  once; `KeyImportError` → immediate, named failure; percent-decode DSN credentials and
  refuse a user-less DSN; ClickHouse `introspect_schema`/`test_connection` through
  `_get_client()` + `reconnect()`; ssh-exec `schema=db_name` for MySQL/ClickHouse and
  `error_type=TIMEOUT`; Mongo per-collection isolation recorded as a completeness gap;
  **delete `EXEC_TEMPLATE_PRESETS`** and serve the server's own templates read-only;
  return `ssh_command_template`/`ssh_pre_commands` to owners only; `ConnectionUpdate`
  typed like `ConnectionCreate`; SSH-key resolution semantics decided once (read sites pass
  `None`; write sites verify) and a two-owner test; frontend: engine-aware default port,
  DSN-and-tunnel warning at form time, `params` honoured in exec mode; delete the dead code
  in C-16.
- **Acceptance.** One test per row C-02…C-15 (the audit names the shape of each);
  Vitest asserts the form never sends `{db_password}`; production: a `db_index` longer than
  30 min on the tunnelled MySQL completes with zero `sample_failed`.
- **Dependencies.** None. Scenarios `SCN-0xx` for the connection form updated in the same
  change.

### PRJ-09 — Connector contract and fifth-engine readiness (L)

- **Goal.** One dialect registry, a contract-test matrix every engine passes, real-driver
  integration tests in CI, and a credential model a warehouse fits. Closes the
  twelve-lists assessment and the SQLite conflation.
- **Scope.** `Dialect` objects (quoting, comment/quote lexing, no-order hint, error
  patterns incl. **sqlite**, exec template, output parser, default port, DSN scheme) in one
  registry consumed by backend and served to the frontend; `DatabaseAdapter` contract test
  matrix (reconnect, `error_type` on timeout, `params`, `TableInfo.schema` semantics,
  truncation flag, read-only session) run against all six adapters; `testcontainers`-based
  integration tests for Postgres, MySQL, ClickHouse, MongoDB in a nightly CI job (not the
  PR gate); demo-SQLite concerns moved out of `to_config` and the connector package into
  the demo service; credential shape for a fifth engine reuses `vendor_credential_id +
  source_config_json` (a design note, `docs/adr/0005-…`), with BigQuery as the worked
  example but **not** implemented here.
- **Acceptance.** Adding a mock sixth dialect requires touching exactly one registry file
  (a test counts the sites); the contract matrix is green for all six; nightly CI runs the
  four real drivers; `grep -c "db_type ==" app/` falls below a ratcheted ceiling.
- **Dependencies.** PRJ-08 (so the matrix starts green).

### PRJ-10 — GA4 tells the truth (M)

- **Goal.** The first real GA4 connection behaves as documented. Closes A-01, A-02, A-04,
  A-05, A-06, A-07, A-08 (GA4 half), A-09, A-11, A-12.
- **Scope.** Journal per `(connection, report, period, property_id)` or a non-done
  `partial` status for a period with any failed property (keeps rows, stays pending);
  `RefreshError`/`GoogleAuthError` (direct, `__cause__`, or the INTERNAL "metadata plugin"
  text) → `AnalyticsAuthError`, and `test_connection` performs one real `refresh()` so a
  dead key lands on the `_connect` sentinel; property timezone read once (Admin API) or a
  `property_timezone` knob, "yesterday" computed per property, tail periods marked
  `provisional` in the journal and caveated; Redis `redis_lock` per connection around
  `collect_in_session`, docstring corrected; `additive: bool` on `GA4Field`, non-additive
  metrics never summed across periods (per-period rows or a deterministic caveat); prune by
  period age, never inside any connection's current window, `backfill_days` ≤ retention;
  `AnalyticsEmpty` on a refetched period deletes that period's rows; project-wide quota
  recorded project-wide; `has_analytics_sources` cache invalidated on connection
  create/delete; `last_verified_at` on credentials and a `POST /verify`; a collection run
  mints an `IndexingRun` so it appears in `/sync-history`; UI exposes `event_names`,
  `currency_code`, all property ids.
- **Acceptance.** One test per finding (the audit names each); an end-to-end fixture with
  two properties where one dies keeps the period pending and the surviving rows; a revoked
  key stops the report on the first period and sets the sentinel. Production: cannot be
  measured until a GA4 connection exists — the acceptance is a **staging** connection to a
  real property (operator provides credentials) collected for 3 nights with `ok` on every
  period and the agent's coverage line matching the journal.
- **Dependencies.** PRJ-07 (A-03) should land first or together.

### PRJ-11 — Vendor abstraction + App Store Connect (L)

- **Goal.** A second vendor exists and the third costs a fraction of the second.
  Delivers BACKLOG 11.1.
- **Scope.** Lift `FieldSpec(column, kind, additive)`, `FactTableSpec(entity_column,
  natural_key, …)` and `ReportSpec(grain, unit: per_period | file_of_periods)` into
  `analytics/base.py`; derive the collector's fact table and the agent's `ReportBinding`
  from them; adapter-owned status classification (404 ⇒ `AnalyticsEmpty` for ASC); an
  `ADAPTER_REGISTRY` keyed by source type replacing `build_adapter`'s if-chain; structured
  per-provider secrets (`{key_id, issuer_id, p8}`) with validation (PEM parse, key-id
  shape); a per-vendor "data available for date D at time T" rule; frontend per-vendor
  field sets driven by a backend-published schema so the UI cannot promise what the
  backend refuses. Then `AppStoreConnectAdapter`: ES256 JWT (`exp ≤ 20 min`, refreshed),
  `salesReports` DAILY SALES/SUMMARY gzip-TSV, subscription and subscription-event
  reports, finance reports by fiscal period, FX via a pinned source, fact tables with
  `(vendor_number, sku|apple_id, country, currency, date)` natural keys, `Numeric` money.
  Remove the App Store credential option from the UI **until** this lands; scope the LLM
  tool description to `VENDOR_CATALOGUES`.
- **Acceptance.** Existing 199 GA4 tests green through the abstraction; a fixture ASC TSV
  round-trips to fact rows and an agent answer; a 404 day journals `empty`; contract tests
  run against both adapters; staging connection to a real ASC account collected for 3
  nights. Scenarios SCN-119 rewritten from "refused" to the ASC flow.
- **Dependencies.** PRJ-10.

### PRJ-12 — Google Play (M, after PRJ-11)

- **Goal.** Delivers BACKLOG 11.2 on the abstraction PRJ-11 built.
- **Scope.** GCS transport (service account, `objects.list` on the bucket as
  `test_connection`), monthly UTF-16LE CSV files as `file_of_periods` reports (installs,
  earnings, subscriptions, crashes/vitals via Play Developer Reporting API), natural keys
  on `(package_name, dimension…, date)`, refetch of the current month's file daily.
- **Acceptance.** Fixture CSVs round-trip; a rewritten month file upserts without
  duplicates; staging connection 3 nights.
- **Dependencies.** PRJ-11.

### PRJ-13 — Orchestrator eval harness (M)

- **Goal.** "Did the orchestrator get better" becomes a number. Extends
  `backend/app/eval/` from retrieval to trajectories, per the `agent-evals` doctrine.
- **Scope.** Turn `request_traces.plan_json` + `trace_spans` into replayable fixtures
  (recorded LLM responses); score routing accuracy against a labelled set, plan validity,
  gate precision/recall (`requery`/`block`/`warn` verdicts vs labelled outcomes), latency
  vs budget, and end-to-end answer correctness on the golden questions; a CI gate on the
  offline set and a nightly run on the last day's production traces; persist
  `MetricsCollector` counters to Postgres so replans and route distribution survive a
  restart (the Ш0b gap).
- **Acceptance.** The harness reproduces the 8 failed production traces as fixtures and
  each PRJ-03/04/05 phase moves at least one of them to a scored pass; CI fails on a
  routing-accuracy drop > 5 points.
- **Dependencies.** PRJ-04 (trace content).

### PRJ-14 — Runtime-true guard tests (S, standing)

- **Goal.** The class of both P0s cannot recur silently. Closes §4 item 5.
- **Scope.** (1) A test that compiles every SQL string passed to psycopg in `app/` (AST
  walk for `conn.execute(` / `cur.execute(` literals) through `psycopg.sql` or a regex for
  unescaped `%` outside placeholders. (2) A test that every LLM tool schema's declared
  argument types are enforced by a coercion layer before use (`code_db_sync_analyzer`,
  `learning_analyzer`, `adaptive_planner`, `router`, all flat-loop tools) — the model may
  return an object for a `string`. (3) A CI job running the unit suite against Postgres
  (asyncpg) as well as SQLite so `Text` vs dict, `Numeric` vs float and JSON-column
  differences surface. (4) Redaction tests for `repo_url` in journal events, logs and API
  responses (S-05's test half). (5) Fallback-mode recovery tests (S-07).
- **Acceptance.** Planting either P0 on a branch turns CI red.
- **Dependencies.** None; ship alongside PRJ-01.

### 5.15 Sequencing

```
week 1   PRJ-01 hotfix ──► PRJ-14 guards          PRJ-02 liveness
week 2-3 PRJ-03 deadline ──► PRJ-04 trace truth   PRJ-08 connections    PRJ-07 scheduling
week 4-6 PRJ-05 executor (phases 1-2)             PRJ-06 pipeline DAG   PRJ-10 GA4 truth
week 7-9 PRJ-05 (phases 3-5)  PRJ-13 evals        PRJ-09 contract       PRJ-11 App Store
later    PRJ-12 Google Play
```

Three tracks can run in parallel (orchestrator: 03→04→05→13; indexing: 02→06/07;
sources: 08→09, 10→11→12) because they touch disjoint modules; the only shared file is
`chat.py` between PRJ-03/04 and nothing else. Total: roughly 60–80 engineer-days, of which
PRJ-01 + PRJ-02 + PRJ-14 (≈ 6 days) remove every production-visible failure in this
report.

### 5.16 What this plan deliberately does not include

- **Reranker, clustering, connector expansion beyond readiness (BigQuery/Snowflake
  implementation), public dashboards, seats** — product decisions in the N1–N11 backlog,
  unchanged by this audit.
- **Raising `EMBEDDING_UPSERT_BATCH_SIZE`** — CLAUDE.md records why 16 stays untested.
- **A Redis lock for repo-index exclusion** — the DB partial unique index already enforces
  it (T07); PRJ-07 fixes the *memory slot*, which is a different constraint.
- **Prompt wording** — O-12's delimiting is a structural change (fences around every
  untrusted block) and belongs in PRJ-05 phase 3, not a prompt edit.

---

## 6. Handoff

- **Objective.** Audit of four subsystems + improvement plan (this document).
- **Completed.** Production measurement (§2), four verified subsystem readings (§3),
  cross-cutting assessment (§4), fourteen scoped projects with acceptance gates (§5).
- **Open.** Everything in §5; nothing has been fixed. Two P0s are live in production
  **today**: the code↔DB map has not updated since 2026-09-09 and any repository re-index
  that reaches `generate_docs` fails.
- **Decisions recorded.** BACKLOG.md Sprint 11 row 11.0 is closed by evidence (§3.1) — mark
  it `done` in the same change that starts PRJ-08. The report is Markdown in `docs/audits/`,
  not HTML, per the operator's standing rule.
- **Prerequisites for the next agent.** `heroku` CLI logged in with access to
  `checkmydata-api`; `psql`; the queries used are reproducible from §2 (connections by
  type; `indexing_runs` by kind/status over 14 days; `request_traces` over 30 days;
  `error_log` over 14 days).
- **Checks actually run.** Production SQL (above); `heroku ps/config/releases`;
  `curl /api/health` → `{"status":"ok"}`; `git log -S"sym:%'"` → `bd256428`; both P0 lines
  read by a second reader. **No test suite was run** — this audit changes no code.
- **Exact next task.** Start PRJ-01 through `/task-pipeline`: branch
  `fix/production-hotfix-wave` from `main`; write the four failing tests first
  (`tests/unit/knowledge/test_code_db_sync_analyzer.py` with an LLM stub returning
  objects; a psycopg compile test for `pgvector_store.delete_by_source_path`;
  `tests/unit/test_agent.py` asserting `response.exposed_learning_ids`; a
  `finalize_trace` test that `total_duration_ms` survives a SQL answer); fix; CI; merge;
  then enqueue the `esim-php` rebuild and record the four post-deploy measurements in the
  PR before closing it. **Do not merge anything else to `main` while that rebuild runs.**
