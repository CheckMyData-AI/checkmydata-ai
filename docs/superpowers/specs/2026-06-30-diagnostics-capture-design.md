# Spec — Diagnostics capture: complete, queryable failure data in the DB

- **Date:** 2026-06-30
- **Skills applied:** senior-architect (impact/coupling), senior-ml-engineer (LLM-pipeline observability/recall), systematic-debugging (verify before spec).
- **Goal:** when anything fails (a query, a stage, a background/sync job), the FULL diagnostic detail is reliably persisted to the DB and queryable, so we can diagnose & fix after the fact. No silent loss.

---

## 1. Audit findings (current state)

The system **already exists and is mature** — this is a gap-closure, not a greenfield:

**Persistence**
- `TracePersistenceService` (services/trace_persistence_service.py) buffers `WorkflowTracker` events per workflow and batch-inserts `RequestTrace` + `TraceSpan` at `pipeline_end` (stale-buffer sweep at 300s persists abandoned ones as `failed`).
- `RequestTrace` (models/request_trace.py): question(500c), response_type, status, error_message(1000c), failure_kind, counts, tokens, cost, provider/model, ids. `TraceSpan`: span_type, name, status, detail, input_preview(1000c), output_preview(1000c), token_usage_json, metadata_json, timings.
- `ErrorLog` (models/error_log.py): dedup'd-by-signature catalog (source run|query|span|system, kind, failure_kind, message, sample_ref, occurrences, status). `ErrorLogService.upsert_from_trace/upsert_from_run`.
- `IndexingRun` + `IndexingRunEvent`: background-job lifecycle (status, error, failure_kind, meta_json, append-only events).

**Read/access** (all real, gated)
- `/api/logs/{project_id}/{requests,requests/{id},summary,users,errors,runs}` — owner-only. `/api/runs/{id}` + `/events` — viewer. `/api/metrics` — admin. `/api/tasks/active`, `/api/workflows/events` (SSE) — tenanted. Frontend `LogsScreen` (Queries/Runs/Errors tabs) + trace detail.

**VERIFIED non-bug (do not "fix"):** SSE backpressure (`workflow_tracker.py:430-451`) drops events only from per-subscriber SSE queues; the persistence hooks (`_deliver_local`, line 464) fire for **every** event regardless. Persistence is NOT starved by backpressure.

**REAL gaps (what is lost / undiagnosable):**
1. **Failed SQL text + full DB error are not first-class.** Only `TraceSpan.input/output_preview` (1000c) of non-skipped events, and `tool_call_log.result_preview[:200]`. For the GROUP BY 1055 incident the actual failing SQL + raw 1055 text are effectively not retrievable.
2. **Repair attempt history is ephemeral.** `ValidationLoopResult.attempts` (the per-attempt query + classified error + elapsed) is returned to the SQL agent and discarded — never persisted. Can't see the 3 failed attempts after the fact.
3. **Background/sync-job failures don't record their triggering flag/config.** `IndexingRun.error` holds only the last step's error; the feature-flag state (`git_webhook_enabled`, `auto_sync_after_index`, `freshness_reconciler_enabled`, `db_index_incremental_enabled`, …) that produced the run is not snapshotted → "which flag caused this sync failure?" is undiagnosable.
4. **The diagnostics layer is not self-observable.** All persistence is best-effort try/except → `logger.warning/debug`. If trace/error persistence itself fails, nothing records it.
5. **Read-path gaps:** `AuditLog` has no read API; `PipelineRun` stage results no read API. (Lower priority.)

---

## 2. Scope

**Release (P0 — this spec, implemented now):** make FAILED QUERIES fully diagnosable + sync-job flag provenance + diagnostics self-observability. Specifically:
- A new append-only `QueryFailure` table capturing failed/recovered query executions with the **full** SQL, **full** raw DB error, classified `error_type`, and the **complete attempt history**.
- `IndexingRun` records a feature-flag snapshot at start.
- Diagnostics persistence failures increment a metric + best-effort `system` ErrorLog (self-observability).
- Owner-gated read API for query failures.

**Follow-ups (P1 — enumerated in the plan, not built now):** frontend "Query failures" tab; `AuditLog` admin read API; historical (persisted) metrics; raising `RequestTrace.error_message` cap.

**Out of scope:** the verified non-bug backpressure path; the GROUP BY classifier fix (separate branch `fix/groupby-classification-2026-06-30`).

---

## 3. Locked contracts

### 3.1 Config — `app/config.py`
```python
diagnostics_capture_enabled: bool = True   # gate the QueryFailure capture (safe rollback)
diagnostics_attempt_history_max: int = 20  # cap attempts serialized per failure
diagnostics_raw_error_max_chars: int = 8000  # cap on stored raw error text
```
Add to `.env.example`.

