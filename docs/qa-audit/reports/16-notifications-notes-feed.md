# Module 16 — Notifications, Notes & Feed — Audit Report

**Round 1** · 2026-06-24 · Scope: `routes/notifications.py`, `routes/notes.py`, `routes/feed.py`,
`services/note_service.py`. (InsightFeedAgent `run_scan` internals deferred to R2.)

This module is **comparatively clean** — authorization and ownership scoping are consistently
applied. The findings are minor and mostly cross-references to the read-only-guard root cause
(F-CONN-01/02).

**Positive notes (verified):**
- **Notifications are strictly user-scoped**: every query filters `Notification.user_id ==
  user_id`; `mark_read` matches both `id` AND `user_id` (no IDOR); `read-all` scoped to the user
  (`notifications.py:38/55/72/96`).
- **Notes access control is correct**: `_require_note_access` = `require_role(project, viewer)`
  **and** (`note.user_id == user` OR `note.is_shared`) (`notes.py:96-97`); `_require_note_owner`
  rejects non-creators (`:81`); create/list require `viewer` membership.
- **`execute_note` is well-guarded**: ownership check, connection-exists check, **cross-project
  guard** (`conn.project_id != note.project_id → 403`, `:239-240`), `SafetyGuard` applied keyed on
  `is_read_only` **before** execution (`:247-256`), row cap (`_RAW_RESULT_ROW_CAP`), and audit
  log. Connector is connected/disconnected in a `finally`.
- **Feed is scoped**: scan requires **owner**, opportunities require **viewer**, project_id passes
  `validate_safe_id` (path-traversal guard) (`feed.py:30/56/104-106`).

Severity: 🔴 Critical · 🟠 High · 🟡 Medium · 🟢 Low · ⚪ Info

---

## F-NOTE-01 — 🟢 Low — Note execution inherits the regex-guard / chokepoint limitation (cross-ref F-CONN-01/02, F-SCHED-02)

**Type:** Security (defense-in-depth, shared root cause)
**Location:** `routes/notes.py:247-262` — `guard.validate(...)` then `connector.execute_query(...)`
directly (not via `ValidationLoop`); `note.sql_query` is user-authored and a **viewer** can
create+execute a note.

**Description.** Unlike batch (F-SCHED-02, unverified) `execute_note` *does* call the
`SafetyGuard` — good. But it's the same call-site-guard pattern (not the connector chokepoint,
F-CONN-01) and relies on the **regex** guard, which is bypassable (F-CONN-02: comment-split DDL,
`INTO OUTFILE`, `COPY … PROGRAM`, etc.). So a viewer authoring a crafted note `sql_query` could in
principle bypass read-only on an `is_read_only` connection.

**Proposed fix.** Resolved centrally by F-CONN-01 (move read-only enforcement to the connector /
DB level) — once that lands, note execution is covered automatically. No note-specific fix needed
beyond routing through the shared guarded-execute path.

---

## F-NOTE-02 — 🟢 Low — Fresh connect/disconnect per note execution (no pool reuse)

**Type:** Performance
**Location:** `routes/notes.py:258-264` (`get_connector(...)` → `connect` → `execute_query` →
`disconnect` each call).

**Description.** Each `execute_note` opens and tears down a brand-new connector connection rather
than reusing the process-wide pooled/cached connector (per `connector_key`). For frequently
re-run notes this adds per-call connection overhead (and, over SSH-tunnel connections, a fresh
tunnel handshake).

**Proposed fix.** Reuse the cached connector (the same path the agent uses) instead of a
throwaway connect/disconnect, or pool note executions.

---

## F-NOTE-03 — ⚪ Info — Notes store a `last_result_json` snapshot (same staleness shape as dashboards)

**Type:** Observation (freshness, §7)
**Location:** `routes/notes.py:269/287` (`last_result_json`, `update_result`).

**Description.** A note caches its last result (`last_result_json` / `last_executed_at`). Viewing a
shared note shows the **cached** result, which can be stale, until someone re-executes — the same
freshness shape as dashboards (F-VIZ-01). The `last_executed_at` timestamp at least exists here
(better than dashboards), so a freshness indicator is feasible.

**Proposed fix.** Surface `last_executed_at` as an "as of" staleness signal in the notes UI;
consider auto-refresh or a stale badge.

---

## Test gaps (⚪ Info)

- (Positive coverage worth locking in) No regression test that `mark_read`/`execute_note` reject a
  note/notification belonging to **another** user (the checks exist; assert them).
- No test that `execute_note` blocks a write on an `is_read_only` connection (will be covered by
  the F-CONN-01 central fix).

## Summary

| id | sev | one-line |
|----|-----|----------|
| F-NOTE-01 | 🟢 | Note exec uses call-site regex guard + direct execute (cross-ref F-CONN-01/02) |
| F-NOTE-02 | 🟢 | Fresh connect/disconnect per note execution (no pool reuse) |
| F-NOTE-03 | ⚪ | Notes cache `last_result_json` snapshot — staleness like dashboards |

**Next-round focus:** `InsightFeedAgent.run_scan` (bounded? guarded? cost per scan); feed insight
list endpoint scoping + pagination caps; notification creation paths (system-only? any user-driven
injection?); note `is_shared` toggle authorization (creator-only?).
