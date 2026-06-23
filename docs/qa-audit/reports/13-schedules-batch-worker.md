# Module 13 — Schedules, Batch & Worker — Audit Report

**Round 1** · 2026-06-24 · Scope: `core/task_queue.py`, `worker.py`, `routes/schedules.py`,
`routes/batch.py`, `services/stale_run_reaper.py`, scheduler loop in `main.py`,
`services/run_coordinator.py` (scanned).

Documented contract (CLAUDE.md): ARQ worker when `REDIS_URL` set, else in-process fallback (keep
both working); `StaleRunReaper` resets stuck `running` rows after
`stale_running_heartbeat_timeout_seconds` (300s); heartbeat every 30s; reaper sweeps every 60s.

**Positive notes (verified):**
- Schedules auth is solid: create/update/delete/run-now require **owner**; list/get require
  **viewer**; cron validated via `SchedulerService.validate_cron` (`schedules.py`).
- Scheduler uses **atomic multi-dyno single-flight** (`claim_due`) so a due schedule runs once
  across dynos, and re-validates the stored SQL through `SafetyGuard` at execution
  (`main.py:~853`).
- `task_queue` in-process fallback is well-behaved: retains the task handle (`_fallback_tasks`),
  dedups by `task_id`, and a done-callback **logs exceptions** (`task_queue.py:125-140`) — no
  GC/orphan bug and no silent swallow (contrast F-PROJ-05, which bypasses this abstraction).
- Reaper is idempotent + concurrency-safe (only touches rows past the cutoff).

Severity: 🔴 Critical · 🟠 High · 🟡 Medium · 🟢 Low · ⚪ Info

---

## F-SCHED-01 — 🟡 Medium — Scheduled queries keep executing after the creating owner loses access (revocation gap)

**Type:** Security (stale authorization)
**Location:** scheduler loop in `main.py` (iterates `get_due_schedules` → `claim_due` → execute);
`routes/schedules.py:122` stores `user_id` but execution never re-checks it.

**Description.** A schedule stores its creator `user_id`, but the scheduler executes the stored
SQL purely on cron, **without re-verifying** that the creator is still an owner/member of the
project (or that the connection still belongs to the project). If the creating owner is later
removed/downgraded, their scheduled queries keep running against the connection indefinitely.

**Impact.** Revocation is not effective for schedules — a removed member's automated queries
continue to read (or, on DML connections, write) tenant data.

**Proposed fix.** At execution, re-check that `schedule.user_id` still has the required role on
`schedule.project_id` and that the connection is still in the project; otherwise disable the
schedule (and surface why). Consider re-binding ownership to the project rather than an individual
user.

---

## F-SCHED-02 — 🟡 Medium — Batch `/execute` runs user-supplied raw SQL with only **viewer** role (verify guard/read-only)

**Type:** Security (authorization / read-only enforcement)
**Location:** `routes/batch.py:57-83` (`require_role(viewer)`, `queries: list[BatchQueryItem]`
each with raw `sql: str` up to 50k), executed by `run_batch` in the worker.

**Description.** Batch execution accepts a list of **raw, user-authored SQL** strings and is gated
at only **viewer** level. Unlike the chat path (LLM-generated SQL routed through `ValidationLoop`'s
`SafetyGuard`), this is direct user SQL. The risk is whether `run_batch` routes each query through
the `SafetyGuard` + connection read-only enforcement. If it executes via the connector directly
(the chokepoint gap, F-CONN-01), a **viewer** could run arbitrary SQL — and on an `is_read_only=
False` connection, writes — bypassing the read-only posture.

**Impact.** Potential read-only bypass / privilege mismatch (viewer running arbitrary SQL).
Severity depends on whether `run_batch` applies the guard — flagged for verification.

**Proposed fix.** Confirm `run_batch` validates every query via `SafetyGuard` keyed on the
connection's `is_read_only`; if not, add it (or move the guard to the connector chokepoint per
F-CONN-01). Reconsider whether arbitrary-SQL batch should require **editor**, not viewer.

---

## F-SCHED-03 — 🟡 Medium — `_stale_run` treats NULL `heartbeat_at` as unconditionally stale → immediate-reap race

**Type:** Bug (race)
**Location:** `services/stale_run_reaper.py:35-38` (`_stale_run`) vs `:27-31` (`_stale`).

