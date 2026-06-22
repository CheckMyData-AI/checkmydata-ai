# Synchronization & Observability Redesign — Design Spec

- **Date:** 2026-06-22
- **Status:** Draft (awaiting user review)
- **Authors:** brainstorming session (sshlg + Claude), multi-lens engineering audit
  (senior-architect, database-schema-designer, senior-data-engineer,
  observability-designer, senior-ml-engineer, agent-designer, senior-prompt-engineer,
  senior-data-scientist)
- **Supersedes / extends:** `2026-06-19-knowledge-pipeline-visibility-design.md`,
  `2026-06-21-sync-workflow-reliability-design.md`,
  `2026-06-21-orchestrator-hardening-design.md`
- **Constraint:** **Greenfield — no backward compatibility.** The project has no
  external consumers of these contracts yet. We collapse fragmented state into a
  single canonical model, promote progress to first-class event fields, and remove
  all legacy fallbacks and feature-flag gating for the new path.

---

## 1. Problem statement

Triggering a repository / database / code-DB sync index from the UI produces a green
toast and then **no further feedback**: no progress, no live steps, no logs, no
confirmation that work is happening. Background runs are invisible in the database
(no history, no persisted errors), while the agent query lifecycle *is* persisted
(`request_traces`/`trace_spans`) — an asymmetry that makes the product feel broken.

The user wants a synchronization + observability system that "works like a Swiss
clock": every run is immediately visible with stepwise progress and percentage,
cancellable, retryable, persisted with logs and errors, queryable with filters,
and governed by measurable reliability targets. Scheduled sync must fire reliably
and be visible. The agent must correctly build queries, work with data, validate
data, handle errors, answer, converse, and invoke data-search — and every one of
those steps must be logged to the database and surfaced with filters.

## 2. Current-state audit (grounded in code)

### 2.1 Background runs (index_repo / db_index / code_db_sync / daily_sync)

| Concern | Current reality | File |
|---|---|---|
| Lifecycle state | Derived on the fly from **three unrelated records** (`IndexCheckpoint`, `DbIndex` status, `Sync` status) | `services/pipeline_status_service.py` |
| Single-active guard | **Two divergent models**: in-process `asyncio.Lock` + `_indexing_tasks`; ARQ via checkpoint `status=='running'` | `api/routes/repos.py:192`, `api/routes/connections.py` |
| Correlation id | ARQ path returns `workflow_id: null`; real id minted later in worker | `api/routes/repos.py:262-269` |
| Progress | None — only step name via SSE; no `N/M`, no `%` | `core/workflow_tracker.py` |
| Cancel / retry | None | — |
| Persistence | **None.** Runs emit ephemeral SSE only; history exists for sync only (daily-sync audit) | — |
| Errors | `checkpoint.error` + logs; not a queryable record | `api/routes/repos.py:556-565` |
| Live delivery | 3 channels with independent truths: SSE `useGlobalEvents`, poll `pipeline-status`, poll `tasks/active` | `hooks/useGlobalEvents.ts`, `hooks/useKnowledgePipelineStatus.ts` |
| UI feedback | Toast only; banner gated on 30 s idle poll (`IDLE_POLL_MS`); no inline progress | `components/knowledge/KnowledgeHealthPanel.tsx` |
| Cross-process bridge | Works (worker `enable_cross_process_publish` → Redis → API `start_workflow_event_subscriber` → `broadcast_external`), but `WorkflowEvent(**payload)` throws on unknown keys → silent drop risk | `core/workflow_events.py`, `core/workflow_tracker.py:352` |

### 2.2 Agent query lifecycle

Already persisted at `pipeline_end` to `request_traces` + `trace_spans` via
`TracePersistenceService`, exposed by a filterable `/logs` API (users, requests,
trace detail, summary). Spans carry `span_type` (llm_call | db_query | rag |
tool_call | sub_agent | viz | validation | other), token usage, previews. Stages
classify failures as `transient | configuration | data_missing | fatal`
(`stage_executor`). Gaps: failure persistence is per-trace only (no dedup'd error
catalog); background runs are absent from this telemetry; no cross-cutting error
view; no "replay/debug" affordance.

