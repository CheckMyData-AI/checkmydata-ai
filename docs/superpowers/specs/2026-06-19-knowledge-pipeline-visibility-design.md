# Knowledge Pipeline Visibility — Design Spec

**Date:** 2026-06-19  
**Status:** Approved for implementation

## Problem

Repo indexing and code↔DB sync run in ARQ worker processes. The UI and logs do not reflect progress because:

1. `GET /sync/status` falsely resets `running → failed` in ARQ mode (missing guard).
2. `WorkflowTracker` is in-memory per process — worker SSE events never reach API subscribers.
3. `GET /repos/status` `is_indexing` ignores `IndexingCheckpoint.status == "running"`.
4. Frontend polls are fragmented; Sidebar loads status once; multi-user project members miss jobs started by others.

## Goals

- Any project member (viewer+) sees running repo index, DB index, and code-DB sync within 3s.
- Status survives page reload and account switch (project-scoped, DB-backed).
- LogPanel and ActiveTasksWidget receive worker step events via Redis pub/sub when ARQ is active.

## Non-goals

- Enable `auto_sync_after_index` by default.
- Sync all connections in auto-chain.
- Read API for `KnowledgeSyncRun`.
- Persist workflow events to DB for audit.

---

## API Contract

### `GET /api/projects/{project_id}/pipeline-status`

**Auth:** project membership, role ≥ viewer.

**Response:**

```typescript
interface PipelineStatusResponse {
  project_id: string;
  repo: {
    is_indexing: boolean;
    checkpoint_status: string | null;
    workflow_id: string | null;
    last_indexed_at: string | null;
    last_indexed_commit: string | null;
  };
  connections: Array<{
    connection_id: string;
    connection_name: string;
    db_index: {
      is_indexing: boolean;
      indexing_status: string;
      indexed_at: string | null;
      table_count: number;
    };
    code_db_sync: {
      is_syncing: boolean;
      sync_status: string;
      synced_at: string | null;
      total_tables: number;
      synced_tables: number;
    };
  }>;
  any_running: boolean;
}
```

**Rules:**

| Signal | In-process | ARQ |
|--------|------------|-----|
| `is_indexing` | in-memory task OR checkpoint `running` | checkpoint `running` only |
| `is_syncing` / `is_indexing` (DB) | in-memory task OR DB `running` | DB `running` only |
| Stale reset on status endpoints | allowed when no in-memory task | **never** reset stale while DB says `running` |

### `GET /api/tasks/active` (extended)

When ARQ active, merge synthetic running tasks from DB:

- Repo: `IndexingCheckpoint.status == "running"` → `{ pipeline: "index_repo", workflow_id, extra: { project_id } }`
- DB index: `indexing_status == "running"` → `{ pipeline: "db_index", ... }`
- Sync: `sync_status == "running"` → `{ pipeline: "code_db_sync", ... }`

Dedupe by `workflow_id` or synthetic key `db:{connection_id}` / `sync:{connection_id}`.

---

## Redis Pub/Sub Bridge

**Channel:** `cmd:workflow_events`  
**Payload:** JSON from `WorkflowEvent.to_json()`

| Publisher | Behavior |
|-----------|----------|
| Worker process | On `broadcast()`, publish to Redis when ARQ pool exists |
| API process | Subscribe on startup; inbound → `tracker.broadcast_external(event)` (local SSE only, no re-publish) |
| API in-process jobs | Local broadcast only (no Redis) |

**Fallback:** No `REDIS_URL` → current in-process tracker behavior unchanged.

---

## Backend Fixes

### `GET /sync/status`

Add `and not task_queue.is_arq_active()` to stale-reset guard (mirror `index_db_status`).

### `GET /repos/status`

```python
is_indexing = (
    (checkpoint is not None and checkpoint.status == "running")
    or (in_memory_task and not in_memory_task.done())
)
```

Return `workflow_id` from checkpoint when present.

### Repo ARQ dedup

If `existing_cp.status == "running"` before spawn → return `None` (409), do **not** mark interrupted.

---

## Frontend Contract

### Hook: `useKnowledgePipelineStatus(projectId: string | null)`

- Poll `pipeline-status` every **3s** when `any_running`, else **30s**.
- On `any_running → false` transition: `clearReadinessCache(projectId)`.
- Call `taskStore.seedFromPipelineStatus(status)`.

### UI surfaces

| Component | Behavior |
|-----------|----------|
| Sidebar | Poll via hook; banner when `repo.is_indexing`; WorkflowProgress from `repo.workflow_id` |
| SyncStatusIndicator | Always visible for active connection; show idle/not-synced |
| KnowledgeHealthPanel | Running badge from hook + task-store step |
| ReadinessGate | Poll pipeline-status after Run |
| OnboardingWizard | Real DB index poll; optional sync step |
| ActiveTasksWidget | Filter by active project; no dismiss while DB says running |
| ConnectionSelector | Start poll on mount if pipeline-status says running |

---

## Logging

| Location | Level | Message pattern |
|----------|-------|-----------------|
| `_dispatch_code_db_sync` | INFO | `code_db_sync dispatched mode={arq\|inprocess} connection=... project=...` |
| `run_code_db_sync` finally | INFO | `completed tables=N matched=M` |
| `_maybe_autostart_sync_chain` | INFO | `auto_sync skipped reason=...` |
| `PipelineStatusService` | DEBUG | `pipeline-status any_running=...` |

---

## File Layout

| Create | Modify |
|--------|--------|
| `backend/app/services/pipeline_status_service.py` | `connections.py`, `repos.py`, `projects.py`, `tasks.py` |
| `frontend/src/hooks/useKnowledgePipelineStatus.ts` | `workflow_tracker.py`, `main.py`, `worker.py` |
| | `task-store.ts`, Sidebar, SyncStatusIndicator, etc. |
