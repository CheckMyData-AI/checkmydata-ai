# Sync Workflow Reliability — Design Spec

**Date:** 2026-06-21
**Status:** Approved (brainstorming) → ready for `writing-plans`
**Branch:** `feat/sync-workflow-reliability`
**Scope:** P0 + P1 + P2 from the sync-workflow audit (2026-06-21)

---

## 1. Problem statement

The three knowledge-sync pipelines — **repo index** (code), **DB index**, **code↔DB sync** —
plus the **daily cron orchestrator** have reliability and observability gaps surfaced in the
audit:

- **P0-1** Stuck `running` status after a hard worker crash (OOM/SIGKILL/dyno cycle) is never
  recovered in ARQ mode. The web-only `_reset_stale_indexing_statuses` runs solely on web
  startup; status-read endpoints intentionally skip the reset in ARQ mode. Result: permanent
  `running` → 409 on retry + perpetual "Syncing…" in UI until a web dyno restart. Repo-index
  checkpoints are only cleaned after 24h.
- **P0-2** A daily-sync ARQ job that exceeds `daily_knowledge_sync_job_timeout_seconds` (or is
  hard-killed) leaves **no `KnowledgeSyncRun` audit record** — `persist_run` runs only after
  `run_for_project` returns.
- **P1-3** `KnowledgeSyncRun` history is persisted but exposed by **no API and no UI**.
- **P1-4** `run_daily_project_knowledge_sync` does not open a parent workflow → the UI shows
  disjoint repo/db/sync tasks with no "this is the nightly sync" grouping.
- **P1-5** The daily cron loop starts in **every web dyno** lifespan with no single-flight guard;
  only ARQ `task_id` dedup prevents double execution (the in-process multi-dyno path can double-run).
- **P1-6** No crash/recovery test coverage.
- **P2-7** `code_db_sync_pipeline` emits coarse SSE progress vs. `db_index_pipeline`.
- **P2-8** Every successful repo index — **including the no-change early-exit** — marks DB index
  and sync `stale`, producing freshness-panel noise.
- **P2-9** Two independent frontend visibility channels (poll + SSE) can diverge; no single source
  of truth.

## 2. Goals / non-goals

**Goals:** heartbeat-based recovery of stuck `running` across web+worker; durable daily-sync audit;
daily-sync history API+UI; parent daily-sync workflow; single-flight cron via a reusable Redis lock;
richer sync SSE; gate stale-marking to real changes; a single frontend read-model for background
tasks; full crash/recovery test coverage.

**Non-goals:** changing the indexing/sync algorithms themselves; migrating cron to ARQ-native
`cron()` (kept in web lifespan per decision); reworking the chat pipeline; touching auth/billing.

## 3. Decisions locked (from brainstorming)

1. **P0 recovery** → heartbeat + idempotent reaper.
2. **Cron single-flight** → reusable Redis advisory-lock helper (`SET NX EX`).
3. **History surface** → dedicated endpoint + UI history panel section.
4. **Frontend SoT** → full refactor to one unified background-tasks store/hook.

## 4. External-library facts (Context7-verified, ARQ `arq-docs.helpmanual.io`)

- `job_timeout` raises `CancelledError` **into** the coroutine → `finally` runs → status set to
  `failed`. The unrecoverable stuck case is **hard process death only** (no `finally`). Heartbeat
  targets exactly that.
- ARQ job uniqueness by `_job_id`: while a job's result key persists (`keep_result`, default ~1h),
  re-`enqueue_job` with the same id returns **`None`** (silent no-op). The repo currently uses
  static ids (`db_index:{cid}`, `code_db_sync:{cid}`, `repo_index:{pid}`).
  → **Contract:** DB-status `running` + 409 guard + in-memory task remain the dedup source of
  truth. Re-triggerable background jobs use **per-run unique** ARQ ids and `keep_result=0`.

---

## 5. Architecture overview

```
Heartbeat (per run)  ──writes heartbeat_at──►  status row (DbIndexSummary / CodeDbSyncSummary / IndexingCheckpoint)
                                                      ▲
Reaper loop (web + worker, idempotent) ──reads──┘  marks rows with stale heartbeat → failed / interrupted

Daily cron loop (web lifespan, per dyno)
   └─ redis_lock("cron:daily_sync:{date}") ─► single dispatcher ─► enqueue run_daily_project_knowledge_sync
        └─ tracker.begin("daily_sync") … persist_run in finally … tracker.end   (parent workflow + durable audit)

Frontend: useBackgroundTasks (single Zustand read-model)
   ◄── SSE  /workflows/events   (precedence for running + terminal)
   ◄── poll /projects/{pid}/pipeline-status + /tasks/active   (gap-fill for pre-connect runs)
```