### 2.3 Scheduled sync

`daily_sync` runs from a cron loop (`main.py:_daily_knowledge_sync_cron_loop` →
`_dispatch_daily_knowledge_sync_wave`, redis-locked) enqueuing
`run_daily_project_knowledge_sync` per project. It `tracker.begin("daily_sync")` /
`end` but, like other background pipelines, leaves **no persisted run record** and
is **not visible** in the UI as a schedule with history.

## 3. Multi-lens findings → design principles

- **Architect** — introduce a canonical **run aggregate** + **append-only event
  log** (event-log + projection / CQRS-lite). The aggregate is the single source of
  truth for "now"; the log is the single source for live progress *and* history.
- **DB-designer** — one lifecycle table with proper constraints: partial-unique
  index enforcing single-active; optimistic-lock `version` for heartbeat↔cancel
  races; FK cascades from project/connection; history index `(project_id, kind,
  created_at desc)`; dedup'd `error_log` catalog.
- **Data-engineer** — batch DAGs need: idempotency key, one single-active model
  across both execution modes, explicit step manifests (DAG-lite) with weights,
  resume/retry, failure classification, freshness as a first-class SLI, dead-letter
  via persisted failed runs.
- **Observability** — define SLI/SLO (golden signals: latency/traffic/errors/
  saturation) for sync; structured logging keyed by `run_id`/`workflow_id`;
  persisted, filterable logs + error catalog; runbook-ready.
- **ML-engineer** — the knowledge index is a feature/embedding store; staleness =
  feature freshness, code↔DB drift = data drift; triggers (webhook/poll/schedule)
  are *retraining triggers*; close the loop freshness → trigger → run → verify.
- **Agent-designer / prompt-engineer** — the orchestrator is a supervisor + pipeline
  pattern; every sub-agent stage must emit a span and persist failures; tool/stage
  error handling stays classified (transient/config/data/fatal) with retry/circuit
  semantics; answering/conversation/validation are observable gates.
- **Data-scientist** — data validation (DataGate hard checks, reconciliation) is a
  measurable quality gate; its pass/fail must be logged per run/query.

## 4. Target architecture ("Swiss clock")

```
trigger (manual│webhook│poll│schedule│chain│auto)
  │  RunCoordinator.start(): mint run_id + workflow_id in API, persist run(queued),
  │  return {run_id, workflow_id} in 202     ← kills "null id" + 30s dead air
  ▼
RunCoordinator  ── ONE seam for in-process AND ARQ (single single-active model)
  │  per step: append IndexingRunEvent (journal) ──► update IndexingRun projection
  │  emit WorkflowEvent with first-class run_id/kind/step_index/total_steps/progress_pct
  │  cooperative cancel: cancel_requested (Redis key cmd:cancel:{run_id} + DB column)
  ▼
WorkflowTracker ─ SSE (in-proc) / Redis pub-sub (ARQ→API) ─► single frontend store
  │
  └─ terminal: completed│failed│cancelled  +  failure_kind
        on failure → upsert ErrorLog (dedup by signature)   reaper flips stuck→failed
```

Two telemetry planes share one observability surface:

- **Runs plane:** `indexing_runs` (projection) + `indexing_run_events` (journal).
- **Query plane:** existing `request_traces` + `trace_spans` (kept, extended).
- **Errors plane:** new `error_log` catalog fed by *both* planes.

## 5. Locked contracts

> These are the zero-context contracts. Everything downstream depends on them.

### 5.1 Data model (SQLAlchemy 2.0 async, Alembic migration)

**`IndexingRun`** — `models/indexing_run.py`, table `indexing_runs` (projection / aggregate):