### 3.2 New model — `app/models/query_failure.py`
```python
class QueryFailure(Base):
    __tablename__ = "query_failures"
    id: str (UUID36, PK)
    project_id: str  (FK projects.id, CASCADE, NOT NULL, indexed)
    connection_id: str | None  (String(36), nullable)
    workflow_id: str | None  (String(36), nullable, indexed)
    trace_id: str | None  (String(36), nullable)        # soft link to RequestTrace.id
    session_id: str | None  (String(36), nullable)
    message_id: str | None  (String(36), nullable)
    db_type: str  (String(30), NOT NULL, default="")
    question: str  (Text, NOT NULL, default="")
    failed_sql: str  (Text, NOT NULL, default="")        # the FINAL failing query
    error_type: str  (String(40), NOT NULL, default="unknown")  # QueryErrorType.value
    failure_kind: str | None  (String(20))               # transient|configuration|data_missing|fatal
    raw_error: str  (Text, NOT NULL, default="")         # full, capped at diagnostics_raw_error_max_chars
    attempts_json: str  (Text, NOT NULL, default="[]")   # [{attempt, query, error_type, raw_error, elapsed_ms}]
    attempt_count: int  (Integer, NOT NULL, default=0)
    final_status: str  (String(20), NOT NULL, default="failed")  # failed | recovered
    created_at: datetime  (tz, NOT NULL, server_default=now())
    # indexes: (project_id, created_at), (connection_id, created_at), (error_type)
```
Migration: Alembic autogenerated revision; **booleans/defaults must be Postgres-safe** (use `sa.true()`/`server_default=sa.text("...")` patterns already in the repo — recall the v185 outage). Append-only (no updates).

### 3.3 Service — `app/services/query_failure_service.py`
```python
class QueryFailureService:
    async def record(self, session, *, project_id, connection_id, workflow_id, trace_id,
                     session_id, message_id, db_type, question, attempts: list[QueryAttempt],
                     final_status: str) -> None
```
- Builds the row from `attempts` (the last attempt's query/error → `failed_sql`/`raw_error`/`error_type`); serializes up to `diagnostics_attempt_history_max` attempts; caps `raw_error`.
- **Best-effort + self-observing:** wrapped in try/except; on failure increments `MetricsCollector` `diagnostics_persist_failures` and logs `ERROR` (not debug). MUST NOT raise into the request path.
- A module-level `maybe_record_query_failure(context, loop_result)` helper that no-ops when `not settings.diagnostics_capture_enabled` or when `loop_result` had no errored attempts.

### 3.4 Capture point — `app/agents/sql_agent.py`
After `validation_loop.execute(...) -> loop_result` in `_handle_execute_query` (the single seam with the full `attempts` + final result + `AgentContext`): if any attempt carried an error, call the recorder (`final_status="recovered"` if `loop_result.success` else `"failed"`). Fire as a non-blocking best-effort task (do not block the answer). Pull `project_id`/`connection_id`/`session_id`/`workflow_id` from `AgentContext`.

### 3.5 Flag snapshot — `app/services/run_coordinator.py`
When creating an `IndexingRun` (status `queued`/`running`), write a snapshot of the relevant feature flags into `meta_json["flags"]`:
```python
{"git_webhook_enabled","git_poll_enabled","auto_sync_after_index",
 "freshness_reconciler_enabled","schema_change_alerts_enabled",
 "db_index_incremental_enabled"}  # name -> bool from settings
```

### 3.6 Read API — `app/api/routes/logs.py`
- `GET /api/logs/{project_id}/query-failures` — owner-only (mirror existing `/requests`): paginated, filter by `error_type`, `connection_id`, `final_status`, date range; returns the row minus `attempts_json` (summary).
- `GET /api/logs/{project_id}/query-failures/{id}` — owner-only: full row incl. parsed `attempts`.
- Add `logs.queryFailures()` / `logs.queryFailureDetail()` to `frontend/src/lib/api/analytics.ts` (frontend tab is a P1 follow-up; API client method is in-scope so the data is reachable).

### 3.7 Self-observability — `app/core/metrics.py`
Add a `diagnostics_persist_failures` counter (increment from QueryFailureService + TracePersistenceService + ErrorLogService persistence except-blocks) exposed via `/api/metrics`.

---

## 4. Whole-system impact (architect lens)

**Touch set:** new `models/query_failure.py` + migration; new `services/query_failure_service.py`; edits to `sql_agent.py` (capture), `run_coordinator.py` (flag snapshot), `core/metrics.py` (counter), `api/routes/logs.py` (read API), `config.py` + `.env.example`, `frontend/src/lib/api/analytics.ts`. **Non-overlapping** with the `fix/groupby-classification` branch.

**Coupling / risk:**
1. **Request-path safety:** capture is best-effort, non-blocking, flag-gated → a capture bug can never fail a user query. (Vision §7 graceful degradation.)
2. **Write volume:** one extra append per *failed/recovered* query only (not every query) → bounded. Append-only; indexed for the read API. Add a retention note (P1: TTL prune like `pipeline_run_ttl_days`).
3. **Tenant isolation:** read API owner-gated + project-scoped (R3), same pattern as `/requests`.
4. **Composes with the groupby fix:** once GROUP BY is classified, `QueryFailure.error_type` will read `group_by_violation` and `final_status=recovered` — the two features together make the incident both *fixable* and *visible*.
5. **No exhaustive enum match** depends on QueryErrorType (verified earlier) → storing `.value` is safe.
6. **Migration safety:** Postgres-safe server defaults (the v185 boolean-default outage is the cautionary precedent — tested against Postgres semantics, not just SQLite).
7. **Coverage gate (72%):** net-new code fully tested → non-decreasing.

**Self-observability gain:** the diagnostics layer can no longer fail silently — `diagnostics_persist_failures` surfaces on `/api/metrics`.

---

## 5. Rollout / verification
- TDD per task; migration applied via `alembic upgrade head` (Procfile runs it pre-boot).
- Post-deploy: trigger a known-failing query (e.g. a GROUP BY violation) and confirm a `QueryFailure` row with the full SQL + raw error + attempts via `GET /api/logs/{project}/query-failures`; confirm an IndexingRun carries `meta_json.flags`; confirm `/api/metrics` exposes `diagnostics_persist_failures` (0 on a healthy run).