---

## 6. Locked contracts

### 6.1 Config flags (`backend/app/config.py` + `backend/.env.example`)

Add as plain `Settings` attributes (same pattern as `daily_knowledge_sync_*`). **Not** added to
`AgentSettingsView`.

```python
# Stale-run reaper (P0). Heartbeat-based recovery of stuck 'running' statuses.
reaper_enabled: bool = True
heartbeat_interval_seconds: int = 30
reaper_interval_seconds: int = 60
stale_running_heartbeat_timeout_seconds: int = 300
```

`.env.example` entries with docstrings mirroring the above.

### 6.2 DB migration (Alembic, single revision)

Add nullable `heartbeat_at` to three tables. Revision message:
`add heartbeat_at to db_index_summary, code_db_sync_summary, indexing_checkpoint`.

| Table | Column |
|---|---|
| `db_index_summary` | `heartbeat_at TIMESTAMPTZ NULL` |
| `code_db_sync_summary` | `heartbeat_at TIMESTAMPTZ NULL` |
| `indexing_checkpoint` | `heartbeat_at TIMESTAMPTZ NULL` |

Model changes (match existing `mapped_column` style):

```python
# DbIndexSummary, CodeDbSyncSummary, IndexingCheckpoint
heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

`autogenerate` must be reviewed; keep the per-file ruff ignore on the migration.

### 6.3 Heartbeat helper (`backend/app/core/heartbeat.py` — NEW)

```python
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

HeartbeatWriter = Callable[[], Awaitable[None]]

@asynccontextmanager
async def heartbeat(writer: HeartbeatWriter, *, interval_seconds: int) -> AsyncIterator[None]:
    """Run *writer* every *interval_seconds* in a background task for the duration of the block.

    The writer updates heartbeat_at=now() on the run's status row. Writer errors are logged
    and swallowed (a heartbeat failure must never crash the run). The task is cancelled and
    awaited on exit. A first heartbeat is written immediately on entry.
    """
```

Each pipeline supplies a `writer` that opens its own short-lived session and updates its row:
- `DbIndexPipeline.run` → updates `DbIndexSummary.heartbeat_at` for `connection_id`.
- `CodeDbSyncPipeline.run` → updates `CodeDbSyncSummary.heartbeat_at` for `connection_id`.
- repo index (`pipeline_runner` / `_run_index_background`) → updates `IndexingCheckpoint.heartbeat_at`.

Service methods to add (idempotent, own session caller-managed):
- `DbIndexService.touch_heartbeat(session, connection_id)` → set `heartbeat_at=now()`.
- `CodeDbSyncService.touch_heartbeat(session, connection_id)` → set `heartbeat_at=now()`.
- `CheckpointService.touch_heartbeat(session, checkpoint_id)` → set `heartbeat_at=now()`.

### 6.4 Reaper (`backend/app/services/stale_run_reaper.py` — NEW)

```python
class StaleRunReaper:
    async def reap_once(self, session: AsyncSession, *, timeout_seconds: int) -> dict[str, int]:
        """Single idempotent sweep. Returns {'db_index': n, 'sync': n, 'repo': n}.

        cutoff = now() - timeout_seconds
        - DbIndexSummary  WHERE indexing_status='running' AND (heartbeat_at IS NULL OR heartbeat_at < cutoff)
              → indexing_status='failed'
        - CodeDbSyncSummary WHERE sync_status='running'  AND (heartbeat_at IS NULL OR heartbeat_at < cutoff)
              → sync_status='failed'
        - IndexingCheckpoint WHERE status='running'      AND (heartbeat_at IS NULL OR heartbeat_at < cutoff)
              → status='interrupted'   (enables resume on next run, not a hard fail)
        Only rows with a genuinely stale/absent heartbeat are touched → safe to run concurrently
        in multiple processes.
        """