| Column | Type | Notes |
|---|---|---|
| `id` | `String(36)` PK | uuid4 |
| `workflow_id` | `String(36)` | unique, indexed; correlation with SSE |
| `project_id` | `String(36)` FK projects ON DELETE CASCADE | indexed |
| `connection_id` | `String(36)` FK connections ON DELETE CASCADE, nullable | null for `index_repo` |
| `kind` | `String(20)` | `index_repo` \| `db_index` \| `code_db_sync` \| `daily_sync` |
| `trigger` | `String(20)` | `manual` \| `webhook` \| `poll` \| `schedule` \| `chain` \| `auto` |
| `status` | `String(20)` | `queued` \| `running` \| `cancelling` \| `completed` \| `failed` \| `cancelled` |
| `current_step` | `String(64)` nullable | step key |
| `step_index` | `Integer` default 0 | 1-based once running |
| `total_steps` | `Integer` default 0 | from manifest at start |
| `progress_pct` | `Integer` default 0 | 0..100, cumulative weight |
| `detail` | `Text` nullable | last step detail |
| `error` | `Text` nullable | terminal error message |
| `failure_kind` | `String(20)` nullable | `transient` \| `configuration` \| `data_missing` \| `fatal` |
| `cancel_requested` | `Boolean` default false | cooperative-cancel flag |
| `version` | `Integer` default 0 | optimistic lock |
| `started_at` | `DateTime(tz)` nullable | set on `running` |
| `finished_at` | `DateTime(tz)` nullable | set on terminal |
| `heartbeat_at` | `DateTime(tz)` nullable | reaper input |
| `meta_json` | `Text` default `{}` | counts (files/tables/matched), resumed, trigger source |
| `created_at` / `updated_at` | `DateTime(tz)` | standard |

Indexes / constraints:
- `ix_indexing_runs_workflow` UNIQUE (`workflow_id`)
- `ix_indexing_runs_history` (`project_id`, `kind`, `created_at` DESC)
- **Partial unique** `uq_indexing_runs_active` on
  (`project_id`, `kind`, `COALESCE(connection_id,'')`)
  `WHERE status IN ('queued','running','cancelling')` — physical single-active guard.
  (SQLite dev: emulate with a guarded insert in `RunCoordinator`; Postgres prod uses
  the partial index.)

**`IndexingRunEvent`** — `models/indexing_run.py`, table `indexing_run_events` (append-only journal):

| Column | Type | Notes |
|---|---|---|
| `id` | `String(36)` PK | uuid4 |
| `run_id` | `String(36)` FK indexing_runs ON DELETE CASCADE | indexed |
| `ts` | `DateTime(tz)` | event time |
| `step` | `String(64)` | step key (`pipeline_start`/`pipeline_end`/manifest key) |
| `status` | `String(20)` | `started` \| `completed` \| `failed` \| `skipped` |
| `detail` | `Text` default `""` | |
| `elapsed_ms` | `Float` nullable | |
| `progress_pct` | `Integer` nullable | snapshot at event |
| `level` | `String(10)` default `info` | `debug`\|`info`\|`warn`\|`error` (filterable) |

Index: `ix_indexing_run_events_run_ts` (`run_id`, `ts`). Retention: TTL sweep keeps
last `INDEXING_RUN_EVENTS_TTL_DAYS` (default 30) and caps rows/run at
`INDEXING_RUN_EVENTS_MAX_PER_RUN` (default 500).

