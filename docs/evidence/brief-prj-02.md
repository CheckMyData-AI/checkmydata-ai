# PRJ-02 — run liveness: one heartbeat writer, one truth (task-pipeline run, 2026-09-14)

**Standard:** Proof of Done.

## Source ledger (stage 0 harvest)

| Source | Found | What it contributed |
|---|---|---|
| `docs/evidence/retro.md` | yes, 7 standing instructions | S-03 (AST guard where the defect is invisible at the call site), S-05 (assert from the contract), S-06 (verify on the artefact) all bind this run |
| `docs/evidence/backlog.md` | 7 open rows | B-06 (P0, awaiting an operator decision) is not this run's |
| `docs/evidence/verification.md` | 3 pending | PRJ-01 R3 still `partial` |
| PRJ-01 live measurement | `scratchpad/prj02-live-measurement.txt` | the defect, measured with both rows in one frame |
| `docs/audits/2026-09-13-…` | yes | S-03, C-01, S-06, S-09 |
| the code | yes | **three corrections to this run's own brief, below** |
| `graphify-out/graph.json` | yes | refreshed at stage 9 |

## What the harvest corrected in the task statement

The brief I was given asked for work that is already done or would be done the wrong way:

1. **"one `RunBeat(run_id)` writer" — it exists.** `run_coordinator._run_beat(run_id)`
   (`:122-145`) is already correct: own session, targeted UPDATE, unconditioned on status.
2. **"log heartbeat writer failures at WARNING" — already done.** `core/heartbeat.py:41-53`
   logs each failure with a **consecutive streak**, deliberately at WARNING because
   "production runs at INFO".
3. **`run_id` is the wrong key for two of the four.** `DbIndexPipeline.run` and
   `CodeDbSyncPipeline.run` receive `wf_id` and not `run_id`, and
   `IndexingRun.workflow_id` carries a **UNIQUE** index (`models/indexing_run.py:86`).
   `pipeline_runner._hb` already beats by it and already logs the zero-rowcount case —
   "a beat keyed on a workflow id the row does not carry looks exactly like a beat that
   worked". Extracting that is smaller and safer than changing six call sites.

**And the summary beats are not redundant.** The reaper sweeps **four** models —
`DbIndexSummary`, `CodeDbSyncSummary`, `IndexingCheckpoint`, `IndexingRun`
(`stale_run_reaper.py:296-312`), each on its own `heartbeat_at`. The summary beats keep
their own rows alive and must stay. The defect is that `IndexingRun` — the row
`/sync-history`, the UI and the reaper's requeue budget read — is beaten for two kinds
**only by manifest step events**, and `analyze_sync` emits none between tables.

## Grill — decisions taken

| # | Question | Decision | Why |
|---|---|---|---|
| G1 | One writer or two per pipeline? | **Both rows beaten, one shared writer for the run row** extracted from `pipeline_runner._hb` into `run_coordinator.run_beat_by_workflow(wf_id)` | the reaper sweeps both rows; the summary beat is not the bug |
| G2 | Key: `run_id` or `workflow_id`? | **`workflow_id`** for the two pipelines (they hold it; UNIQUE index), `run_id` for the daily-sync parent (it holds that) | no signature changes, and the extracted writer already handles the silent-no-match trap |
| G3 | daily_sync's `status == "running"` condition | **removed** | it is the exact shape deleted from `pipeline_runner._hb` on 2026-08-31 with the note "NOT conditioned on status, and that is the whole point" |
| G4 | A reaped-then-completed parent | **reconciled**: `run_for_project` folds its own terminal outcome into a row the reaper gave up on | measured: the 02:08 sync completed in 619 s with its row reading `failed` |
| G5 | Regression lock shape | **AST guard** that no beat writer is status-conditioned, plus behaviour tests per kind | S-03: the defect is invisible at the call site, and this exact condition has now been written three times |

## REQ table

| REQ | Requirement | Verified by |
|---|---|---|
| R1 | A `db_index` run beats `IndexingRun` on a wall clock, not only on step events | test: a stalled `fetch_samples` longer than the reaper timeout leaves `heartbeat_at` advancing |
| R2 | Same for `code_db_sync` across `analyze_sync` | same shape, per kind |
| R3 | The `daily_sync` parent's beat is **not** conditioned on status, so a reaped run can re-assert liveness | test: flip the row to `failed`, beat, assert `heartbeat_at` moved |
| R4 | A reaped-then-completed run ends `completed`, not `failed` | test: reap mid-run, finish, assert terminal status and `/sync-history` |
| R5 | No beat writer anywhere may be status-conditioned | AST guard over `app/` |
| R6 | The summary rows keep their own beats | test: both rows advance during one run |
| R7 | `_fetch_live_table_names` runs under the heartbeat and cannot hang unbounded | test: a slow connector does not outlive the guard |
| R8 | A failed pipeline sets `IndexingCheckpoint.status` | test: `run()` swallowing an exception still marks the checkpoint |
| R9 | Suite green, coverage ≥ 80% | `make check` + CI |
| R10 | Production: no run is reaped that later completes | 14 days of `indexing_runs` after deploy |