```

**`heartbeat_at IS NULL` grace:** rows created by an in-flight run before its first heartbeat
have `heartbeat_at IS NULL`. To avoid killing a just-started run, the reaper treats `NULL` as
stale **only if** `updated_at < cutoff` (the row hasn't been touched recently either). Implement
as: `(heartbeat_at IS NOT NULL AND heartbeat_at < cutoff) OR (heartbeat_at IS NULL AND updated_at < cutoff)`.

Loop driver (`backend/app/core/reaper_loop.py` — NEW, or co-located): `async def reaper_loop()`
sleeps `reaper_interval_seconds`, calls `reap_once`; gated by `settings.reaper_enabled`. A one-shot
`reap_once` also runs at startup of **both** processes.

**Wiring:**
- `backend/app/main.py` lifespan: replace `_reset_stale_indexing_statuses()` call with a startup
  `reap_once` + `asyncio.create_task(reaper_loop())`. **Delete** `_reset_stale_indexing_statuses`.
- `backend/app/worker.py` `startup(ctx)`: add startup `reap_once` + launch `reaper_loop` task;
  `shutdown(ctx)`: cancel it.

### 6.5 ARQ job-id contract (`backend/app/api/routes/connections.py`, `repos.py`, `worker.py`)

For **re-triggerable** background enqueues, use per-run **unique** ids. A unique id alone fully
removes the result-key re-enqueue block (each run has a fresh id → no collision regardless of
ARQ result retention), so DB-status dedup stays authoritative:
- `connections._dispatch_db_index`: `task_id=f"db_index:{connection_id}:{uuid4().hex[:8]}"`.
- `connections._dispatch_code_db_sync`: `task_id=f"code_db_sync:{connection_id}:{uuid4().hex[:8]}"`.
- `repos._spawn_repo_index` (ARQ branch): `task_id=f"repo_index:{project_id}:{uuid4().hex[:8]}"`.

Daily wave keeps deterministic `daily_sync:{pid}:{date}` (idempotency desired there).

**ARQ result retention:** `keep_result` is a worker/function-level setting in ARQ (not a per-
`enqueue_job` kwarg), so it is **not** threaded through `task_queue.enqueue`. If Redis result
bloat becomes a concern, set `keep_result` on `WorkerSettings` in a follow-up — out of scope here.
No `task_queue.enqueue` signature change is required; only the `task_id` values above change.
Confirm the in-process fallback still tracks the task for status/409 (unchanged path).

### 6.6 Redis advisory lock (`backend/app/core/distributed_lock.py` — NEW)

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def redis_lock(key: str, *, ttl_seconds: int) -> AsyncIterator[bool]:
    """Best-effort distributed lock via SET key value NX EX ttl.

    Yields True if this process acquired the lock, else False. On exit, releases the lock
    only if still owned (compare-and-del via a unique token, Lua or GET+DEL guard).
    Without Redis configured (redis_client.get_redis() is None) yields True (single process).
    Never raises on Redis errors — yields False so callers skip rather than crash.
    """
```

Cron usage (`main.py._dispatch_daily_knowledge_sync_wave`):
```python
async with redis_lock(f"cron:daily_sync:{run_date}", ttl_seconds=3600) as acquired:
    if not acquired:
        return
    ... existing dispatch ...
```

### 6.7 Daily parent workflow + durable audit (`backend/app/worker.py`, `main.py`)

`run_daily_project_knowledge_sync` and the in-process `_run_in_process` closure both:
```python
wf_id = await tracker.begin("daily_sync", {"project_id": project_id, "trigger": "scheduled"})
result = None
try:
    result = await svc.run_for_project(project_id)   # emits child repo/db/sync workflows
    await tracker.end(wf_id, "daily_sync", _wf_status(result.status), _summary(result))
finally:
    if result is None:  # crash/timeout before run_for_project returned
        result = KnowledgeSyncRunResult(project_id=project_id, status="failed",
                                        error_message="interrupted before completion")
    await svc.persist_run(result)   # ALWAYS persists (P0-2)
```
`DailyKnowledgeSyncService.run_for_project` should emit phase-level `tracker.emit(wf_id, ...)` for
repo→db→sync; pass `wf_id` in so children can be tagged via `extra={"parent_workflow_id": wf_id}`
(additive, optional for UI grouping).

Register `"daily_sync"` in `BACKGROUND_PIPELINES` (`backend/app/core/workflow_tracker.py`) so it
appears in `/tasks/active` and SSE.

### 6.8 Sync-history API (`backend/app/api/routes/projects.py`)

```
GET /api/projects/{project_id}/sync-history?limit=20        (viewer role required)
```
Response (locked shape):
```json
{
  "runs": [
    {
      "id": "uuid",
      "trigger": "scheduled",
      "status": "success|partial|failed|skipped",
      "duration_seconds": 123.4,
      "error_message": null,
      "created_at": "2026-06-21T00:03:11Z",
      "steps": { "repo_index": {"status": "completed", "error": null},
                 "connections": [ {"connection_id": "...", "db_index": {...}, "code_db_sync": {...}} ] }
    }
  ]
}
```
Backed by a new `KnowledgeSyncRunService.list_for_project(session, project_id, limit)` ordered by
`created_at DESC`, capped (`limit` clamped 1..50). `steps` is `steps_json` passed through.