**`ErrorLog`** — `models/error_log.py`, table `error_log` (dedup'd error catalog, both planes):

| Column | Type | Notes |
|---|---|---|
| `id` | `String(36)` PK | uuid4 |
| `project_id` | `String(36)` FK projects ON DELETE CASCADE | indexed, nullable for system errors |
| `signature` | `String(64)` | sha256 of normalized (source+kind+message-skeleton) — dedup key |
| `source` | `String(20)` | `run` \| `query` \| `span` \| `system` |
| `kind` | `String(40)` | pipeline kind or span_type or `route` |
| `failure_kind` | `String(20)` nullable | classification |
| `message` | `Text` | latest message |
| `sample_ref` | `String(36)` nullable | latest `run_id` / `trace_id` / `span_id` |
| `occurrences` | `Integer` default 1 | incremented on repeat |
| `first_seen_at` / `last_seen_at` | `DateTime(tz)` | |
| `status` | `String(20)` default `open` | `open` \| `acknowledged` \| `resolved` — future debug workflow |
| `meta_json` | `Text` default `{}` | connection_id, user_id, etc. |

Indexes: `uq_error_log_project_sig` UNIQUE (`project_id`, `signature`);
`ix_error_log_project_lastseen` (`project_id`, `last_seen_at` DESC);
`ix_error_log_status` (`status`).

**`request_traces` / `trace_spans`** — kept as-is (see `models/request_trace.py`).
Extension: `RequestTrace` gains `failure_kind String(20)` (nullable) for parity with
runs; failed traces/spans additionally upsert into `error_log`.

`IndexCheckpoint` is **retained only as the repo resume cursor** (head/last SHA,
resume stage); its `status` field is no longer read for lifecycle — `IndexingRun`
owns lifecycle. `DbIndex`/`Sync` status records remain for domain results only.

### 5.2 Event contract (first-class fields — greenfield)

`core/workflow_tracker.py::WorkflowEvent` gains first-class fields (no more
progress-in-`extra`):

```python
@dataclass
class WorkflowEvent:
    workflow_id: str
    step: str
    status: str                      # started | completed | failed | skipped
    detail: str = ""
    elapsed_ms: float | None = None
    timestamp: float = field(default_factory=time.time)
    pipeline: str = ""
    span_type: str | None = None
    # --- new first-class run/progress fields ---
    run_id: str | None = None
    kind: str | None = None          # mirror of run kind for FE convenience
    step_index: int | None = None
    total_steps: int | None = None
    progress_pct: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)
```

`broadcast_external` MUST reconstruct tolerantly (filter payload to known dataclass
fields) to prevent silent drops as the contract evolves. Frontend `WorkflowEvent`
type in `lib/sse.ts` mirrors these fields.

### 5.3 Step manifests (DAG-lite, weighted)

`knowledge/run_manifests.py` — ordered `(step_key, label, weight)` per kind.
Baseline keys are the real step names already used (verified against
`ActiveTasksWidget` STEP_LABELS):

- `index_repo`: `resolve_ssh_key`, `clone_or_pull`, `detect_changes`,
  `cleanup_deleted`, `analyze_files`, `project_profile`, `cross_file_analysis`,
  `generate_docs`, `record_index`. Flag-gated steps appended when enabled:
  `ast_parse`, `graph_build`, `bm25_build`, `schema_embed`, `graph_db_bridge`,
  `graph_clustering`. `total_steps` is computed from the *resolved* manifest at
  `start()` so `%` is accurate for the active configuration.
- `db_index`: `introspect_schema`, `fetch_samples`, `load_context`,
  `validate_tables`, `store_results`, `generate_summary`.
- `code_db_sync`: `load_code_knowledge`, `load_db_index`, `match_tables`,
  `analyze_sync`, `store_sync`, `generate_sync_summary`.
- `daily_sync`: composite — `plan_targets`, `db_index` (sub), `code_db_sync` (sub),
  `freshness_reconcile`, `summarize`. Sub-pipeline progress rolls up by weight.

### 5.4 Service interface — `RunCoordinator`

`services/run_coordinator.py` — the single seam used by every trigger and by both
execution modes.

```python
class RunCoordinator:
    async def start(self, db, *, kind: str, project_id: str,
                    connection_id: str | None, trigger: str,
                    force_full: bool = False) -> IndexingRun:
        """Create run (queued→running guard), mint workflow_id, persist, emit
        pipeline_start. Raises RunAlreadyActive if a single-active conflict exists."""

    @asynccontextmanager
    async def step(self, run: IndexingRun, step_key: str):
        """Append started event, run body, append completed/failed event, update
        projection (current_step/step_index/progress_pct/heartbeat). Checks
        cancel_requested before entering; raises RunCancelled if set."""

    async def heartbeat(self, run: IndexingRun) -> None: ...

    async def finish(self, run: IndexingRun, status: str,
                     error: str | None = None,
                     failure_kind: str | None = None) -> None:
        """Terminal projection update + pipeline_end emit + ErrorLog upsert on failure."""

    async def request_cancel(self, db, run_id: str) -> bool:
        """Set cancel_requested (DB + Redis cmd:cancel:{run_id}); cancel in-proc task."""

    async def retry(self, db, run_id: str, *, force_full: bool) -> IndexingRun:
        """Start a new run (resume for index_repo via checkpoint, restart otherwise)."""
```

Pipelines (`pipeline_runner`, `db_index_pipeline`, `code_db_sync_pipeline`,
`daily_knowledge_sync_service`) call `RunCoordinator.step(...)` instead of
`tracker.step(...)` directly. The coordinator wraps `WorkflowTracker` for SSE.

### 5.5 API surface

Runs:
- `POST /repos/{project_id}/index` → `202 {run_id, workflow_id, status}` (in-proc **and** ARQ).
- `POST /connections/{connection_id}/index-db` → `202 {run_id, workflow_id, status}`.
- `POST /connections/{connection_id}/sync` → `202 {run_id, workflow_id, status}`.
- `GET /projects/{project_id}/pipeline-status` → rebuilt from `indexing_runs`
  (active runs query). Shape per pipeline: `{status, progress_pct, current_step,
  step_index, total_steps, run_id, started_at, error, failure_kind}`.
- `GET /tasks/active` → from `indexing_runs WHERE status IN (queued,running,cancelling)`, tenancy-filtered. No synthetic ids.
- `GET /projects/{project_id}/runs?kind=&status=&limit=&page=` → run history (all kinds).
- `GET /runs/{run_id}` → run detail (projection).
- `GET /runs/{run_id}/events?level=` → journal (live + history), filterable by level.
- `POST /runs/{run_id}/cancel` → `request_cancel`.
- `POST /runs/{run_id}/retry` → `{run_id (new), workflow_id}`; body `{force_full: bool}`.

Telemetry / logs (extends existing `/logs`):
- existing `/logs/{project_id}/requests|requests/{trace_id}|summary|users` kept.
- `GET /logs/{project_id}/errors?source=&kind=&failure_kind=&status=&date_from=&date_to=&page=` → `error_log` catalog with filters.
- `PATCH /logs/{project_id}/errors/{id}` → `{status}` (open/acknowledged/resolved).
- `GET /logs/{project_id}/runs?...` → unified run-log view (mirrors `/projects/.../runs` under the logs screen).

Scheduled sync:
- daily_sync becomes a first-class run (kind `daily_sync`) with history under `/projects/{id}/runs?kind=daily_sync`.
- `GET /projects/{project_id}/sync-schedule` / `PUT ...` → expose/configure cadence
  (cron expr + timezone, default from `daily_knowledge_sync_*` settings); "Sync now"
  reuses `POST /connections/{id}/sync` + repo index chain.

### 5.6 SLI / SLO contract (the "clockwork" Definition of Done)

| SLI | Measurement | SLO | Alert |
|---|---|---|---|
| Time-to-first-progress | click → first `IndexingRunEvent` for run | p95 < 2 s | burn-rate |
| Run success rate | completed / (completed+failed), 7 d, per kind | ≥ 99% | error-budget |
| Stuck-run recovery | runs flipped by reaper / total stuck | 100% within `timeout + 1 sweep` | critical |
| Index freshness (active project) | now − last completed run | < 24 h | warning |
| Drift lag (push→reindex done) | webhook ts → run completed | p95 < debounce + pipeline p95 | info |
| Agent answer validity | AnswerValidator/AgentResultValidator pass rate | ≥ target | warning |

Exposed via `MetricsCollector` (`/api/metrics`, `/api/metrics/prometheus`) with new
run counters: runs started/completed/failed/cancelled by kind, run duration
histogram, time-to-first-progress, error_log open count.

## 6. Agent query-lifecycle correctness (audit → contract)

Each capability maps to an existing component; the redesign guarantees each emits a
span and persists failures to `error_log`, and is filterable in the logs UI.

| Capability | Component(s) | Guarantee added |
|---|---|---|
| Work with data | connectors, `DataGate` | every DB query → `db_query` span; DataGate verdict logged |
| Build queries | `SQLAgent` (schema retrieval, lineage) | query + schema-context provenance in span `metadata_json` |
| Invoke data-search | `KnowledgeAgent`, retrieval, `McpSourceAgent` | `rag`/`tool_call` spans with retrieval stats |
| Handle errors | `stage_executor` classification, `llm_call_with_retry` | failed spans persist + classify; `error_log` upsert; retry/circuit semantics kept |
| Validate data | `DataGate` hard checks, `InvestigationAgent`, reconciliation | validation verdict span; failed validation → `error_log` (source=query) |
| Answer user | `AnswerValidator`, `AgentResultValidator` | validation gate result logged; near-budget partial answers flagged |
| Converse | session rotation, multilingual | session/rotation events in trace meta |

No rebuild of the (already hardened) orchestrator — this milestone is
**observability hardening + gap closure**, ensuring nothing is silent.

## 7. Frontend design

- **Single store** `useRunsStore` (replaces `pipelineStatusByProject` +
  `background-tasks-store`), keyed by `run_id`. SSE primary (first-class progress);
  poll `/tasks/active` + `/pipeline-status` for gap-fill with existing precedence
  (sse > poll, terminal guard). Optimistic insert of `queued` run from the 202
  response + immediate status refetch — instant feedback.
- **Global pill** (`ActiveTasksWidget`): kind, target, `step N/M`, `%` bar, elapsed,
  Cancel/Retry.
- **Overview rich panel** (rebuild of `KnowledgeHealthPanel` zone): three cards
  (Repository / Database / Code-DB Sync) with idle/running/failed states, progress
  bar, current step, collapsible live log, Cancel/Retry, and a History disclosure.
- **Logs & Observability screen** (extends existing logs screen): tabs
  **Queries** (existing traces), **Runs** (history + live + per-run event log),
  **Errors** (filterable `error_log` catalog with status open/ack/resolved → future
  debug workflow). Filters across all: kind, status, failure_kind, date range, user,
  connection, error signature.
- **Default view** (sub-item): deterministic landing (persist last active view per
  project; choose overview vs chat without the overview→chat flicker).

## 8. Observability, logging coverage & filters (explicit requirement)

- **Everything to DB:** background runs → `indexing_runs` + `indexing_run_events`;
  query lifecycle → `request_traces` + `trace_spans` (existing); all failures →
  `error_log` (dedup'd, both planes). Nothing important stays only in the ephemeral
  live drawer.
- **Structured logging:** every backend log line on the run/query path carries
  `run_id`/`workflow_id`/`project_id` (correlation ids) for grep + trace linking.
- **Filters:** logs API exposes filters by kind, status, failure_kind, level, date
  range, user, connection, signature (see §5.5). UI mirrors them.
- **Future debug/replay:** `error_log.status` (open/ack/resolved) tracks remediation;
  `sample_ref` links to the originating run/trace for one-click drill-down; run
  `meta_json` + checkpoint enable retry/resume. (Full replay engine is out of scope
  for v1 but the schema supports it.)

## 9. Non-goals (YAGNI)

- No microservice extraction — stays a modular monolith.
- No external tracing backend (Jaeger/OTel) in v1 — internal tables + `/metrics`.
- No full deterministic replay engine in v1 (schema-ready only).
- No multi-repo-per-project lifecycle changes beyond what exists.

## 10. Decomposition into implementation plans

Umbrella design-of-record → sequenced plans (each gets its own `writing-plans` pass).
Contracts in §5 are locked first; later milestones depend on them.

- **P0 — Contracts (sequential, blocks all):** models + Alembic migration
  (`indexing_runs`, `indexing_run_events`, `error_log`, `request_traces.failure_kind`);
  `WorkflowEvent` first-class fields; `run_manifests.py`; `RunCoordinator` skeleton +
  interfaces; settings (TTL/caps/timeouts). *Owns:* `models/*`, `core/workflow_tracker.py`,
  `knowledge/run_manifests.py`, `services/run_coordinator.py`, migration, `config.py`.
- **P1 — Run lifecycle:** rewire 3 triggers through `RunCoordinator` (return run_id+wf_id);
  worker correlation (pass run_id/wf_id, no re-begin); rebuild `pipeline_status_service`
  + `/tasks/active` on `indexing_runs`; cancel/retry; reaper on `indexing_runs`;
  tolerant `broadcast_external`. *Owns:* `api/routes/repos.py`, `connections.py`,
  `tasks.py`, `worker.py`, `services/pipeline_status_service.py`, `core/reaper_loop.py`,
  `core/workflow_events.py`.
- **P2 — Scheduled sync:** daily_sync as first-class run; freshness→trigger→verify
  loop; sync-schedule get/put; run history endpoint. *Owns:* `daily_knowledge_sync_service.py`,
  `main.py` cron, `api/routes/schedules.py` (or new sync-schedule), `api/routes/repos.py` (runs list).
- **P3 — Telemetry & errors:** `indexing_run_events` persistence in coordinator;
  `error_log` upsert from both planes; unified `/logs/.../errors` + `/runs/{id}/events`;
  TTL sweeps; metrics counters; SLO instrumentation. *Owns:* `services/run_coordinator.py`
  (events), `services/error_log_service.py`, `services/logs_service.py`,
  `api/routes/logs.py`, `services/trace_persistence_service.py`, `core/metrics.py`.
- **P4 — Agent-lifecycle observability hardening:** ensure all sub-agent stages emit
  spans + persist failures to `error_log`; DataGate/validator verdicts logged; no
  silent paths. *Owns:* `agents/*` (span emission only), `data_gate.py`,
  `answer_validator.py`, `stage_executor.py`.
- **P5 — Frontend:** `useRunsStore`; optimistic triggers; Overview rich panel; pill;
  Logs/Observability screen (Queries/Runs/Errors tabs + filters); default view.
  *Owns:* `frontend/src/stores/*`, `components/knowledge/*`, `components/tasks/*`,
  `components/logs/*`, `app/app/page.tsx`, `lib/api/*`, `lib/sse.ts`. Parallelizable
  after P0 contract lock.

Parallel groups: P0 sequential → {P1, P3 partial} → {P2, P4} → P5 (after P0; FE store
work can begin against the locked contract while backend lands).

## 11. Testing strategy

- **Backend unit:** `RunCoordinator` (progress math, single-active conflict, cancel,
  retry/resume); manifest resolution incl. flag-gated steps; `error_log` dedup;
  tolerant event reconstruction; reaper flips stuck runs; status/active/runs/cancel/
  retry endpoints; SLO metric emission.
- **Backend integration:** full in-process index run emits ordered events + terminal
  + persisted journal; cancel mid-run → `cancelled`; retry resumes; daily_sync writes
  a run; failed run upserts `error_log`; query-lifecycle failure upserts `error_log`.
- **Frontend (Vitest):** store reconciliation (sse>poll, terminal guard, optimistic
  insert, cancel/retry); card states (idle/running/failed/cancelled) + progress bar;
  logs screen filters; default-view selection.
- **Coverage:** keep combined backend gate ≥ 72%; retrieval eval gate unaffected.

## 12. Definition of Done

1. Clicking any index/sync trigger shows a running task with stepwise progress and
   `%` within the time-to-first-progress SLO (p95 < 2 s), in both execution modes.
2. Every run is persisted with its event journal; failures appear in the `error_log`
   catalog with filters and a drill-down link.
3. Cancel and Retry work from the UI in both modes; reaper recovers stuck runs.
4. Scheduled (daily) sync fires reliably and is visible with history.
5. Agent query lifecycle stages emit spans and persist failures; logs screen filters
   across queries, runs, and errors.
6. SLI/SLO counters exposed via `/api/metrics`; all CI gates green; coverage ≥ 72%.
