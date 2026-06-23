# Module 05 — Chat & Orchestration — Audit Report

**Round 1 (first pass — highest-risk surface)** · 2026-06-23 · Scope this pass:
`routes/chat.py` (REST `/ask`, SSE `/ask/stream`, WS `/ws/...`), WS ticket auth
(`core/ws_tickets.py`), and orchestrator control-flow (`agents/orchestrator.py` replan/pipeline-
end), `agents/stage_executor.py` (scanned). **Deferred to round 2:** deep internals of
`adaptive_planner`, `data_gate`, `answer_validator`, `stage_validator`, budget-accounting
accuracy, and session rotation.

Documented contract (CLAUDE.md request-lifecycle): `ConversationalAgent.run()` wraps everything
in try/except/finally and emits `pipeline_end` even on crash; budget gate + `agent_limiter` on
all chat entry points; WS auth via single-use ticket (never URL).

**Positive notes (verified):**
- WS auth is strong: single-use, short-TTL (30s), opaque ticket bound to
  (user, project, connection), carried in `Sec-WebSocket-Protocol` (not the URL); redeemed
  atomically; access re-checked after redeem (`chat.py:1335-1354`).
- `agent_limiter` acquire/release is **balanced** on the WS path (releases at 1474/1491/1508 for
  early-continues + a `finally` at 1701-1709) and the HTTP paths have `finally` releases
  (487/832/1230/1252).
- Token-budget gate (F-FIN-1) is applied before LLM work on REST, SSE, and WS paths.
- The orchestrator replan loop is correctly bounded (`replan_count < settings.max_pipeline_replans`,
  `orchestrator.py:1969-2055`); `pipeline_end` is emitted via try/except with `logger.warning`
  (logged, not silently swallowed — `:524-560`).
- `session_processing_lock` serialises concurrent processing on the same session (obs 19293/19438).

Severity: 🔴 Critical · 🟠 High · 🟡 Medium · 🟢 Low · ⚪ Info

---

## F-CHAT-01 — 🟡 Medium — WS authorization is checked only at connect; a long-lived socket never re-verifies membership

**Type:** Security (multi-tenancy)
**Location:** `routes/chat.py:1340-1354` (access check at connect), `:1406-1410` (role check at
setup), `:1453+` (per-message loop with no re-check).

**Description.** Project access and role are verified once, during the handshake/setup. The
message loop then services unlimited messages over a long-lived socket without re-checking
membership. If the user is removed from the project (or downgraded, or the connection is deleted)
**while the socket is open**, they retain a fully functional query channel — including access to
the connection's data — until they happen to disconnect. There's also a minor TOCTOU: the access
check (1341) and setup (1405) use two separate sessions, so membership can change in between.

**Impact.** Revocation isn't effective until disconnect; a removed member can keep querying a
tenant's database for the life of the socket.

**Proposed fix.** Re-verify membership (and connection ownership) at the top of each message
iteration — `get_role` is a cheap indexed lookup — and close the socket (4003) if it no longer
resolves. Optionally bound socket lifetime and force periodic re-auth.

---

## F-CHAT-02 — 🟡 Medium — A chat session row is created on every WS connect, before any message

**Type:** Bug (resource / data hygiene)
**Location:** `routes/chat.py:1438-1444`.

**Description.** `create_session(...)` runs unconditionally during WS setup, before the client
sends anything. A browser that opens a socket speculatively (or reconnects on network blips, or
opens/closes during navigation) accumulates empty `chat_session` rows that were never used. There
is no "materialise on first message" guard.

**Impact.** Orphan empty sessions accumulate in the DB and clutter the session list / history UI;
reconnect churn amplifies it.

**Proposed fix.** Defer session creation until the first valid `WsChatMessage` arrives (lazy
init), or reap empty sessions (no messages) on disconnect / via maintenance.

---

## F-CHAT-03 — 🟡 Medium — `_relay_events` silently stops streaming progress after a 60s idle gap on a still-running pipeline

**Type:** Bug (UX / observability)
**Location:** `routes/chat.py:1365-1402` (`await asyncio.wait_for(queue.get(), timeout=60)` →
`except TimeoutError: logger.debug(...); return`).