### 6.9 Stale-marking gate (`backend/app/knowledge/pipeline_runner.py`)

In `_record_and_finish`, wrap the `_mark_db_index_code_stale` / `_mark_sync_stale` block so it runs
only when there were real changes:
```python
if state.changed_files or state.deleted_files:
    await self._mark_db_index_code_stale(db, project_id)
    await self._mark_sync_stale(db, project_id)
```
(No-change early-exit no longer marks stale.)

### 6.10 Sync SSE granularity (`backend/app/knowledge/code_db_sync_pipeline.py`)

Add `tracker.step(...)` / `tracker.emit(...)` around the existing analysis/persist phases to reach
parity with `db_index_pipeline` (e.g. `match_tables`, `analyze_columns`, `persist_summary`). No
behavior change — events only. Keep `project_id` in the `begin` extra (already present).

### 6.11 Frontend unified store (`frontend/src/stores/background-tasks-store.ts` — NEW)

Single Zustand read-model. Consolidates `task-store` background-task duties.

```ts
export type BgPipeline = "index_repo" | "db_index" | "code_db_sync" | "daily_sync";
export type BgStatus = "running" | "completed" | "failed";

export interface BgTask {
  workflowId: string;
  pipeline: BgPipeline;
  status: BgStatus;
  step?: string;
  startedAt: number;
  updatedAt: number;
  extra: { project_id?: string; connection_id?: string; parent_workflow_id?: string };
  source: "sse" | "poll";       // provenance for precedence
}

interface BackgroundTasksState {
  tasks: Record<string, BgTask>;
  pinnedRunningIds: Set<string>;
  applySseEvent: (e: WorkflowEvent) => void;          // precedence: terminal SSE wins; running SSE > poll
  reconcileFromPipelineStatus: (s: PipelineStatusResponse) => void;  // gap-fill running not seen via SSE
  reconcileFromActive: (tasks: ApiActiveTask[]) => void;
  dismissTask: (workflowId: string) => void;
}
```

**Precedence rules (locked):**
1. A terminal SSE event (`pipeline_end`) is authoritative — sets `completed/failed`, schedules dismiss.
2. A running SSE event upserts `running` with `source:"sse"`; never downgraded by a later poll.
3. Poll (`pipeline-status`/`active`) may **create** a `running` task only if absent (run started
   before SSE connect); it must **not** flip an SSE-sourced task back to `running` once terminal.
4. `pinnedRunningIds` survives until explicitly dismissed.

`useGlobalEvents`, `useKnowledgePipelineStatus`, `SyncStatusIndicator`, `KnowledgeHealthPanel`,
`Sidebar`, `ActiveTasksWidget` read/write **only** this store. Old `task-store` background paths
(`seedFromPipelineStatus`, `processEvent`, `seedFromApi`) are migrated into the new store; remove
the duplicated logic. (Chat/log stores untouched.)

### 6.12 Sync-history UI (`frontend/src/components/knowledge/SyncHistoryPanel.tsx` — NEW)

Rendered inside / beside `KnowledgeHealthPanel`. Shows latest run summary
("Nightly sync: success · 2h ago · 3/3 connections") with an expandable per-step breakdown from
`steps`. Data via new `api.projects.syncHistory(projectId, limit)` →
`frontend/src/lib/api/projects.ts` + `SyncHistoryResponse` type in `frontend/src/lib/api/types.ts`.
Polls on the same cadence as health when `any_running`.

---

## 7. Testing strategy (TDD — failing test first)

**Backend unit:**
- `test_stale_run_reaper.py`: stuck (old/NULL heartbeat) → reset; fresh heartbeat → untouched;
  NULL heartbeat + recent `updated_at` → untouched (grace); idempotent double-run; checkpoint →
  `interrupted` not `failed`.
- `test_heartbeat.py`: writes immediately + every interval; swallows writer errors; cancels on exit.
- `test_distributed_lock.py`: one acquirer wins under contention; no-Redis → True; release only if owned.
- `test_daily_knowledge_sync.py` (extend): `persist_run` called on timeout/exception path; parent
  `daily_sync` workflow begin/end emitted; `BACKGROUND_PIPELINES` includes it.
- `test_sync_history` (route/service): ordering, limit clamp, viewer auth (403 for non-member).
- `test_db_index_pipeline` / `test_code_db_sync_pipeline`: heartbeat writes during run; sync SSE
  granularity events present.
- `test_pipeline_runner` stale-gate: no-change early-exit does **not** mark stale; change path does.
- `test_task_queue`: `_keep_result` / unique-id threaded to ARQ; in-process fallback still tracks.