**Description.** `_stale` (summaries) considers a NULL-heartbeat row stale only when
`updated_at < cutoff` (an age guard). But `_stale_run` drops that guard: a run is stale if
`heartbeat_at < cutoff` **OR `heartbeat_at IS NULL`** — unconditionally. So a freshly-created run
row whose first heartbeat hasn't been written yet is immediately eligible for reaping. If the
reaper sweep lands between run creation and first heartbeat, it flips a live, just-started run to
`failed` (spurious failure, and a retry could double-run the work).

**Impact.** Spurious `failed` status on newly-started runs (if run rows don't set `heartbeat_at`
at creation); confusing UX + possible duplicate execution.

**Proposed fix.** Make `_stale_run` symmetric with `_stale`: for the NULL-heartbeat case, require
`updated_at < cutoff`. Alternatively, set `heartbeat_at = now()` atomically at run creation so NULL
never denotes a live run. Add a test: create a run, sweep immediately, assert it is **not** reaped.

---

## F-SCHED-04 — 🟡 Medium — ARQ enqueue failure silently falls back to running heavy jobs in-process on the web dyno

**Type:** Reliability / isolation
**Location:** `core/task_queue.py:92-126` (on ARQ `enqueue_job` exception → log + fall through to
`asyncio.create_task`).

**Description.** When `_arq_pool` is active (web dyno) but a single `enqueue_job` call raises (e.g.
a transient Redis blip), the code falls back to `asyncio.create_task` **in the current process** —
the web dyno. A heavy job (`run_repo_index`, `run_db_index`) then executes on the request event
loop instead of the worker, defeating worker isolation, competing with request handling, and dying
on the next web restart (where the reaper must clean it up).

**Impact.** Transient Redis errors silently relocate heavy work onto the API process — latency
spikes / starvation, and lost work on restart.

**Proposed fix.** On the web dyno, treat ARQ enqueue failure as a hard error (retry enqueue /
surface failure) rather than silently running in-process; only use the in-process path when ARQ is
genuinely not configured (`_arq_pool is None`).

---

## F-SCHED-05 — 🟢 Low — In-process fallback dedup is per-process; no cross-process single-flight without Redis

**Type:** Robustness
**Location:** `task_queue.py:119-126` (`_fallback_tasks` is in-memory).

**Description.** `task_id` dedup in fallback mode is per-process. Without Redis (so no ARQ), if more
than one API process runs, the same `task_id` can execute concurrently on each (no shared lock).
Acceptable for single-process dev, but a footgun if fallback mode is ever run multi-process.

**Proposed fix.** Document that fallback mode assumes single-process, or add a DB-level claim
(like `claim_due`) for fallback dedup.

---

## F-SCHED-06 — 🟢 Low — No per-schedule frequency/cost guard

**Type:** Resource / cost
**Location:** `routes/schedules.py:101-133` (only cron validity checked).

**Description.** An owner can schedule an expensive query at `* * * * *` (every minute). Overlapping
runs are de-duped by `RunCoordinator`, but fast non-overlapping runs still consume DB/LLM/compute
each minute with no minimum-interval or cost ceiling.

**Proposed fix.** Enforce a minimum cron interval and/or a per-project schedule budget.

---

## Test gaps (⚪ Info)

- No test that a schedule whose creator lost access is disabled/skipped (F-SCHED-01).
- No test that batch `/execute` enforces read-only / SafetyGuard for a viewer (F-SCHED-02).
- No test that a just-created run isn't reaped before its first heartbeat (F-SCHED-03).

## Summary

| id | sev | one-line |
|----|-----|----------|
| F-SCHED-01 | 🟡 | Schedules keep running after creator loses access (no membership re-check) |
| F-SCHED-02 | 🟡 | Batch `/execute` runs raw user SQL at viewer role — verify guard/read-only |
| F-SCHED-03 | 🟡 | `_stale_run` reaps NULL-heartbeat runs unconditionally → immediate-reap race |
| F-SCHED-04 | 🟡 | ARQ enqueue failure silently runs heavy jobs in-process on the web dyno |
| F-SCHED-05 | 🟢 | Fallback dedup is per-process; no cross-process single-flight without Redis |
| F-SCHED-06 | 🟢 | No min-interval / cost guard on schedules |

**Next-round focus:** `run_batch` executor (confirm SafetyGuard + per-query/result caps + token
budget); `RunCoordinator` heartbeat-tick frequency vs reaper timeout for long indexing;
`worker.py` job functions error handling + retry semantics; maintenance cron (decay/TTL/backup)
failure isolation; whether `claim_due` + cron parsing handles DST/timezone correctly.