**Description.** The relay coroutine pulls workflow events with a 60s per-event timeout. A single
pipeline step that emits no events for >60s (e.g. a slow LLM call or a long SQL execution) trips
the timeout, the relay logs at debug level and **returns**, permanently ending live progress
delivery for that socket — even though the pipeline keeps running and will still emit
`pipeline_end`. The user sees progress freeze with no error.

**Impact.** On legitimately slow steps, the live reasoning/progress panel stalls and never
resumes; the terminal `pipeline_end`/result may be missed by the relay path.

**Proposed fix.** Treat the 60s timeout as a keepalive tick (send a heartbeat / `continue`),
not a terminal condition; only stop on `pipeline_end` or an explicit cancel/disconnect. Bound the
relay by total wall-clock against the pipeline budget instead of per-event idle.

---

## F-CHAT-04 — 🟢 Low — WS captures decrypted connection config once; mid-session credential changes are stale

**Type:** Bug (edge case)
**Location:** `routes/chat.py:1412-1433` (`config` built once at setup).

**Description.** The decrypted `config` (credentials) is resolved a single time at WS setup. If
the user updates the connection password or settings mid-session, the socket keeps using the
stale config until reconnect, producing confusing auth failures or querying with old settings.

**Proposed fix.** Re-resolve config when the connection's `updated_at` changes, or invalidate the
socket's cached config on connection-update events.

---

## F-CHAT-05 — ⚪ Info (cross-cutting) — ~51 silent exception handlers mask errors (obs 21209)

**Type:** Observability / honest-degradation principle
**Location:** Codebase-wide (observation 21209: "51 silent exception handlers (`except: pass`)").

**Description.** A repo-wide pattern of `except ...: pass` (or debug-only logging) swallows
failures, which conflicts with the project's stated "never swallow errors silently / honest
degradation" principle. The orchestrator's `pipeline_end` handlers are a *good* counter-example
(they `logger.warning(..., exc_info=True)`), but many others hide root causes and make pipeline
failures look like successes (cf. `orchestrator.py:1830` comment about a green check shown after
exhausting replans).

**Impact.** Bugs hide; failed sub-steps surface as partial/empty success; debugging is harder.

**Proposed fix.** Sweep the 51 sites; convert silent passes to at least `logger.warning(...,
exc_info=True)`, and fail-closed where the swallowed error affects correctness (e.g. data gates).
Track as a dedicated tech-debt task.

---

## F-CHAT-06 — 🟢 Low — `websocket.receive_json()` has no explicit payload-size cap

**Type:** Hardening
**Location:** `routes/chat.py:1454`.

**Description.** Inbound WS messages are parsed with `receive_json()` and validated via
`WsChatMessage`, but there's no explicit byte cap before parsing — it relies on Starlette
defaults. A large/abusive payload is parsed into memory before validation rejects it.

**Proposed fix.** Enforce a max frame/message size (reject oversize before `model_validate`).

---

## Test gaps (⚪ Info)

- No test that a member removed mid-WS-session loses access on the next message (F-CHAT-01).
- No test that opening+closing a WS without sending a message does **not** persist a session
  (F-CHAT-02).
- No test that a >60s silent step keeps the progress relay alive (F-CHAT-03).

## Summary

| id | sev | one-line |
|----|-----|----------|
| F-CHAT-01 | 🟡 | WS authz checked only at connect; revocation ineffective until disconnect |
| F-CHAT-02 | 🟡 | Empty chat_session created on every WS connect → orphan-session bloat |
| F-CHAT-03 | 🟡 | `_relay_events` 60s idle timeout silently kills progress on slow steps |
| F-CHAT-04 | 🟢 | WS uses connection config captured once; stale after mid-session edits |
| F-CHAT-05 | ⚪ | ~51 silent exception handlers mask errors (cross-cutting, obs 21209) |
| F-CHAT-06 | 🟢 | WS `receive_json` lacks explicit payload-size cap |

**Next-round focus (Module 05 deep dive):** `adaptive_planner.replan` correctness and infinite-
replan guards; `data_gate` hard-check semantics; `answer_validator` fail-open/closed behaviour;
budget accounting accuracy (estimated vs actual tokens; double-counting across replans);
`stage_executor` parallel-stage failure classification (transient/configuration/data_missing/
fatal) and whether a `fatal` in one parallel stage cancels siblings cleanly; session-rotation
summariser auth/PII handling.