**Backend integration:**
- `test_indexing_e2e` (extend): crash simulation — set `running` + old `heartbeat_at`, run
  `reap_once`, assert `failed`/`interrupted` and that a fresh re-trigger enqueues (unique id).

**Frontend (Vitest):**
- `background-tasks-store.test.ts`: precedence matrix (SSE terminal > poll; poll gap-fill;
  pin survival).
- `SyncHistoryPanel.test.tsx`: renders latest + expands steps; empty state.
- Update/relocate existing `task-store-pipeline.test.ts`, `pipeline-event-handlers.test.ts`,
  `sync-api.test.ts`, `KnowledgeHealthPanel.test.tsx` to the new store.

**Gates:** `make check` (ruff format+check, mypy, combined coverage ≥72%); frontend
`tsc --noEmit && eslint --max-warnings=0 && vitest run`.

---

## 8. Parallel-execution plan (file ownership — no two parallel tasks write the same file)

**S0 — Sequential contract lock (first, blocks all):**
`config.py` (+`.env.example`), Alembic migration + 3 model edits, `BACKGROUND_PIPELINES` entry,
`frontend/src/lib/api/types.ts` (`SyncHistoryResponse`, store types),
`frontend/src/lib/api/projects.ts` (`syncHistory`).

**Parallel group 1** (depends: S0):
- **S1 — P0 backend:** `core/heartbeat.py`, `services/stale_run_reaper.py`, `core/reaper_loop.py`,
  heartbeat wiring in `db_index_pipeline.py` / `code_db_sync_pipeline.py` / `pipeline_runner.py`
  (heartbeat only) / `_run_index_background`, `*_service.touch_heartbeat`, `main.py` + `worker.py`
  startup wiring, delete `_reset_stale_indexing_statuses`, unique ARQ ids in `connections.py`/`repos.py`.
- **S2 — P1 backend:** `core/distributed_lock.py`, cron lock in `main.py` wave dispatch, daily
  parent workflow + persist-in-finally in `worker.py`/`main.py`, `services/knowledge_sync_run_service.py`,
  `sync-history` route in `projects.py`.
- **S3 — C backend:** sync SSE granularity in `code_db_sync_pipeline.py` **only at distinct
  line ranges from S1's heartbeat edit** → to avoid overlap, **merge S3 into S1** (same file).
  Stale-gate in `pipeline_runner.py` (distinct function from S1's heartbeat edit; if overlap risk,
  fold into S1).
- **S4 — frontend:** `stores/background-tasks-store.ts`, refactor `useGlobalEvents.ts`,
  `useKnowledgePipelineStatus.ts`, `SyncStatusIndicator.tsx`, `KnowledgeHealthPanel.tsx`,
  `Sidebar.tsx`, `ActiveTasksWidget.tsx`, new `SyncHistoryPanel.tsx`, migrate tests.

> **Overlap note:** `code_db_sync_pipeline.py` and `pipeline_runner.py` are touched by both P0
> (heartbeat) and P2 (SSE/stale-gate). To respect "no two parallel tasks write the same file,"
> **S1 and S3 are merged into a single owner** for those two files. Net parallel streams: **S1+S3
> (backend reliability+pipeline-events), S2 (backend cron/history), S4 (frontend)**.

**S5 — Sequential glue (last):** integration tests, full `make check` + frontend gates, fix
failures, update `CHANGELOG.md` `[Unreleased]`, `API.md` (sync-history endpoint), `CLAUDE.md` flag
table, commit → push → Heroku auto-deploy.

## 9. Rollout / flags

- `reaper_enabled=True` by default (safe: only touches genuinely stale rows). Reaper + heartbeat are
  the core fix and ship on.
- New env vars documented in `.env.example` and `CLAUDE.md` feature-flag/config tables.
- No data backfill needed (`heartbeat_at` nullable; reaper grace handles legacy NULLs).
- Deploy is standard Heroku auto-deploy on merge; `Procfile` already runs `alembic upgrade head`
  before the web dyno boots, so the migration applies automatically.

## 10. Definition of done

All §7 tests pass; coverage ≥72%; mypy/ruff/eslint/tsc clean; stuck-`running` recovers within
`stale_running_heartbeat_timeout_seconds` in both web-only and worker-only restart scenarios;
daily-sync always leaves a `KnowledgeSyncRun`; `/projects/{id}/sync-history` returns history and the
UI renders it; no-change repo index no longer marks stale; sync pipeline emits step-level SSE; a
single frontend store drives all background-task UI with no poll/SSE divergence; merged + deployed.
